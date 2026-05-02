#include "csv_io.hpp"
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

struct Job { std::string target_id, input_csv, output_csv, ops_json; };

int main(int argc, char** argv) {
  try {
    if (argc != 2) throw std::runtime_error("Usage: pcl_pointcloud_ops_batch <manifest.csv>");
    std::ifstream mf(argv[1]);
    if (!mf) throw std::runtime_error("Cannot open manifest");
    std::string line;
    if (!std::getline(mf, line)) throw std::runtime_error("Empty manifest");
    std::vector<Job> jobs;
    while (std::getline(mf, line)) {
      if (line.empty()) continue;
      auto cols = split_csv_line(line);
      if (cols.size() != 4) throw std::runtime_error("Manifest row must have 4 columns");
      jobs.push_back({cols[0], cols[1], cols[2], cols[3]});
    }
    std::cout << "[pcl_ops] jobs=" << jobs.size() << "\n";
    for (size_t i = 0; i < jobs.size(); ++i) {
      const auto& j = jobs[i];
      std::cout << "[pcl_ops] " << (i+1) << "/" << jobs.size() << " target=" << j.target_id << "\n";
      auto table = read_csv(j.input_csv);
      // Phase 1 no-op/copy mode only
      write_csv(j.output_csv, table);
    }
    return 0;
  } catch (const std::exception& e) {
    std::cerr << "[pcl_ops][ERROR] " << e.what() << "\n";
    return 2;
  }
}
