#include "csv_io.hpp"
#include <fstream>
#include <sstream>
#include <stdexcept>

std::vector<std::string> split_csv_line(const std::string& line) {
  std::vector<std::string> out;
  std::stringstream ss(line);
  std::string item;
  while (std::getline(ss, item, ',')) out.push_back(item);
  return out;
}

CsvTable read_csv(const std::string& path) {
  std::ifstream in(path);
  if (!in) throw std::runtime_error("Cannot open CSV: " + path);
  CsvTable t;
  std::string line;
  if (!std::getline(in, line)) throw std::runtime_error("Empty CSV: " + path);
  t.header = split_csv_line(line);
  while (std::getline(in, line)) {
    if (line.empty()) continue;
    auto row = split_csv_line(line);
    if (row.size() != t.header.size()) throw std::runtime_error("Malformed CSV row in: " + path);
    t.rows.push_back(std::move(row));
  }
  return t;
}

void write_csv(const std::string& path, const CsvTable& table) {
  std::ofstream out(path);
  if (!out) throw std::runtime_error("Cannot write CSV: " + path);
  for (size_t i = 0; i < table.header.size(); ++i) {
    if (i) out << ',';
    out << table.header[i];
  }
  out << '\n';
  for (const auto& row : table.rows) {
    for (size_t i = 0; i < row.size(); ++i) {
      if (i) out << ',';
      out << row[i];
    }
    out << '\n';
  }
}
