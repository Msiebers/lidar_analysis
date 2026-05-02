#pragma once
#include <string>
#include <vector>

struct CsvTable {
  std::vector<std::string> header;
  std::vector<std::vector<std::string>> rows;
};

CsvTable read_csv(const std::string& path);
void write_csv(const std::string& path, const CsvTable& table);
std::vector<std::string> split_csv_line(const std::string& line);
