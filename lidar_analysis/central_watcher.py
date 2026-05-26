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
except Exception:
    from yaml_loader import yaml


# ---------------------------------------------------------------------
# Simple central watcher paths
# ---------------------------------------------------------------------
# CartCity is mounted locally.
#
# Raw data:
#   /mnt/cartcity/cart_data/raw_data/<experiment>/<date>/
#
# Default config templates:
#   /mnt/cartcity/cart_data/config_templates/
#
# Local mirror:
#   /media/central/raw_mirror/<experiment>/<date>/source/
#   /media/central/raw_mirror/<experiment>/<date>/pointclouds/
#   /media/central/raw_mirror/<experiment>/<date>/scan_metadata/
#   /media/central/raw_mirror/<experiment>/<date>/results.csv

CARTCITY_ROOT = Path("/mnt/cartcity")
RAW_ROOT = CARTCITY_ROOT / "raw_data"
CONFIG_TEMPLATES_ROOT = CARTCITY_ROOT / "config_templates"

LOCAL_ROOT = Path("/media/central/raw_mirror")
WATCHER_LOG = LOCAL_ROOT / "watcher.log"

SCRIPT_ROOT = Path(__file__).resolve().parent
PROCESS_SCRIPT = SCRIPT_ROOT / "run_experiment_date.py"

DEFAULT_CONFIG_CANDIDATES = (
    "experiment_config.yaml",
    "default_experiment_config.yaml",
    "experiment_config.template.yaml",
)


# ---------------------------------------------------------------------
# Basic helpers
# ---------------------------------------------------------------------
def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def append_log(log_path: Path, line: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"{now_str()} - {line}\n")


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


def ensure_local_root() -> None:
    LOCAL_ROOT.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------
# Local mirror layout
# ---------------------------------------------------------------------
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


def state_path(root: Path) -> Path:
    return metadata_dir(root) / "state.yaml"


def process_log_path(root: Path) -> Path:
    return metadata_dir(root) / "process.log"


def config_snapshot_path(root: Path) -> Path:
    return metadata_dir(root) / "experiment_config.snapshot.yaml"


def cart_config_snapshot_path(root: Path) -> Path:
    return metadata_dir(root) / "cart_config.snapshot.yaml"


# ---------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------
def list_raw_experiments() -> list[str]:
    if not RAW_ROOT.exists():
        append_log(WATCHER_LOG, f"RAW_ROOT_MISSING path={RAW_ROOT}")
        return []
    return sorted(p.name for p in RAW_ROOT.iterdir() if p.is_dir())


def list_raw_dates(experiment: str) -> list[str]:
    exp_root = RAW_ROOT / experiment
    if not exp_root.exists():
        return []
    return sorted(p.name for p in exp_root.iterdir() if p.is_dir())


# ---------------------------------------------------------------------
# Config stamping
# ---------------------------------------------------------------------
def find_default_experiment_config() -> Path:
    """
    Find a default experiment config template.

    Preferred:
      /mnt/cartcity/cart_data/config_templates/experiment_config.yaml

    Fallback:
      first *.yaml in /mnt/cartcity/cart_data/config_templates
    """
    for name in DEFAULT_CONFIG_CANDIDATES:
        p = CONFIG_TEMPLATES_ROOT / name
        if p.exists():
            return p

    yaml_files = sorted(CONFIG_TEMPLATES_ROOT.glob("*.yaml"))
    if yaml_files:
        return yaml_files[0]

    raise FileNotFoundError(
        "No default experiment config template found. Expected one of "
        f"{DEFAULT_CONFIG_CANDIDATES} or any *.yaml under {CONFIG_TEMPLATES_ROOT}"
    )


def stamp_default_config(root: Path, *, overwrite: bool = False) -> Path:
    """
    Put experiment_config.yaml into source/.

    By default, this does not overwrite an existing local config.
    That protects tuned configs from being replaced every poll.
    """
    dst = source_dir(root) / "experiment_config.yaml"

    if dst.exists() and not overwrite:
        append_log(WATCHER_LOG, f"CONFIG_EXISTS keep={dst}")
        return dst

    src = find_default_experiment_config()
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    append_log(WATCHER_LOG, f"STAMP_CONFIG src={src} dst={dst}")
    return dst


# ---------------------------------------------------------------------
# State file
# ---------------------------------------------------------------------
def default_state(experiment: str, date_name: str) -> dict:
    root = date_root(experiment, date_name)
    return {
        "experiment_name": experiment,
        "date": date_name,
        "local_root": str(root),
        "source_dir": str(source_dir(root)),
        "status": "unknown",
        "last_polled_at": None,
        "last_rerun_at": None,
        "last_rerun_status": None,
        "last_error": None,
    }


def update_state(
    root: Path,
    experiment: str,
    date_name: str,
    *,
    status: str | None = None,
    rerun_status: str | None = None,
    error: str | None = None,
) -> dict:
    state = load_yaml(state_path(root))
    if not state:
        state = default_state(experiment, date_name)

    state["experiment_name"] = experiment
    state["date"] = date_name
    state["local_root"] = str(root)
    state["source_dir"] = str(source_dir(root))

    if status is not None:
        state["status"] = status

    state["last_polled_at"] = now_utc_iso()

    if rerun_status is not None:
        state["last_rerun_status"] = rerun_status
        state["last_rerun_at"] = now_utc_iso()

    if error is not None:
        state["last_error"] = error
    elif rerun_status == "success":
        state["last_error"] = None

    save_yaml(state_path(root), state)
    return state


# ---------------------------------------------------------------------
# Sync-only poll
# ---------------------------------------------------------------------
def sync_dir_contents(src: Path, dst: Path) -> None:
    """
    Sync raw mounted CartCity date contents into local source/.

    This intentionally excludes experiment_config.yaml from rsync delete behavior,
    because source/experiment_config.yaml is the local working config stamped from
    config_templates and may later be edited locally.

    Poll only touches source/.
    Poll does not delete pointclouds/, results.csv, or scan_metadata/.
    """
    dst.mkdir(parents=True, exist_ok=True)

    cmd = [
        "rsync",
        "-a",
        "--delete",
        "--exclude",
        "experiment_config.yaml",
        "--info=stats2",
        f"{src}/",
        f"{dst}/",
    ]

    append_log(WATCHER_LOG, f"RSYNC_START src={src} dst={dst}")
    subprocess.run(cmd, check=True)
    append_log(WATCHER_LOG, f"RSYNC_DONE src={src} dst={dst}")


def sync_date_only(experiment: str, date_name: str, *, overwrite_config: bool = False) -> Path:
    """
    Sync one experiment/date.

    Does not process.
    Does not classify as pending/failed.
    Does not touch old local_pending/local_failed trees.
    """
    raw_date_dir = RAW_ROOT / experiment / date_name
    if not raw_date_dir.exists():
        raise FileNotFoundError(f"Missing raw date directory: {raw_date_dir}")

    root = date_root(experiment, date_name)
    metadata_dir(root).mkdir(parents=True, exist_ok=True)
    source_dir(root).mkdir(parents=True, exist_ok=True)

    sync_dir_contents(raw_date_dir, source_dir(root))
    stamp_default_config(root, overwrite=overwrite_config)

    update_state(root, experiment, date_name, status="synced")
    append_log(WATCHER_LOG, f"SYNCED experiment={experiment} date={date_name} root={root} source={source_dir(root)}")
    return root


def poll_once(
    *,
    experiment_filter: str | None = None,
    date_filter: str | None = None,
    overwrite_config: bool = False,
) -> None:
    """
    Sync-only polling.

    This does not analyze data.

    To process after polling:
      python3 lidar_analysis/central_watcher.py rerun <experiment> <date>
    """
    append_log(
        WATCHER_LOG,
        f"Polling cycle start raw_root={RAW_ROOT} local_root={LOCAL_ROOT} "
        f"experiment_filter={experiment_filter} date_filter={date_filter}",
    )

    if experiment_filter:
        experiments = [experiment_filter]
    else:
        experiments = list_raw_experiments()

    if not experiments:
        print(f"[POLL] No experiments found at {RAW_ROOT}")
        append_log(WATCHER_LOG, f"NO_EXPERIMENTS raw_root={RAW_ROOT}")
        return

    total_dates = 0
    failed = 0

    for experiment in experiments:
        dates = [date_filter] if date_filter else list_raw_dates(experiment)

        if not dates:
            append_log(WATCHER_LOG, f"NO_DATES experiment={experiment}")
            continue

        for date_name in dates:
            total_dates += 1
            try:
                root = sync_date_only(
                    experiment,
                    date_name,
                    overwrite_config=overwrite_config,
                )
                print(f"[POLL] synced {experiment}/{date_name} -> {source_dir(root)}")
            except Exception as exc:
                failed += 1
                append_log(WATCHER_LOG, f"SYNC_FAILED experiment={experiment} date={date_name} error={exc}")
                print(f"[POLL][ERROR] {experiment}/{date_name}: {exc}")

    append_log(WATCHER_LOG, f"Polling cycle end dates={total_dates} failed={failed}")
    print(f"[POLL] done. dates={total_dates} failed={failed}")


# ---------------------------------------------------------------------
# Rerun processing
# ---------------------------------------------------------------------
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

    config_path = local_input_dir / "experiment_config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"Missing source experiment config: {config_path}")

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
        str(config_path),
    ]

    with open(log_path, "w", encoding="utf-8") as log_file:
        log_file.write(f"$ {' '.join(cmd)}\n")
        log_file.write(f"[WATCHER] input={local_input_dir}\n")
        log_file.write(f"[WATCHER] working={working_dir}\n")
        log_file.write(f"[WATCHER] output={output_dir}\n")
        log_file.flush()
        proc = subprocess.run(cmd, stdout=log_file, stderr=subprocess.STDOUT, text=True)

    if proc.returncode != 0:
        raise RuntimeError(f"failed to process {experiment}/{date_name}; see {log_path}")


def write_input_snapshots(root: Path) -> None:
    metadata_dir(root).mkdir(parents=True, exist_ok=True)

    src_experiment_cfg = source_dir(root) / "experiment_config.yaml"
    src_cart_cfg = source_dir(root) / "cart_config.yaml"

    if src_experiment_cfg.exists():
        shutil.copy2(src_experiment_cfg, config_snapshot_path(root))

    if src_cart_cfg.exists():
        shutil.copy2(src_cart_cfg, cart_config_snapshot_path(root))


def local_output_complete(root: Path) -> bool:
    has_results = results_csv_path(root).exists()
    local_pointclouds = pointclouds_dir(root)
    has_pointclouds = local_pointclouds.exists() and any(p.is_file() for p in local_pointclouds.rglob("*"))
    return has_results and has_pointclouds


def clean_processing_outputs(root: Path) -> None:
    """
    Rerun rebuilds outputs.

    Poll never calls this.
    """
    if pointclouds_dir(root).exists():
        shutil.rmtree(pointclouds_dir(root), ignore_errors=True)

    if results_csv_path(root).exists():
        results_csv_path(root).unlink()


def process_date_root(experiment: str, date_name: str, root: Path) -> Path:
    src_dir = source_dir(root)
    if not src_dir.exists():
        raise FileNotFoundError(f"Missing source directory: {src_dir}")

    config_path = src_dir / "experiment_config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(
            f"Missing {config_path}. Run poll first so the default config template is stamped."
        )

    clean_processing_outputs(root)
    write_input_snapshots(root)

    run_processing(experiment, date_name, src_dir, root, root, process_log_path(root))

    if not local_output_complete(root):
        raise RuntimeError(f"Incomplete local output for {experiment}/{date_name}")

    return root


def rerun_date(experiment: str, date_name: str) -> None:
    root = date_root(experiment, date_name)

    if not source_dir(root).exists():
        raise FileNotFoundError(
            f"No local mirrored source found for {experiment}/{date_name} at {source_dir(root)}. "
            "Run poll first, or use run_experiment_date.py with explicit paths."
        )

    try:
        append_log(WATCHER_LOG, f"RERUN_START experiment={experiment} date={date_name} root={root}")
        process_date_root(experiment, date_name, root)
        update_state(root, experiment, date_name, status="processed", rerun_status="success")
        append_log(WATCHER_LOG, f"RERUN_SUCCESS experiment={experiment} date={date_name} root={root}")
        print(f"[RERUN] success {experiment}/{date_name} -> {root}")
    except Exception as exc:
        update_state(root, experiment, date_name, status="rerun_failed", rerun_status="failed", error=str(exc))
        append_log(WATCHER_LOG, f"RERUN_FAILED experiment={experiment} date={date_name} root={root} error={exc}")
        print(f"[RERUN][ERROR] {experiment}/{date_name}: {exc}")
        raise


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync CartCity raw data to local raw_mirror, and rerun selected dates."
    )
    subparsers = parser.add_subparsers(dest="command")

    poll_parser = subparsers.add_parser("poll", help="Sync mounted CartCity raw data to local raw_mirror")
    poll_parser.add_argument("--once", action="store_true", help="Accepted for compatibility; poll is always one cycle.")
    poll_parser.add_argument("--experiment", help="Only sync one experiment")
    poll_parser.add_argument("--date", help="Only sync one date")
    poll_parser.add_argument(
        "--overwrite-config",
        action="store_true",
        help="Overwrite source/experiment_config.yaml from config_templates. Default preserves existing config.",
    )

    rerun_parser = subparsers.add_parser("rerun", help="Reprocess a mirrored date")
    rerun_parser.add_argument("experiment")
    rerun_parser.add_argument("date")

    parser.add_argument("--once", action="store_true", help="Accepted for compatibility; runs one poll cycle.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_local_root()

    if args.command in (None, "poll"):
        poll_once(
            experiment_filter=getattr(args, "experiment", None),
            date_filter=getattr(args, "date", None),
            overwrite_config=bool(getattr(args, "overwrite_config", False)),
        )
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