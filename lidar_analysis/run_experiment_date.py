#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one LiDAR experiment date from an explicit local input folder.")
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--input", required=True, help="Local per-date input folder containing raw data and experiment_config.yaml")
    parser.add_argument("--working", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", help="Optional explicit local experiment_config.yaml override")
    parser.add_argument("--cart-id")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--fusion", default="interp", choices=["interp", "imu_interp", "pps"])
    return parser.parse_args()


def resolve_config_path(input_dir: Path, explicit_config: str | None) -> Path:
    if explicit_config:
        cfg = Path(explicit_config).resolve()
    else:
        cfg = (input_dir / "experiment_config.yaml").resolve()

    if not cfg.exists():
        raise FileNotFoundError(f"Missing experiment config: {cfg}")

    return cfg


def call_runner(args: argparse.Namespace, input_dir: Path, config_path: Path) -> int:
    try:
        from . import central_runner  # type: ignore
    except Exception:
        import central_runner  # type: ignore

    experiment_config = central_runner._load_yaml(config_path)
    analysis_cfg = central_runner.extract_analysis_cfg(experiment_config)
    central_runner.run_experiment_date(
        experiment=args.experiment,
        date_name=args.date,
        input_dir=input_dir,
        working_dir=Path(args.working).resolve(),
        output_dir=Path(args.output).resolve(),
        experiment_config=experiment_config,
        experiment_analysis=analysis_cfg,
        cart_id=args.cart_id,
        force=bool(args.force),
        fusion_method=args.fusion,
    )
    return 0


def main() -> None:
    args = parse_args()
    input_dir = Path(args.input).resolve()
    working_dir = Path(args.working).resolve()
    output_dir = Path(args.output).resolve()

    if not input_dir.exists():
        raise FileNotFoundError(f"Missing input directory: {input_dir}")

    working_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    config_path = resolve_config_path(input_dir, args.config)
    rc = call_runner(args, input_dir, config_path)
    if rc != 0:
        raise SystemExit(rc)


if __name__ == "__main__":
    main()
