#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <exception>
#include <fstream>
#include <iostream>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

struct Job {
  std::string target_id;
  std::string input_csv;
  std::string output_csv;
  std::string ops_config_path;
};

static std::string trim(const std::string& s) {
  size_t start = 0;
  while (start < s.size() && std::isspace(static_cast<unsigned char>(s[start]))) {
    ++start;
  }

  size_t end = s.size();
  while (end > start && std::isspace(static_cast<unsigned char>(s[end - 1]))) {
    --end;
  }

  return s.substr(start, end - start);
}

static std::vector<std::string> split_simple_csv_line(const std::string& line) {
  std::vector<std::string> cols;
  std::stringstream ss(line);
  std::string item;

  while (std::getline(ss, item, ',')) {
    cols.push_back(trim(item));
  }

  // Preserve a trailing empty column.
  if (!line.empty() && line.back() == ',') {
    cols.push_back("");
  }

  return cols;
}

static void print_usage() {
  std::cout
      << "Usage:\n"
      << "  pcl_pointcloud_ops_batch <manifest.csv>\n\n"
      << "Manifest columns:\n"
      << "  target_id,input_csv,output_csv,ops_config_path\n\n"
      << "Current support:\n"
      << "  - no-op/copy when ops_config_path is empty, missing, or has no enabled ops\n"
      << "  - scalar_range_filter via external ops JSON config\n";
}

static std::string read_text_file_or_empty(const std::string& path) {
  if (path.empty()) {
    return "";
  }

  std::ifstream in(path);
  if (!in) {
    // Required behavior for this scaffold:
    // missing config path means no-op/copy, not fatal.
    return "";
  }

  std::ostringstream ss;
  ss << in.rdbuf();
  return ss.str();
}

static bool json_has_enabled_true(const std::string& json) {
  const std::string key = "\"enabled\"";
  size_t pos = json.find(key);

  while (pos != std::string::npos) {
    size_t colon = json.find(':', pos + key.size());
    if (colon == std::string::npos) {
      return false;
    }

    size_t value_pos = colon + 1;
    while (value_pos < json.size() &&
           std::isspace(static_cast<unsigned char>(json[value_pos]))) {
      ++value_pos;
    }

    if (json.compare(value_pos, 4, "true") == 0) {
      return true;
    }

    pos = json.find(key, pos + key.size());
  }

  return false;
}

static std::string parse_string_field(
    const std::string& json,
    const std::string& field,
    const std::string& default_value) {
  const std::string key = "\"" + field + "\"";
  size_t pos = json.find(key);
  if (pos == std::string::npos) {
    return default_value;
  }

  size_t colon = json.find(':', pos + key.size());
  if (colon == std::string::npos) {
    return default_value;
  }

  size_t q1 = json.find('"', colon + 1);
  if (q1 == std::string::npos) {
    return default_value;
  }

  size_t q2 = json.find('"', q1 + 1);
  if (q2 == std::string::npos) {
    return default_value;
  }

  return json.substr(q1 + 1, q2 - q1 - 1);
}

static std::optional<double> parse_nullable_number(
    const std::string& json,
    const std::string& field) {
  const std::string key = "\"" + field + "\"";
  size_t pos = json.find(key);
  if (pos == std::string::npos) {
    return std::nullopt;
  }

  size_t colon = json.find(':', pos + key.size());
  if (colon == std::string::npos) {
    return std::nullopt;
  }

  size_t value_pos = colon + 1;
  while (value_pos < json.size() &&
         std::isspace(static_cast<unsigned char>(json[value_pos]))) {
    ++value_pos;
  }

  if (json.compare(value_pos, 4, "null") == 0) {
    return std::nullopt;
  }

  const char* start = json.c_str() + value_pos;
  char* end = nullptr;
  double value = std::strtod(start, &end);

  if (end == start) {
    return std::nullopt;
  }

  return value;
}

static std::vector<Job> read_manifest(const std::string& manifest_path) {
  std::ifstream in(manifest_path);
  if (!in) {
    throw std::runtime_error("Cannot open manifest");
  }

  std::string header;
  if (!std::getline(in, header)) {
    throw std::runtime_error("Manifest is empty");
  }

  const std::string expected_header =
      "target_id,input_csv,output_csv,ops_config_path";

  if (trim(header) != expected_header) {
    throw std::runtime_error(
        "Manifest header must be: " + expected_header);
  }

  std::vector<Job> jobs;
  std::string line;
  size_t line_no = 1;

  while (std::getline(in, line)) {
    ++line_no;

    if (trim(line).empty()) {
      continue;
    }

    auto cols = split_simple_csv_line(line);

    if (cols.size() != 4) {
      throw std::runtime_error(
          "Manifest row must have 4 columns: "
          "target_id,input_csv,output_csv,ops_config_path");
    }

    Job j;
    j.target_id = cols[0];
    j.input_csv = cols[1];
    j.output_csv = cols[2];
    j.ops_config_path = cols[3];

    if (j.input_csv.empty()) {
      throw std::runtime_error("Manifest row has empty input_csv");
    }

    if (j.output_csv.empty()) {
      throw std::runtime_error("Manifest row has empty output_csv");
    }

    jobs.push_back(j);
  }

  return jobs;
}

static void copy_file(const std::string& input_csv, const std::string& output_csv) {
  std::ifstream in(input_csv, std::ios::binary);
  if (!in) {
    throw std::runtime_error("Cannot open input CSV: " + input_csv);
  }

  std::ofstream out(output_csv, std::ios::binary);
  if (!out) {
    throw std::runtime_error("Cannot open output CSV: " + output_csv);
  }

  out << in.rdbuf();
}

static int find_column_index(
    const std::vector<std::string>& header_cols,
    const std::string& name) {
  for (size_t i = 0; i < header_cols.size(); ++i) {
    if (header_cols[i] == name) {
      return static_cast<int>(i);
    }
  }

  return -1;
}

static double parse_double_or_throw(
    const std::string& value,
    const std::string& scalar_name,
    size_t line_no) {
  try {
    size_t idx = 0;
    double parsed = std::stod(value, &idx);

    if (idx != value.size()) {
      throw std::invalid_argument("trailing characters");
    }

    return parsed;
  } catch (const std::exception&) {
    throw std::runtime_error(
        "Could not parse scalar '" + scalar_name +
        "' as number on input CSV line " + std::to_string(line_no));
  }
}

static void apply_scalar_range_filter(
    const Job& j,
    const std::string& ops_json) {
  const std::string scalar =
      parse_string_field(ops_json, "scalar", "rssi_norm");

  const auto min_v = parse_nullable_number(ops_json, "min_value");
  const auto max_v = parse_nullable_number(ops_json, "max_value");

  std::ifstream in(j.input_csv);
  if (!in) {
    throw std::runtime_error("Cannot open input CSV: " + j.input_csv);
  }

  std::ofstream out(j.output_csv);
  if (!out) {
    throw std::runtime_error("Cannot open output CSV: " + j.output_csv);
  }

  std::string header;
  if (!std::getline(in, header)) {
    throw std::runtime_error("Input CSV is empty: " + j.input_csv);
  }

  auto header_cols = split_simple_csv_line(header);
  const int scalar_col = find_column_index(header_cols, scalar);

  if (scalar_col < 0) {
    throw std::runtime_error(
        "scalar_range_filter requested scalar column '" + scalar +
        "', but that column was not found in input CSV");
  }

  out << header << "\n";

  std::string line;
  size_t line_no = 1;

  while (std::getline(in, line)) {
    ++line_no;

    if (trim(line).empty()) {
      continue;
    }

    auto cols = split_simple_csv_line(line);

    if (static_cast<size_t>(scalar_col) >= cols.size()) {
      throw std::runtime_error(
          "Input CSV line " + std::to_string(line_no) +
          " does not contain scalar column '" + scalar + "'");
    }

    const double value =
        parse_double_or_throw(cols[static_cast<size_t>(scalar_col)], scalar, line_no);

    if (min_v.has_value() && value < min_v.value()) {
      continue;
    }

    if (max_v.has_value() && value > max_v.value()) {
      continue;
    }

    out << line << "\n";
  }
}

static void process_job(const Job& j) {
  const std::string ops_json = read_text_file_or_empty(j.ops_config_path);

  const bool do_scalar_range =
      !ops_json.empty() &&
      ops_json.find("scalar_range_filter") != std::string::npos &&
      json_has_enabled_true(ops_json);

  if (do_scalar_range) {
    apply_scalar_range_filter(j, ops_json);
    return;
  }

  copy_file(j.input_csv, j.output_csv);
}

int main(int argc, char** argv) {
  try {
    if (argc != 2) {
      print_usage();
      return 0;
    }

    const std::string arg = argv[1];

    if (arg == "--help" || arg == "-h") {
      print_usage();
      return 0;
    }

    const auto jobs = read_manifest(arg);

    for (const auto& j : jobs) {
      process_job(j);
    }

    return 0;
  } catch (const std::exception& e) {
    std::cerr << "[pcl_ops][ERROR] " << e.what() << "\n";
    return 2;
  }
}
