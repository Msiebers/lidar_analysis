#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from lidar_analysis.research_delivery import build_delivery, load_delivery_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build an internal, test-only researcher-delivery preview from existing "
            "canonical LiDAR results. Inputs are never modified."
        )
    )
    parser.add_argument("--config", required=True, help="Research-delivery YAML config path.")
    parser.add_argument(
        "--run-id",
        default=datetime.now(timezone.utc).strftime("preview_%Y%m%dT%H%M%SZ"),
        help="New output run directory name. Existing run directories are never overwritten.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write a new test preview. Without this flag, the command is a read-only dry run.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_delivery_config(Path(args.config))
    result = build_delivery(config, run_id=args.run_id, write=args.write)

    print("WRITE COMPLETE" if result.wrote_files else "DRY RUN — NO FILES WRITTEN")
    print(f"Target: {result.target_dir}")
    print(f"Delivery config SHA-256: {result.config_sha256}")
    print(f"Latest usable date: {result.latest_usable_date or 'none'}")
    print("Dates:")
    for inspection in result.dates:
        print(
            f"  {inspection.date}: {inspection.status}; {inspection.reason} "
            f"rows={len(inspection.rows)} qc_issues={len(inspection.qc_flags)}"
        )
    if not args.write:
        print("Review this plan, then rerun the same command with --write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
