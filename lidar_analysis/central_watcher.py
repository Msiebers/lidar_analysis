#!/usr/bin/env python3

from __future__ import annotations

import argparse
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    from .yaml_loader import yaml
    from .scaffold_experiments import ensure_experiment_scaffold
except Exception:
    from yaml_loader import yaml
    from scaffold_experiments import ensure_experiment_scaffold

CARTCITY_ROOT = Path("/mnt/cartcity")
RAW_ROOT = CARTCITY_ROOT / "raw_data"
EXPERIMENTS_ROOT = CARTCITY_ROOT / "experiments"

SCRIPT_ROOT = Path(__file__).resolve().parent
LOCAL_ROOT = Path("/media/central/raw_mirror")
WATCHER_LOG = LOCAL_ROOT / "watcher.log"
PROCESS_SCRIPT = SCRIPT_ROOT / "run_experiment_date.py"

VALID_PROCESSING_MODES = {"off", "local", "auto_publish"}


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def save_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False)


def append_log(log_path: Path, line: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"{now_str()} - {line}\n")


def safe_remove_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def ensure_local_dirs() -> None:
    LOCAL_ROOT.mkdir(parents=True, exist_ok=True)


def date_root(experiment: str, date_name: str) -> Path:
    return LOCAL_ROOT / experiment / date_name


def source_dir(root: Path) -> Path:
    return root / "source"


def pointclouds_dir(root: Path) -> Path:
    return root / "pointclouds"


def results_csv_path(root: Path) -> Path:
    return root / "results.csv"


def metadata_dir(root: Path) -> Path:
    return root / "scan_metadata"


def process_log_path(root: Path) -> Path:
    return metadata_dir(root) / "process.log"


def config_snapshot_path(root: Path) -> Path:
    return metadata_dir(root) / "experiment_config.snapshot.yaml"


def state_path(root: Path) -> Path:
    return metadata_dir(root) / "state.yaml"


def experiment_config_path(experiment: str) -> Path:
    return EXPERIMENTS_ROOT / experiment / "experiment_config.yaml"


def list_raw_experiments() -> list[str]:
    if not RAW_ROOT.exists():
        return []
    return sorted([p.name for p in RAW_ROOT.iterdir() if p.is_dir()])


def list_raw_dates(experiment: str) -> list[str]:
    exp_root = RAW_ROOT / experiment
    if not exp_root.exists():
        return []
    return sorted([p.name for p in exp_root.iterdir() if p.is_dir()])


def default_state(experiment: str, date_name: str, mode: str) -> dict:
    return {
        "experiment_name": experiment,
        "date": date_name,
        "processing_mode": mode,
        "bucket": "raw_mirror",
        "published": False,
        "last_attempt_at": None,
        "last_attempt_status": None,
        "last_error": None,
        "last_published_at": None,
        "last_polled_at": None,
    }


def initialize_state(root: Path, experiment: str, date_name: str, mode: str) -> dict:
    state = default_state(experiment, date_name, mode)
    state["last_polled_at"] = now_utc_iso()
    save_yaml(state_path(root), state)
    return state


def update_state(root: Path, *, attempt_status: str | None = None, error: str | None = None) -> dict:
    state = load_yaml(state_path(root))
    if not state:
        state = {}
    state["bucket"] = "raw_mirror"
    state["last_polled_at"] = now_utc_iso()
    if attempt_status is not None:
        state["last_attempt_status"] = attempt_status
        state["last_attempt_at"] = now_utc_iso()
    if error is not None:
        state["last_error"] = error
    elif attempt_status == "success":
        state["last_error"] = None
    save_yaml(state_path(root), state)
    return state


def resolve_processing_mode(cfg: dict) -> str:
    mode = str(cfg.get("processing_mode", "off")).strip().lower()
    if mode not in VALID_PROCESSING_MODES:
        raise ValueError(f"Invalid processing_mode={mode!r}. Use one of: off, local, auto_publish")
    return mode


def experiment_mode(experiment: str) -> tuple[str, dict]:
    cfg = load_yaml(experiment_config_path(experiment))
    return resolve_processing_mode(cfg), cfg


def sync_dir_contents(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["rsync", "-av", "--delete", f"{src}/", f"{dst}/"], check=True)


def stage_new_date_bundle(experiment: str, date_name: str) -> Path:
    raw_date_dir = RAW_ROOT / experiment / date_name
    if not raw_date_dir.exists():
        raise FileNotFoundError(f"Missing raw date directory: {raw_date_dir}")

    root = date_root(experiment, date_name)
    source_dir(root).mkdir(parents=True, exist_ok=True)
    metadata_dir(root).mkdir(parents=True, exist_ok=True)

    sync_dir_contents(raw_date_dir, source_dir(root))

    cfg_src = experiment_config_path(experiment)
    cfg_dst = source_dir(root) / "experiment_config.yaml"
    if not cfg_src.exists():
        raise FileNotFoundError(f"Missing experiment config: {cfg_src}")
    shutil.copy2(cfg_src, cfg_dst)

    return root


def run_processing(experiment: str, date_name: str, local_input_dir: Path, working_dir: Path, output_dir: Path, log_path: Path) -> None:
    working_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    if not PROCESS_SCRIPT.exists():
        raise FileNotFoundError(f"Processing script not found: {PROCESS_SCRIPT}")

    cmd = [
        "python3", str(PROCESS_SCRIPT), "--experiment", experiment, "--date", date_name,
        "--input", str(local_input_dir), "--working", str(working_dir), "--output", str(output_dir),
        "--config", str(local_input_dir / "experiment_config.yaml"),
    ]

    with open(log_path, "w", encoding="utf-8") as log_file:
        log_file.write(f"$ {' '.join(cmd)}\n")
        log_file.write(f"[WATCHER] input={local_input_dir}\n")
        log_file.write(f"[WATCHER] working={working_dir}\n")
        log_file.write(f"[WATCHER] output={output_dir}\n")
        log_file.flush()
        proc = subprocess.run(cmd, stdout=log_file, stderr=subprocess.STDOUT, text=True)

    if proc.returncode != 0:
        raise RuntimeError(f"failed to process {experiment}/{date_name}")


def write_input_snapshots(root: Path) -> None:
    src_experiment_cfg = source_dir(root) / "experiment_config.yaml"
    src_cart_cfg = source_dir(root) / "cart_config.yaml"
    if not src_experiment_cfg.exists():
        raise FileNotFoundError(f"Missing source experiment config: {src_experiment_cfg}")
    if not src_cart_cfg.exists():
        raise FileNotFoundError(f"Missing source cart config: {src_cart_cfg}")
    shutil.copy2(src_experiment_cfg, config_snapshot_path(root))
    shutil.copy2(src_cart_cfg, metadata_dir(root) / "cart_config.snapshot.yaml")


def local_output_complete(root: Path) -> bool:
    has_results = results_csv_path(root).exists()
    local_pointclouds = pointclouds_dir(root)
    has_pointclouds = local_pointclouds.exists() and any(p.is_file() for p in local_pointclouds.rglob("*"))
    return has_results and has_pointclouds


def process_date_root(experiment: str, date_name: str, mode: str, root: Path) -> Path:
    src_dir = source_dir(root)
    if not src_dir.exists():
        raise FileNotFoundError(f"Missing source directory: {src_dir}")

    if pointclouds_dir(root).exists():
        safe_remove_dir(pointclouds_dir(root))
    if results_csv_path(root).exists():
        results_csv_path(root).unlink()

    initialize_state(root, experiment, date_name, mode)
    write_input_snapshots(root)

    run_processing(experiment, date_name, src_dir, root, root, process_log_path(root))

    if not local_output_complete(root):
        raise RuntimeError(f"Incomplete local output for {experiment}/{date_name}")
    return root


def process_new_date(experiment: str, date_name: str, mode: str) -> Path:
    root = stage_new_date_bundle(experiment, date_name)
    try:
        process_date_root(experiment, date_name, mode, root)
        update_state(root, attempt_status="success")
        append_log(WATCHER_LOG, f"LOCAL_SUCCESS experiment={experiment} date={date_name} root={root}")
    except Exception as exc:
        update_state(root, attempt_status="failed", error=str(exc))
        append_log(WATCHER_LOG, f"PROCESS_FAILED experiment={experiment} date={date_name} root={root} error={exc}")
        raise
    return root


def rerun_date(experiment: str, date_name: str) -> None:
    root = date_root(experiment, date_name)
    if not source_dir(root).exists():
        raise FileNotFoundError(f"No local mirrored source found for {experiment}/{date_name} at {source_dir(root)}")
    mode, _cfg = experiment_mode(experiment)
    try:
        process_date_root(experiment, date_name, mode, root)
        update_state(root, attempt_status="success")
        append_log(WATCHER_LOG, f"RERUN_SUCCESS experiment={experiment} date={date_name} root={root}")
    except Exception as exc:
        update_state(root, attempt_status="failed", error=str(exc))
        append_log(WATCHER_LOG, f"RERUN_FAILED experiment={experiment} date={date_name} root={root} error={exc}")
        raise


def poll_once() -> None:
    append_log(WATCHER_LOG, "Polling cycle start")
    for experiment in list_raw_experiments():
        ensure_experiment_scaffold(experiment)
        mode, _cfg = experiment_mode(experiment)
        if mode == "off":
            append_log(WATCHER_LOG, f"SKIP experiment={experiment} processing_mode=off")
            continue

        for date_name in list_raw_dates(experiment):
            root = date_root(experiment, date_name)
            if source_dir(root).exists():
                append_log(WATCHER_LOG, f"SYNC_EXISTING experiment={experiment} date={date_name} source={source_dir(root)}")
            else:
                append_log(WATCHER_LOG, f"SYNC_NEW experiment={experiment} date={date_name} source={source_dir(root)}")
            try:
                process_new_date(experiment, date_name, mode)
            except Exception as exc:
                append_log(WATCHER_LOG, f"POLL_DATE_FAILED experiment={experiment} date={date_name} error={exc}")

    append_log(WATCHER_LOG, "Polling cycle end")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")

    poll_parser = subparsers.add_parser("poll", help="Run one polling cycle")
    poll_parser.add_argument("--once", action="store_true", help="Accepted for compatibility.")

    rerun_parser = subparsers.add_parser("rerun", help="Reprocess a mirrored date")
    rerun_parser.add_argument("experiment")
    rerun_parser.add_argument("date")

    parser.add_argument("--once", action="store_true", help="Accepted for compatibility; runs one poll cycle.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_local_dirs()

    if args.command in (None, "poll"):
        poll_once()
        return
    if args.command == "rerun":
        rerun_date(args.experiment, args.date)
        return
    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        append_log(WATCHER_LOG, f"TOP_LEVEL_ERROR {exc}")
        raise
