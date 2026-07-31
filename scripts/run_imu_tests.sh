#!/usr/bin/env bash
set -u

usage() {
  cat <<'EOF'
Usage:
  scripts/run_imu_tests.sh /PATH/TO/FIELD_INPUT /PATH/TO/IMU_OUTPUT_ROOT EXPERIMENT_NAME YYYY_MM_DD

Arguments:
  /PATH/TO/FIELD_INPUT       Folder containing *_lidar.csv, *_pico.csv, cart_config.yaml, and experiment/marker files.
  /PATH/TO/IMU_OUTPUT_ROOT   Folder outside this repo where outputs, logs, summaries, and working files will be written.
  EXPERIMENT_NAME            Experiment label to write into results.csv.
  YYYY_MM_DD                 Date label to write into results.csv.

Example:
  scripts/run_imu_tests.sh /PATH/TO/FIELD_INPUT /PATH/TO/IMU_OUTPUT_ROOT MeadowFescue_YYYY YYYY_MM_DD
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -ne 4 ]]; then
  usage >&2
  exit 2
fi

INPUT_DIR="$1"
OUTPUT_ROOT="$2"
EXPERIMENT_NAME="$3"
DATE_NAME="$4"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_DIR="${REPO_ROOT}/runs/imu_tests/configs"

if [[ ! -d "${INPUT_DIR}" ]]; then
  echo "ERROR: input folder does not exist: ${INPUT_DIR}" >&2
  exit 1
fi

if [[ ! -f "${INPUT_DIR}/cart_config.yaml" ]]; then
  echo "ERROR: missing required cart_config.yaml in input folder: ${INPUT_DIR}/cart_config.yaml" >&2
  exit 1
fi

if ! compgen -G "${INPUT_DIR}/*_lidar.csv" >/dev/null; then
  echo "ERROR: no *_lidar.csv files found in input folder: ${INPUT_DIR}" >&2
  exit 1
fi

if ! compgen -G "${INPUT_DIR}/*_pico.csv" >/dev/null; then
  echo "ERROR: no *_pico.csv files found in input folder: ${INPUT_DIR}" >&2
  exit 1
fi

mkdir -p "${OUTPUT_ROOT}/outputs" "${OUTPUT_ROOT}/working" "${OUTPUT_ROOT}/logs" "${OUTPUT_ROOT}/screenshots"

RUN_IDS=(
  "001_no_imu_interp"
  "002_imu_roll_pitch_interp"
  "003_imu_roll_pitch_heading_interp"
  "004_imu_roll_pitch_imu_interp"
  "005_imu_roll_pitch_pps"
)

FUSIONS=(
  "interp"
  "interp"
  "interp"
  "imu_interp"
  "pps"
)

FAILED_RUNS=()

cd "${REPO_ROOT}" || exit 1

for i in "${!RUN_IDS[@]}"; do
  RUN_ID="${RUN_IDS[$i]}"
  FUSION="${FUSIONS[$i]}"
  CONFIG_PATH="${CONFIG_DIR}/${RUN_ID}.yaml"
  RUN_OUTPUT="${OUTPUT_ROOT}/outputs/${RUN_ID}"
  RUN_WORKING="${OUTPUT_ROOT}/working/${RUN_ID}"
  RUN_LOG="${OUTPUT_ROOT}/logs/${RUN_ID}.log"

  if [[ ! -f "${CONFIG_PATH}" ]]; then
    echo "ERROR: missing config: ${CONFIG_PATH}" | tee "${RUN_LOG}"
    FAILED_RUNS+=("${RUN_ID}")
    continue
  fi

  echo "============================================================" | tee "${RUN_LOG}"
  echo "Run: ${RUN_ID}" | tee -a "${RUN_LOG}"
  echo "Fusion: ${FUSION}" | tee -a "${RUN_LOG}"
  echo "Output: ${RUN_OUTPUT}" | tee -a "${RUN_LOG}"
  echo "Command:" | tee -a "${RUN_LOG}"
  printf 'python3 -m lidar_analysis.central_runner --experiment %q --date %q --input %q --working %q --output %q --config %q --fusion %q --force\n' \
    "${EXPERIMENT_NAME}" "${DATE_NAME}" "${INPUT_DIR}" "${RUN_WORKING}" "${RUN_OUTPUT}" "${CONFIG_PATH}" "${FUSION}" | tee -a "${RUN_LOG}"

  python3 -m lidar_analysis.central_runner \
    --experiment "${EXPERIMENT_NAME}" \
    --date "${DATE_NAME}" \
    --input "${INPUT_DIR}" \
    --working "${RUN_WORKING}" \
    --output "${RUN_OUTPUT}" \
    --config "${CONFIG_PATH}" \
    --fusion "${FUSION}" \
    --force >> "${RUN_LOG}" 2>&1

  STATUS=$?
  if [[ ${STATUS} -ne 0 ]]; then
    echo "FAILED: ${RUN_ID} exited with status ${STATUS}" | tee -a "${RUN_LOG}"
    FAILED_RUNS+=("${RUN_ID}")
  elif [[ ! -f "${RUN_OUTPUT}/results.csv" ]]; then
    echo "FAILED: ${RUN_ID} did not produce ${RUN_OUTPUT}/results.csv" | tee -a "${RUN_LOG}"
    FAILED_RUNS+=("${RUN_ID}")
  else
    RESULT_ROWS=$(python3 - "${RUN_OUTPUT}/results.csv" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
with path.open("r", encoding="utf-8", errors="replace") as f:
    n = sum(1 for _ in f)
print(max(0, n - 1))
PY
)
    POINTCLOUD_COUNT=$(find "${RUN_OUTPUT}/pointclouds" -type f -name '*.csv' 2>/dev/null | wc -l | tr -d ' ')
    echo "SUCCESS: ${RUN_ID}" | tee -a "${RUN_LOG}"
    echo "Result rows: ${RESULT_ROWS}" | tee -a "${RUN_LOG}"
    echo "Pointcloud CSV files: ${POINTCLOUD_COUNT}" | tee -a "${RUN_LOG}"
  fi
done

COMPARE_LOG="${OUTPUT_ROOT}/logs/compare_imu_runs.log"
echo "Running comparison script..." | tee "${COMPARE_LOG}"
python3 "${REPO_ROOT}/scripts/compare_imu_runs.py" --run-root "${OUTPUT_ROOT}" >> "${COMPARE_LOG}" 2>&1
COMPARE_STATUS=$?
if [[ ${COMPARE_STATUS} -ne 0 ]]; then
  echo "WARNING: comparison script exited with status ${COMPARE_STATUS}. See ${COMPARE_LOG}" >&2
fi

echo "============================================================"
echo "IMU test output root: ${OUTPUT_ROOT}"
echo "Logs: ${OUTPUT_ROOT}/logs"
echo "Combined results: ${OUTPUT_ROOT}/imu_all_results.csv"
echo "Summary: ${OUTPUT_ROOT}/imu_comparison_summary.csv"

if [[ ${#FAILED_RUNS[@]} -gt 0 ]]; then
  echo "Failed runs: ${FAILED_RUNS[*]}" >&2
  exit 1
fi

echo "All IMU runs completed."
