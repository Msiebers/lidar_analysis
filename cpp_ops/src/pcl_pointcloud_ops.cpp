#include "csv_io.hpp"
#include <algorithm>
#include <cmath>
#include <cctype>
#include <fstream>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

#include <pcl/filters/statistical_outlier_removal.h>
#include <pcl/kdtree/kdtree_flann.h>
#include <pcl/point_cloud.h>
#include <pcl/point_types.h>

struct Job { std::string target_id, input_csv, output_csv, ops_config_path; };
struct OpCfg { std::unordered_map<std::string, std::string> kv; };

static void print_help(){
  std::cout << "Usage:\n  pcl_pointcloud_ops_batch <manifest.csv>\n\n"
            << "Manifest columns:\n  target_id,input_csv,output_csv,ops_config_path\n";
}

static std::string trim(std::string s){ while(!s.empty()&&std::isspace((unsigned char)s.back())) s.pop_back(); size_t i=0; while(i<s.size()&&std::isspace((unsigned char)s[i])) i++; return s.substr(i);} 
static bool is_null(const std::string& v){ return trim(v)=="null"; }
static double to_d(const std::string& v){ return std::stod(trim(v)); }
static int to_i(const std::string& v){ return std::stoi(trim(v)); }
static bool to_b(const std::string& v){ auto t=trim(v); return t=="true"||t=="1"; }
static std::string unquote(std::string v){ v=trim(v); if(v.size()>=2&&v.front()=='"'&&v.back()=='"') return v.substr(1,v.size()-2); return v; }

static std::vector<OpCfg> parse_ops_json(const std::string& p){
  std::ifstream f(p); if(!f) return {};
  std::string s((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
  auto ops_pos = s.find("\"ops\""); if(ops_pos==std::string::npos) return {};
  auto lb = s.find('[', ops_pos); auto rb = s.find(']', lb); if(lb==std::string::npos||rb==std::string::npos) return {};
  std::string arr = s.substr(lb+1, rb-lb-1);
  std::vector<OpCfg> ops;
  size_t i=0;
  while(i<arr.size()){
    auto ob=arr.find('{',i); if(ob==std::string::npos) break; int depth=1; size_t j=ob+1;
    while(j<arr.size()&&depth>0){ if(arr[j]=='{') depth++; else if(arr[j]=='}') depth--; j++; }
    if(depth!=0) break;
    std::string obj=arr.substr(ob+1,j-ob-2);
    OpCfg op;
    size_t k=0;
    while(k<obj.size()){
      auto q1=obj.find('"',k); if(q1==std::string::npos) break; auto q2=obj.find('"',q1+1); if(q2==std::string::npos) break;
      std::string key=obj.substr(q1+1,q2-q1-1); auto c=obj.find(':',q2); if(c==std::string::npos) break;
      size_t v0=obj.find_first_not_of(" \t",c+1); if(v0==std::string::npos) break; size_t v1=v0;
      if(obj[v0]=='"'){ v1=obj.find('"',v0+1); if(v1==std::string::npos) break; v1++; }
      else { while(v1<obj.size() && obj[v1]!=',') v1++; }
      op.kv[key]=trim(obj.substr(v0,v1-v0));
      k=obj.find(',',v1); if(k==std::string::npos) break; k++;
    }
    ops.push_back(op); i=j;
  }
  return ops;
}

struct Table { std::vector<std::string> h; std::vector<std::vector<double>> r; std::unordered_map<std::string,size_t> idx; };
static Table to_table(const CsvTable& c){ Table t; t.h=c.header; for(size_t i=0;i<t.h.size();++i) t.idx[t.h[i]]=i; for(const auto& row:c.rows){ std::vector<double> v; v.reserve(row.size()); for(const auto& x:row){ try{ v.push_back(std::stod(x)); } catch(...){ throw std::runtime_error("Nonnumeric value in CSV data"); }} t.r.push_back(std::move(v)); } return t; }
static CsvTable from_table(const Table& t){ CsvTable c; c.header=t.h; for(const auto& row:t.r){ std::vector<std::string> s; s.reserve(row.size()); for(double v:row){ std::ostringstream oss; oss<<v; s.push_back(oss.str()); } c.rows.push_back(std::move(s)); } return c; }

static void op_scalar_range(Table& t, const OpCfg& op){
  std::string scalar = op.kv.count("scalar")?unquote(op.kv.at("scalar")):"rssi_norm";
  if(!t.idx.count(scalar)) throw std::runtime_error("Missing scalar column: "+scalar);
  size_t col=t.idx[scalar]; bool has_min=op.kv.count("min_value")&&!is_null(op.kv.at("min_value")); bool has_max=op.kv.count("max_value")&&!is_null(op.kv.at("max_value"));
  double minv=has_min?to_d(op.kv.at("min_value")):-std::numeric_limits<double>::infinity();
  double maxv=has_max?to_d(op.kv.at("max_value")): std::numeric_limits<double>::infinity();
  size_t before=t.r.size(); if(has_min||has_max){ std::vector<std::vector<double>> k; for(auto& row:t.r){ double v=row[col]; if(v>=minv&&v<=maxv) k.push_back(row);} t.r.swap(k);} std::cout<<"[pcl_ops] scalar_range_filter before="<<before<<" after="<<t.r.size()<<"\n";
}

static void op_bilateral(Table& t, const OpCfg& op){
  std::string scalar=op.kv.count("scalar")?unquote(op.kv.at("scalar")):"rssi_norm";
  if(!t.idx.count(scalar)) throw std::runtime_error("Missing scalar column: "+scalar);
  std::string out=op.kv.count("output_scalar")?unquote(op.kv.at("output_scalar")):"rssi_norm_bilateral";
  bool replace=op.kv.count("replace_scalar")?to_b(op.kv.at("replace_scalar")):false;
  size_t src=t.idx[scalar], dst=src;
  if(!replace){ if(t.idx.count(out)) throw std::runtime_error("output_scalar exists: "+out); dst=t.h.size(); t.h.push_back(out); t.idx[out]=dst; for(auto& row:t.r) row.push_back(row[src]); }
  double ss=to_d(op.kv.at("spatial_sigma_m")); double rs=to_d(op.kv.at("scalar_sigma")); double rad=to_d(op.kv.at("radius_m"));
  int min_n=op.kv.count("min_neighbors")?to_i(op.kv.at("min_neighbors")):3; int max_n=op.kv.count("max_neighbors")?to_i(op.kv.at("max_neighbors")):64;
  pcl::PointCloud<pcl::PointXYZ>::Ptr cloud(new pcl::PointCloud<pcl::PointXYZ>()); cloud->points.resize(t.r.size());
  for(size_t i=0;i<t.r.size();++i){ cloud->points[i].x=t.r[i][t.idx["X"]]; cloud->points[i].y=t.r[i][t.idx["Y"]]; cloud->points[i].z=t.r[i][t.idx["Z"]]; }
  pcl::KdTreeFLANN<pcl::PointXYZ> tree; tree.setInputCloud(cloud);
  std::vector<double> outv(t.r.size());
  for(size_t i=0;i<t.r.size();++i){ std::vector<int> idx; std::vector<float> d2; tree.radiusSearch(cloud->points[i], rad, idx, d2, max_n);
    if((int)idx.size()<min_n){ outv[i]=t.r[i][src]; continue; }
    double num=0,den=0,si=t.r[i][src];
    for(size_t k=0;k<idx.size();++k){ double sj=t.r[idx[k]][src]; double dist=std::sqrt(d2[k]); double ws=std::exp(-(dist*dist)/(2*ss*ss)); double wd=std::exp(-((si-sj)*(si-sj))/(2*rs*rs)); double w=ws*wd; num+=w*sj; den+=w; }
    outv[i]=(den>0)?num/den:si;
  }
  for(size_t i=0;i<t.r.size();++i) t.r[i][dst]=outv[i];
}

static void op_sor(Table& t, const OpCfg& op){
  int k=op.kv.count("mean_k")?to_i(op.kv.at("mean_k")):16; if((int)t.r.size()<=k){ std::cout<<"[pcl_ops][WARN] sor_filter skipped (too few points)\n"; return; }
  double th=op.kv.count("stddev_mul_thresh")?to_d(op.kv.at("stddev_mul_thresh")):2.0;
  pcl::PointCloud<pcl::PointXYZ>::Ptr cloud(new pcl::PointCloud<pcl::PointXYZ>()); cloud->points.resize(t.r.size());
  for(size_t i=0;i<t.r.size();++i){ cloud->points[i].x=t.r[i][t.idx["X"]]; cloud->points[i].y=t.r[i][t.idx["Y"]]; cloud->points[i].z=t.r[i][t.idx["Z"]]; }
  pcl::StatisticalOutlierRemoval<pcl::PointXYZ> sor; sor.setInputCloud(cloud); sor.setMeanK(k); sor.setStddevMulThresh(th); std::vector<int> inliers; sor.filter(inliers);
  std::vector<std::vector<double>> kept; kept.reserve(inliers.size()); for(int i:inliers) kept.push_back(t.r[(size_t)i]); t.r.swap(kept);
}

static void op_voxel(Table& t, const OpCfg& op){
  std::string agg=op.kv.count("aggregation")?unquote(op.kv.at("aggregation")):"centroid"; if(agg!="centroid") throw std::runtime_error("Unknown voxel aggregation: "+agg);
  double leaf=to_d(op.kv.at("leaf_size_m"));
  struct Acc{ std::vector<double> sum; int n=0;}; std::unordered_map<std::string,Acc> m;
  for(const auto& row:t.r){ long long ix=(long long)std::floor(row[t.idx["X"]]/leaf), iy=(long long)std::floor(row[t.idx["Y"]]/leaf), iz=(long long)std::floor(row[t.idx["Z"]]/leaf); std::string k=std::to_string(ix)+"|"+std::to_string(iy)+"|"+std::to_string(iz); auto& a=m[k]; if(a.n==0) a.sum.assign(row.size(),0.0); for(size_t c=0;c<row.size();++c) a.sum[c]+=row[c]; a.n++; }
  std::vector<std::vector<double>> out; out.reserve(m.size()); for(auto& kv:m){ auto& a=kv.second; std::vector<double> r(a.sum.size()); for(size_t c=0;c<r.size();++c) r[c]=a.sum[c]/a.n; out.push_back(std::move(r)); } t.r.swap(out);
}

int main(int argc,char** argv){
  if(argc==1|| (argc>=2 && (std::string(argv[1])=="--help"||std::string(argv[1])=="-h"))){ print_help(); return 0; }
  try{
    if(argc!=2) throw std::runtime_error("Usage: pcl_pointcloud_ops_batch <manifest.csv>");
    std::ifstream mf(argv[1]); if(!mf) throw std::runtime_error("Cannot open manifest");
    std::string line; if(!std::getline(mf,line)) throw std::runtime_error("Empty manifest");
    std::vector<Job> jobs; while(std::getline(mf,line)){ if(line.empty()) continue; auto c=split_csv_line(line); if(c.size()!=4) throw std::runtime_error("Manifest row must have 4 columns"); jobs.push_back({trim(c[0]),trim(c[1]),trim(c[2]),trim(c[3])}); }
    for(size_t i=0;i<jobs.size();++i){ const auto& j=jobs[i]; std::cout<<"[pcl_ops] "<<(i+1)<<"/"<<jobs.size()<<" target="<<j.target_id<<"\n"; auto csv=read_csv(j.input_csv); Table t=to_table(csv); auto ops=parse_ops_json(j.ops_config_path);
      for(const auto& op:ops){ if(!op.kv.count("enabled")||!to_b(op.kv.at("enabled"))) continue; auto name=unquote(op.kv.at("name")); if(name=="scalar_range_filter") op_scalar_range(t,op); else if(name=="bilateral_scalar_filter") op_bilateral(t,op); else if(name=="sor_filter") op_sor(t,op); else if(name=="voxel_grid") op_voxel(t,op); else throw std::runtime_error("Unknown op: "+name); }
      write_csv(j.output_csv, from_table(t));
    }
    return 0;
  } catch(const std::exception& e){ std::cerr<<"[pcl_ops][ERROR] "<<e.what()<<"\n"; return 2; }
}
