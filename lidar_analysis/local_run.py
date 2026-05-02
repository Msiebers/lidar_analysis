#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path

try:
    from .orchestrator import PipelinePaths, process_one_date
except Exception:
    from orchestrator import PipelinePaths, process_one_date


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the LiDAR pipeline locally with reproducible workspace roots.")
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--raw-root", required=True, help="Local raw_data root containing <experiment>/<date>.")
    parser.add_argument("--experiments-root", required=True, help="Local experiments root for configs and optional published outputs.")
    parser.add_argument("--workspace-root", required=True, help="Workspace root for caches, manifests, logs, and run artifacts.")
    parser.add_argument("--publish", action="store_true", help="Publish outputs into the local experiments root.")
    parser.add_argument("--force", action="store_true", help="Force a rerun even if the manifest indicates the date is current.")
    parser.add_argument("--reuse-staged-input", action="store_true", help="Reuse cached staged input instead of copying from raw_root again.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    workspace_root = Path(args.workspace_root).resolve()
    paths = PipelinePaths(
        raw_root=Path(args.raw_root).resolve(),
        experiments_root=Path(args.experiments_root).resolve(),
        workspace_root=workspace_root,
        manifest_root=workspace_root / "manifests",
        log_root=workspace_root / "logs",
    )
    run_root = process_one_date(
        args.experiment,
        args.date,
        paths=paths,
        force=args.force,
        publish=args.publish,
        restage=not args.reuse_staged_input,
    )
    print(f"[Local Run] completed at {run_root}")


if __name__ == "__main__":
    main()
