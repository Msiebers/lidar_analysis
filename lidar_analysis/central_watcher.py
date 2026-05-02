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
ACTIVE_BUCKETS = ("local_pending", "local_failed", "auto_published", "auto_failed")
ALL_BUCKETS = ACTIVE_BUCKETS + ("cache",)


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


def prune_empty_parents(path: Path, stop_at: Path) -> None:
    path = path.resolve()
    stop_at = stop_at.resolve()
    while path != stop_at:
        try:
            path.rmdir()
        except OSError:
            break
        path = path.parent


def ensure_local_dirs() -> None:
    LOCAL_ROOT.mkdir(parents=True, exist_ok=True)

def bucket_root(bucket: str) -> Path:
    return LOCAL_ROOT / bucket

def bucket_date_root(bucket: str, experiment: str, date_name: str) -> Path:
    return bucket_root(bucket) / experiment / date_name

def source_dir(date_root: Path) -> Path:
    return date_root / "source"

def pointclouds_dir(date_root: Path) -> Path:
    return date_root / "pointclouds"

def results_csv_path(date_root: Path) -> Path:
    return date_root / "results.csv"

def metadata_dir(date_root: Path) -> Path:
    return date_root / "scan_metadata"

def process_log_path(date_root: Path) -> Path:
    return metadata_dir(date_root) / "process.log"

def config_snapshot_path(date_root: Path) -> Path:
    return metadata_dir(date_root) / "experiment_config.snapshot.yaml"

def state_path(date_root: Path) -> Path:
    return metadata_dir(date_root) / "state.yaml"

def experiment_config_path(experiment: str) -> Path:
    return EXPERIMENTS_ROOT / experiment / "experiment_config.yaml"

def remote_pointclouds_dir(experiment: str, date_name: str) -> Path:
    return EXPERIMENTS_ROOT / experiment / "pointclouds" / date_name

def remote_results_dir(experiment: str, date_name: str) -> Path:
    return EXPERIMENTS_ROOT / experiment / "results" / date_name

def remote_metadata_dir(experiment: str, date_name: str) -> Path:
    return EXPERIMENTS_ROOT / experiment / "scan_metadata" / date_name

def list_raw_experiments() -> list[str]:
    if not RAW_ROOT.exists():
        return []
    return sorted([p.name for p in RAW_ROOT.iterdir() if p.is_dir()])

def list_raw_dates(experiment: str) -> list[str]:
    exp_root = RAW_ROOT / experiment
    if not exp_root.exists():
        return []
    return sorted([p.name for p in exp_root.iterdir() if p.is_dir()])

def default_state(experiment: str, date_name: str, mode: str, bucket: str) -> dict:
    return {
        "experiment_name": experiment,
        "date": date_name,
        "processing_mode": mode,
        "bucket": bucket,
        "published": False,
        "last_attempt_at": None,
        "last_attempt_status": None,
        "last_error": None,
        "last_published_at": None,
        "last_polled_at": None,
    }

def load_state(date_root: Path) -> dict:
    return load_yaml(state_path(date_root))

def save_state(date_root: Path, state: dict) -> None:
    save_yaml(state_path(date_root), state)

def initialize_state(date_root: Path, experiment: str, date_name: str, mode: str, bucket: str) -> dict:
    state = default_state(experiment, date_name, mode, bucket)
    state["published"] = remote_output_complete(experiment, date_name)
    state["last_polled_at"] = now_utc_iso()
    save_state(date_root, state)
    return state

def update_state(
    date_root: Path,
    *,
    bucket: str,
    attempt_status: str | None = None,
    error: str | None = None,
    published: bool | None = None,
) -> dict:
    state = load_state(date_root)
    if not state:
        state = {}
    state["bucket"] = bucket
    state["last_polled_at"] = now_utc_iso()
    if attempt_status is not None:
        state["last_attempt_status"] = attempt_status
        state["last_attempt_at"] = now_utc_iso()
    if error is not None:
        state["last_error"] = error
    elif attempt_status == "success":
        state["last_error"] = None
    if published is not None:
        state["published"] = published
        if published:
            state["last_published_at"] = now_utc_iso()
    save_state(date_root, state)
    return state

def resolve_processing_mode(cfg: dict) -> str:
    mode = str(cfg.get("processing_mode", "off")).strip().lower()
    if mode not in VALID_PROCESSING_MODES:
        raise ValueError(
            f"Invalid processing_mode={mode!r}. "
            f"Use one of: off, local, auto_publish"
        )
    return mode


def experiment_mode(experiment: str) -> tuple[str, dict]:
    cfg = load_yaml(experiment_config_path(experiment))
    return resolve_processing_mode(cfg), cfg


def remote_output_complete(experiment: str, date_name: str) -> bool:
    results_csv = remote_results_dir(experiment, date_name) / "results.csv"
    pointcloud_dir = remote_pointclouds_dir(experiment, date_name)
    has_results = results_csv.exists()
    has_pointclouds = pointcloud_dir.exists() and any(p.is_file() for p in pointcloud_dir.rglob("*"))
    return has_results and has_pointclouds


def local_output_complete(date_root: Path) -> bool:
    has_results = results_csv_path(date_root).exists()
    local_pointclouds = pointclouds_dir(date_root)
    has_pointclouds = local_pointclouds.exists() and any(p.is_file() for p in local_pointclouds.rglob("*"))
    return has_results and has_pointclouds


def find_existing_bucket(experiment: str, date_name: str, include_cache: bool = True) -> str | None:
    buckets = ALL_BUCKETS if include_cache else ACTIVE_BUCKETS
    for bucket in buckets:
        if bucket_date_root(bucket, experiment, date_name).exists():
            return bucket
    return None


def existing_date_root(experiment: str, date_name: str, include_cache: bool = True) -> Path | None:
    bucket = find_existing_bucket(experiment, date_name, include_cache=include_cache)
    if bucket is None:
        return None
    return bucket_date_root(bucket, experiment, date_name)


def sync_dir_contents(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["rsync", "-av", "--delete", f"{src}/", f"{dst}/"], check=True)


def stage_new_date_bundle(experiment: str, date_name: str, target_bucket: str) -> Path:
    raw_date_dir = RAW_ROOT / experiment / date_name
    if not raw_date_dir.exists():
        raise FileNotFoundError(f"Missing raw date directory: {raw_date_dir}")

    date_root = bucket_date_root(target_bucket, experiment, date_name)
    safe_remove_dir(date_root)
    source_dir(date_root).mkdir(parents=True, exist_ok=True)
    metadata_dir(date_root).mkdir(parents=True, exist_ok=True)

    sync_dir_contents(raw_date_dir, source_dir(date_root))

    cfg_src = experiment_config_path(experiment)
    cfg_dst = source_dir(date_root) / "experiment_config.yaml"
    if not cfg_src.exists():
        raise FileNotFoundError(f"Missing experiment config: {cfg_src}")
    shutil.copy2(cfg_src, cfg_dst)

    return date_root


def run_processing(
    experiment: str,
    date_name: str,
    local_input_dir: Path,
    working_dir: Path,
    output_dir: Path,
    log_path: Path,
) -> None:
    working_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    if not PROCESS_SCRIPT.exists():
        raise FileNotFoundError(f"Processing script not found: {PROCESS_SCRIPT}")

    cmd = [
        "python3",
        str(PROCESS_SCRIPT),
        "--experiment",
        experiment,
        "--date",
        date_name,
        "--input",
        str(local_input_dir),
        "--working",
        str(working_dir),
        "--output",
        str(output_dir),
        "--config",
        str(local_input_dir / "experiment_config.yaml"),
    ]

    with open(log_path, "w", encoding="utf-8") as log_file:
        log_file.write(f"$ {' '.join(cmd)}\n")
        log_file.write(f"[WATCHER] input={local_input_dir}\n")
        log_file.write(f"[WATCHER] output={output_dir}\n")
        log_file.flush()
        proc = subprocess.run(cmd, stdout=log_file, stderr=subprocess.STDOUT, text=True)

    if proc.returncode != 0:
        raise RuntimeError(f"failed to process {experiment}/{date_name}")

def write_input_snapshots(date_root: Path) -> None:
    src_experiment_cfg = source_dir(date_root) / "experiment_config.yaml"
    src_cart_cfg = source_dir(date_root) / "cart_config.yaml"

    dst_experiment_cfg = config_snapshot_path(date_root)
    dst_cart_cfg = metadata_dir(date_root) / "cart_config.snapshot.yaml"

    if not src_experiment_cfg.exists():
        raise FileNotFoundError(f"Missing source experiment config: {src_experiment_cfg}")
    if not src_cart_cfg.exists():
        raise FileNotFoundError(f"Missing source cart config: {src_cart_cfg}")

    dst_experiment_cfg.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_experiment_cfg, dst_experiment_cfg)
    shutil.copy2(src_cart_cfg, dst_cart_cfg)

def process_date_root(experiment: str, date_name: str, mode: str, cfg: dict, date_root: Path) -> Path:
    src_dir = source_dir(date_root)
    if not src_dir.exists():
        raise FileNotFoundError(f"Missing source directory: {src_dir}")

    metadata_dir(date_root).mkdir(parents=True, exist_ok=True)

    if pointclouds_dir(date_root).exists():
        safe_remove_dir(pointclouds_dir(date_root))
    if results_csv_path(date_root).exists():
        results_csv_path(date_root).unlink()

    initialize_state(date_root, experiment, date_name, mode, date_root.parent.name)
    write_input_snapshots(date_root)

    run_processing(
        experiment=experiment,
        date_name=date_name,
        local_input_dir=src_dir,
        working_dir=date_root,
        output_dir=date_root,
        log_path=process_log_path(date_root),
    )

    if not local_output_complete(date_root):
        raise RuntimeError(f"Incomplete local output for {experiment}/{date_name}")

    return date_root


def finalize_bucket_move(experiment: str, date_name: str, src_root: Path, target_bucket: str) -> Path:
    target_root = bucket_date_root(target_bucket, experiment, date_name)
    if src_root.resolve() == target_root.resolve():
        return target_root

    safe_remove_dir(target_root)
    target_root.parent.mkdir(parents=True, exist_ok=True)

    for bucket in ALL_BUCKETS:
        other = bucket_date_root(bucket, experiment, date_name)
        if other.exists() and other.resolve() != src_root.resolve():
            safe_remove_dir(other)

    shutil.move(str(src_root), str(target_root))
    return target_root


def process_new_date(experiment: str, date_name: str, mode: str, cfg: dict) -> Path:
    if mode == "local":
        success_bucket = "local_pending"
        failure_bucket = "local_failed"
    elif mode == "auto_publish":
        success_bucket = "auto_published"
        failure_bucket = "auto_failed"
    else:
        raise RuntimeError(f"process_new_date called with unsupported mode={mode!r}")

    date_root = stage_new_date_bundle(experiment, date_name, success_bucket)

    try:
        process_date_root(experiment, date_name, mode, cfg, date_root)

        if mode == "auto_publish":
            publish_from_date_root(experiment, date_name, date_root)
            rebuild_all_results_csv(experiment)
            update_state(date_root, bucket="auto_published", attempt_status="success", published=True)
            append_log(WATCHER_LOG, f"AUTO_PUBLISH_SUCCESS experiment={experiment} date={date_name}")
        else:
            update_state(date_root, bucket="local_pending", attempt_status="success", published=False)
            append_log(WATCHER_LOG, f"LOCAL_SUCCESS experiment={experiment} date={date_name}")

        return date_root

    except Exception as exc:
        failed_root = finalize_bucket_move(experiment, date_name, date_root, failure_bucket)
        update_state(failed_root, bucket=failure_bucket, attempt_status="failed", error=str(exc), published=False)
        append_log(WATCHER_LOG, f"PROCESS_FAILED experiment={experiment} date={date_name} -> {failure_bucket} error={exc}")
        raise


def publish_from_date_root(experiment: str, date_name: str, date_root: Path) -> None:
    cfg = load_yaml(experiment_config_path(experiment))
    overwrite_pointclouds = bool(cfg.get("analysis", {}).get("overwrite_pointclouds", True))

    if not local_output_complete(date_root):
        raise FileNotFoundError(f"Local processed output is incomplete for {experiment}/{date_name}")

    remote_pc = remote_pointclouds_dir(experiment, date_name)
    remote_results = remote_results_dir(experiment, date_name)
    remote_metadata = remote_metadata_dir(experiment, date_name)
    remote_pc.mkdir(parents=True, exist_ok=True)
    remote_results.mkdir(parents=True, exist_ok=True)
    remote_metadata.mkdir(parents=True, exist_ok=True)

    remote_has_pointclouds = remote_pc.exists() and any(p.is_file() for p in remote_pc.rglob("*"))
    if remote_has_pointclouds and not overwrite_pointclouds:
        raise FileExistsError(
            f"Remote pointclouds already exist for {experiment}/{date_name} and overwrite_pointclouds is false"
        )

    sync_dir_contents(pointclouds_dir(date_root), remote_pc)
    shutil.copy2(results_csv_path(date_root), remote_results / "results.csv")
    sync_dir_contents(metadata_dir(date_root), remote_metadata)

    head_results_csv = EXPERIMENTS_ROOT / experiment / "results.csv"
    rebuild_all_results_csv(experiment, head_results_csv)

    if not remote_output_complete(experiment, date_name):
        raise RuntimeError(f"Remote output verification failed for {experiment}/{date_name}")


def rebuild_all_results_csv(experiment: str, output_csv: Path | None = None) -> None:
    import csv

    exp_dir = EXPERIMENTS_ROOT / experiment
    results_root = exp_dir / "results"
    all_results_path = output_csv if output_csv is not None else exp_dir / "results.csv"

    date_result_files = sorted(results_root.glob("*/results.csv"))
    if not date_result_files:
        if all_results_path.exists():
            all_results_path.unlink()
        return

    rows: list[dict] = []
    fieldnames: list[str] | None = None
    for fp in date_result_files:
        with open(fp, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                continue
            if fieldnames is None:
                fieldnames = list(reader.fieldnames)
            rows.extend(reader)

    if not fieldnames:
        if all_results_path.exists():
            all_results_path.unlink()
        return

    with open(all_results_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def publish_date(experiment: str, date_name: str) -> None:
    current_bucket = find_existing_bucket(experiment, date_name, include_cache=False)
    if current_bucket != "local_pending":
        raise RuntimeError(
            f"Publish is only supported from local_pending; found {current_bucket!r} for {experiment}/{date_name}"
        )

    date_root = bucket_date_root("local_pending", experiment, date_name)
    publish_from_date_root(experiment, date_name, date_root)
    update_state(date_root, bucket="local_pending", published=True)
    append_log(WATCHER_LOG, f"MANUAL_PUBLISH_SUCCESS experiment={experiment} date={date_name} remains=local_pending")


def cache_ready_dates() -> None:
    for bucket in ("local_pending", "auto_published"):
        bucket_root_path = bucket_root(bucket)
        if not bucket_root_path.exists():
            continue

        for experiment_dir in sorted([p for p in bucket_root_path.iterdir() if p.is_dir()]):
            experiment = experiment_dir.name
            for date_dir in sorted([p for p in experiment_dir.iterdir() if p.is_dir()]):
                date_name = date_dir.name
                if not remote_output_complete(experiment, date_name):
                    continue

                cache_dest = bucket_date_root("cache", experiment, date_name)
                safe_remove_dir(cache_dest)
                cache_dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(date_dir), str(cache_dest))
                update_state(cache_dest, bucket="cache", published=True)
                append_log(WATCHER_LOG, f"CACHED experiment={experiment} date={date_name} from={bucket} -> cache")

            if experiment_dir.exists() and not any(experiment_dir.iterdir()):
                experiment_dir.rmdir()


def clear_date(experiment: str, dates: list[str]) -> None:
    for date_name in dates:
        for bucket in ALL_BUCKETS:
            date_root = bucket_date_root(bucket, experiment, date_name)
            safe_remove_dir(date_root)
            prune_empty_parents(date_root.parent, LOCAL_ROOT)

        append_log(WATCHER_LOG, f"CLEARED_LOCAL experiment={experiment} date={date_name}")


def rerun_date(experiment: str, date_name: str) -> None:
    current_bucket = find_existing_bucket(experiment, date_name, include_cache=False)
    if current_bucket is None:
        raise FileNotFoundError(f"No active local date found for {experiment}/{date_name}")
    if current_bucket == "auto_published":
        raise RuntimeError(f"Refusing to rerun auto_published date {experiment}/{date_name} automatically")

    mode, cfg = experiment_mode(experiment)
    date_root = bucket_date_root(current_bucket, experiment, date_name)

    success_bucket = "local_pending"
    failure_bucket = "local_failed"

    try:
        process_date_root(experiment, date_name, mode, cfg, date_root)

        if current_bucket != success_bucket:
            date_root = finalize_bucket_move(experiment, date_name, date_root, success_bucket)

        update_state(date_root, bucket=success_bucket, attempt_status="success", published=False)
        append_log(WATCHER_LOG, f"RERUN_SUCCESS experiment={experiment} date={date_name} -> {success_bucket}")

    except Exception as exc:
        if current_bucket != failure_bucket:
            date_root = finalize_bucket_move(experiment, date_name, date_root, failure_bucket)

        update_state(date_root, bucket=failure_bucket, attempt_status="failed", error=str(exc), published=False)
        append_log(WATCHER_LOG, f"RERUN_FAILED experiment={experiment} date={date_name} -> {failure_bucket} error={exc}")
        raise


def resolve_experiment_arg(args: argparse.Namespace) -> str:
    experiment = getattr(args, "experiment", None) or getattr(args, "experiment_flag", None)
    if not experiment:
        raise SystemExit("Missing required experiment. Use the positional value or --experiment.")
    return experiment


def resolve_date_arg(args: argparse.Namespace) -> str:
    date_name = getattr(args, "date", None) or getattr(args, "date_flag", None)
    if not date_name:
        raise SystemExit("Missing required date. Use the positional value or --date.")
    return date_name


def poll_once() -> None:
    append_log(WATCHER_LOG, "Polling cycle start")
    for experiment in list_raw_experiments():
        ensure_experiment_scaffold(experiment)
        mode, cfg = experiment_mode(experiment)

        if mode == "off":
            append_log(WATCHER_LOG, f"SKIP experiment={experiment} processing_mode=off")
            continue

        for date_name in list_raw_dates(experiment):
            if remote_output_complete(experiment, date_name):
                append_log(WATCHER_LOG, f"SKIP_PUBLISHED experiment={experiment} date={date_name}")
                continue

            existing_bucket = find_existing_bucket(experiment, date_name, include_cache=True)
            if existing_bucket is not None:
                append_log(WATCHER_LOG, f"SKIP_EXISTING experiment={experiment} date={date_name} bucket={existing_bucket}")
                continue

            try:
                append_log(WATCHER_LOG, f"START experiment={experiment} date={date_name} mode={mode}")
                process_new_date(experiment, date_name, mode, cfg)
            except Exception as exc:
                append_log(WATCHER_LOG, f"POLL_DATE_FAILED experiment={experiment} date={date_name} error={exc}")

    cache_ready_dates()
    append_log(WATCHER_LOG, "Polling cycle end")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")

    poll_parser = subparsers.add_parser("poll", help="Run one polling cycle")
    poll_parser.add_argument("--once", action="store_true", help="Accepted for compatibility.")

    clear_parser = subparsers.add_parser("clear-date", help="Remove one or more local experiment/date folders from all buckets")
    clear_parser.add_argument("experiment")
    clear_parser.add_argument("dates", nargs="+")

    rerun_parser = subparsers.add_parser("rerun", help="Reprocess a date already in a workflow bucket")
    rerun_parser.add_argument("experiment", nargs="?")
    rerun_parser.add_argument("date", nargs="?")
    rerun_parser.add_argument("--experiment", dest="experiment_flag")
    rerun_parser.add_argument("--date", dest="date_flag")

    publish_parser = subparsers.add_parser("publish", help="Publish one local_pending date to CartCity")
    publish_parser.add_argument("experiment", nargs="?")
    publish_parser.add_argument("date", nargs="?")
    publish_parser.add_argument("--experiment", dest="experiment_flag")
    publish_parser.add_argument("--date", dest="date_flag")

    cache_parser = subparsers.add_parser("cache", help="Move published successful dates into cache")
    cache_parser.add_argument("--once", action="store_true", help="Accepted for compatibility.")

    parser.add_argument("--once", action="store_true", help="Accepted for compatibility; runs one poll cycle.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_local_dirs()

    if args.command in (None, "poll"):
        poll_once()
        return
    if args.command == "clear-date":
        clear_date(args.experiment, args.dates)
        return
    if args.command == "rerun":
        rerun_date(resolve_experiment_arg(args), resolve_date_arg(args))
        return
    if args.command == "publish":
        publish_date(resolve_experiment_arg(args), resolve_date_arg(args))
        return
    if args.command == "cache":
        cache_ready_dates()
        return
    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        append_log(WATCHER_LOG, f"TOP_LEVEL_ERROR {exc}")
        raise