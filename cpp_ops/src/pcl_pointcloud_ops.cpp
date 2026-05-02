#include "csv_io.hpp"
#include <cctype>
#include <fstream>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

struct Job { std::string target_id, input_csv, output_csv, ops_json; };

static void print_help() {
  std::cout << "Usage:\n"
            << "  pcl_pointcloud_ops_batch <manifest.csv>\n\n"
            << "Manifest columns:\n"
            << "  target_id,input_csv,output_csv,ops_json\n\n"
            << "Current support:\n"
            << "  - no-op/copy (default)\n"
            << "  - scalar_range_filter via ops_json\n";
}

static std::optional<double> parse_nullable_number(const std::string& s, const std::string& key) {
  auto pos = s.find("\"" + key + "\"");
  if (pos == std::string::npos) return std::nullopt;
  auto colon = s.find(':', pos);
  if (colon == std::string::npos) return std::nullopt;
  auto start = s.find_first_not_of(" \t", colon + 1);
  if (start == std::string::npos) return std::nullopt;
  if (s.compare(start, 4, "null") == 0) return std::nullopt;
  size_t end = start;
  while (end < s.size() && (std::isdigit(s[end]) || s[end] == '.' || s[end] == '-' || s[end] == '+')) ++end;
  return std::stod(s.substr(start, end - start));
}

static std::string parse_string_field(const std::string& s, const std::string& key, const std::string& def = "") {
  auto pos = s.find("\"" + key + "\"");
  if (pos == std::string::npos) return def;
  auto colon = s.find(':', pos);
  auto q1 = s.find('"', colon + 1);
  auto q2 = s.find('"', q1 + 1);
  if (q1 == std::string::npos || q2 == std::string::npos) return def;
  return s.substr(q1 + 1, q2 - q1 - 1);
}

int main(int argc, char** argv) {
  if (argc == 1) {
    print_help();
    return 0;
  }
  const std::string arg1 = argv[1] ? std::string(argv[1]) : std::string();
  if (arg1 == "--help" || arg1 == "-h") {
    print_help();
    return 0;
  }

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
      const bool do_scalar_range = j.ops_json.find("scalar_range_filter") != std::string::npos &&
                                   j.ops_json.find("\"enabled\":true") != std::string::npos;
      if (do_scalar_range) {
        const std::string scalar = parse_string_field(j.ops_json, "scalar", "rssi_norm");
        const auto min_v = parse_nullable_number(j.ops_json, "min_value");
        const auto max_v = parse_nullable_number(j.ops_json, "max_value");
        size_t scalar_idx = std::string::npos;
        for (size_t c = 0; c < table.header.size(); ++c) {
          if (table.header[c] == scalar) { scalar_idx = c; break; }
        }
        if (scalar_idx == std::string::npos) throw std::runtime_error("Missing scalar column: " + scalar);
        const size_t before = table.rows.size();
        if (min_v.has_value() || max_v.has_value()) {
          std::vector<std::vector<std::string>> kept;
          kept.reserve(table.rows.size());
          for (const auto& row : table.rows) {
            const double v = std::stod(row[scalar_idx]);
            bool ok = true;
            if (min_v.has_value()) ok = ok && (v >= *min_v);
            if (max_v.has_value()) ok = ok && (v <= *max_v);
            if (ok) kept.push_back(row);
          }
          table.rows.swap(kept);
        }
        std::cout << "[pcl_ops] scalar_range_filter scalar=" << scalar
                  << " before=" << before << " after=" << table.rows.size() << "\n";
      }
      write_csv(j.output_csv, table);
    }
    return 0;
  } catch (const std::exception& e) {
    std::cerr << "[pcl_ops][ERROR] " << e.what() << "\n";
    return 2;
  }
}
