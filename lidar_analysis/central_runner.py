from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

try:
    from .config import AnalysisConfig
    from .pipeline_stages import DEFAULT_STAGES, StageContext
    from . import pipeline_core
except Exception:
    from config import AnalysisConfig
    from pipeline_stages import DEFAULT_STAGES, StageContext
    import pipeline_core

@dataclass
class NormalizedRunRequest:
    experiment: str
    date_name: str
    date_dir: Path
    working_dir: Path
    output_dir: Path
    config_path: Path
    force: bool = False
    fusion_method: str = "interp"
    cart_id_override: str | None = None

def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run central LiDAR analysis for one experiment/date")
    p.add_argument("--experiment", required=True, help="Experiment folder name")
    p.add_argument("--date", required=True, help="Date folder (YYYY_MM_DD)")
    p.add_argument("--input", required=True, help="Local per-date input directory")
    p.add_argument("--working", required=True, help="Local working directory")
    p.add_argument("--output", required=True, help="Local output directory")
    p.add_argument("--config", help="Optional explicit experiment config YAML path")
    p.add_argument("--cart-id", help="Optional cart id override")
    p.add_argument("--force", action="store_true", help="Reprocess scans even when outputs already exist")
    p.add_argument("--fusion", default="interp", choices=["interp", "pps"], help="Fusion method")
    return p.parse_args()

def resolve_config_path(input_dir: Path, explicit_config: str | None) -> Path:
    """
    Resolve experiment_config.yaml whether --input points at:

        date_root/
            source/experiment_config.yaml

    or directly at:

        source/
            experiment_config.yaml

    The watcher currently passes --input as the source directory.
    """
    if explicit_config:
        cfg = Path(explicit_config).resolve()
        if not cfg.exists():
            raise FileNotFoundError(f"Experiment config not found: {cfg}")
        return cfg

    input_dir = Path(input_dir).resolve()

    candidates = [
        input_dir / "experiment_config.yaml",
        input_dir / "source" / "experiment_config.yaml",
    ]

    for cfg in candidates:
        if cfg.exists():
            return cfg.resolve()

    raise FileNotFoundError(
        "Experiment config not found. Tried: "
        + ", ".join(str(p) for p in candidates)
    )


def normalize_request(args: argparse.Namespace) -> NormalizedRunRequest:
    if not (args.input and args.working and args.output):
        raise ValueError("--input, --working, and --output are required")

    date_dir = Path(args.input).resolve()
    working_dir = Path(args.working).resolve()
    output_dir = Path(args.output).resolve()
    config_path = resolve_config_path(date_dir, args.config)

    return NormalizedRunRequest(
        experiment=args.experiment,
        date_name=args.date,
        date_dir=date_dir,
        working_dir=working_dir,
        output_dir=output_dir,
        config_path=config_path,
        force=bool(args.force),
        fusion_method=str(args.fusion),
        cart_id_override=args.cart_id,
    )


def discover_scan_pairs(date_dir: Path) -> tuple[list[tuple[str, Path, Path]], list[str]]:
    lidar_by_scan: dict[str, Path] = {}
    pico_by_scan: dict[str, Path] = {}
    ignored: list[str] = []

    for fp in sorted(date_dir.glob("*.csv")):
        if fp.name.endswith("_lidar.csv"):
            scan_id = fp.name[:-len("_lidar.csv")]
            if scan_id:
                lidar_by_scan[scan_id] = fp
            else:
                ignored.append(fp.name)
        elif fp.name.endswith("_pico.csv"):
            scan_id = fp.name[:-len("_pico.csv")]
            if scan_id:
                pico_by_scan[scan_id] = fp
            else:
                ignored.append(fp.name)
        else:
            ignored.append(fp.name)

    pairs: list[tuple[str, Path, Path]] = []
    for scan_id in sorted(set(lidar_by_scan) | set(pico_by_scan)):
        lidar_fp = lidar_by_scan.get(scan_id)
        pico_fp = pico_by_scan.get(scan_id)
        if lidar_fp and pico_fp:
            pairs.append((scan_id, lidar_fp, pico_fp))
        else:
            missing = "pico" if lidar_fp else "lidar"
            ignored.append(f"{scan_id} (missing {missing})")
    return pairs, ignored


def read_calibration_from_cart_config(cart_config_path: Path) -> dict:
    cfg = _load_yaml(cart_config_path)
    lidar_cfg = cfg.get("lidar", {}) or {}
    encoder_cfg = cfg.get("encoder", {}) or {}
    imu_cfg = cfg.get("imu", {}) or {}

    m_per_click = float(cfg.get("m_per_click", encoder_cfg.get("m_per_click", 0.0)))
    lidar_height_m = float(cfg.get("lidar_height_m", lidar_cfg.get("height_m", 0.0)))
    lidar_wheel_offset_m = float(cfg.get("lidar_wheel_offset_m", lidar_cfg.get("lidar_wheel_offset_m", 0.0)))

    imu_offset_cfg = cfg.get("imu_offset_m", imu_cfg.get("offset_m", {})) or {}
    imu_dx_m = float(imu_offset_cfg.get("dx", 0.0))
    imu_dy_m = float(imu_offset_cfg.get("dy", 0.0))
    imu_dz_m = float(imu_offset_cfg.get("dz", 0.0))

    tilt_bias_cfg = cfg.get("tilt_bias_deg", imu_cfg.get("tilt_bias_deg", {})) or {}
    roll_yaml = float(tilt_bias_cfg.get("roll_offset_deg", 0.0))
    pitch_yaml = float(tilt_bias_cfg.get("pitch_offset_deg", 0.0))

    cart_id = str(cfg.get("cart_id") or cfg.get("cart") or cfg.get("hostname") or "unknown")
    return {
        "cart_id": cart_id,
        "step_mm": m_per_click * 1000.0,
        "lidar_height_mm": lidar_height_m * 1000.0,
        "lidar_wheel_offset_mm": lidar_wheel_offset_m * 1000.0,
        "imu_offset_mm": [imu_dx_m * 1000.0, imu_dy_m * 1000.0, imu_dz_m * 1000.0],
        "roll_offset_deg": roll_yaml,
        "pitch_offset_deg": pitch_yaml,
    }


def build_config(experiment_config: dict, force: bool, cart_id: str, data_dir: Path) -> AnalysisConfig:
    marks_cfg = experiment_config.get("marks", {}) or {}

    split_source = experiment_config.get("split_source")
    if split_source is None:
        split_source = "marks" if bool(experiment_config.get("use_markers", False)) else "distance"

    mark_target_type = (
        marks_cfg.get("target_type")
        or experiment_config.get("mark_target_type")
        or experiment_config.get("marker_target_type")
        or "auto"
    )

    mark_z_buffer_u = (
        marks_cfg.get("buffer_u")
        if marks_cfg.get("buffer_u") is not None
        else experiment_config.get("mark_z_buffer_u")
        if experiment_config.get("mark_z_buffer_u") is not None
        else experiment_config.get("marker_z_buffer_u")
        if experiment_config.get("marker_z_buffer_u") is not None
        else 0.0
    )

    missing_mark_file = marks_cfg.get("missing_file")
    if missing_mark_file is None:
        missing_mark_file = experiment_config.get("missing_mark_file")
    if missing_mark_file is None and "markers_required" in experiment_config:
        missing_mark_file = "error" if bool(experiment_config.get("markers_required")) else "distance"
    if missing_mark_file is None:
        missing_mark_file = "error"

    write_marker_pointcloud = (
        marks_cfg.get("write_pointcloud")
        if marks_cfg.get("write_pointcloud") is not None
        else experiment_config.get("write_marker_pointcloud")
        if experiment_config.get("write_marker_pointcloud") is not None
        else False
    )

    return AnalysisConfig(
        data_dirs=[data_dir],
        calibration_dir=data_dir,
        cart_id=cart_id,
        split_source=str(split_source),
        mark_target_type=str(mark_target_type),
        mark_z_buffer_u=float(mark_z_buffer_u),
        markers_dirname=str(experiment_config.get("markers_dirname", "markers")),
        missing_mark_file=str(missing_mark_file),
        write_marker_pointcloud=bool(write_marker_pointcloud),

        make_point_cloud=bool(experiment_config.get("generate_pointclouds", True)),
        overwrite_outputs=bool(experiment_config.get("overwrite_pointclouds", True)),
        reprocess_scans=force,

        use_imu=bool(experiment_config.get("apply_imu", False)),
        imu_zero_mode=str(experiment_config.get("imu_zero_mode", "dense_median")),
        imu_zero_fraction=float(experiment_config.get("imu_zero_fraction", 0.5)),
        use_heading=bool(experiment_config.get("use_heading", False)),
        heading_sign=float(experiment_config.get("heading_sign", 1.0)),

        normalize_rssi=bool(experiment_config.get("normalize_rssi", False)),
        rssi_norm_mode=str(experiment_config.get("rssi_norm_mode", "percentile")),
        use_rssi_filter=bool(experiment_config.get("use_rssi_filter", False)),
        rssi_min=experiment_config.get("rssi_min"),
        rssi_max=experiment_config.get("rssi_max"),

        write_o3d_ply=bool(experiment_config.get("write_o3d_ply", False)),
        fusion_method=str(experiment_config.get("fusion_method", "interp")),
        dim_units=str(experiment_config.get("dim_units", "m")),
        row_width_u=float(experiment_config.get("row_width_u", 5.0)),
        start_u=experiment_config.get("start_u", 0.0),
        split_u=float(experiment_config.get("split_u", 0.0)),
        end_buffer_u=float(experiment_config.get("end_buffer_u", 0.5)),
        max_y_u=experiment_config.get("max_y_u"),
        x_min_u=experiment_config.get("x_min_u"),
        min_radius_u=experiment_config.get("min_radius_u"),
        use_o3d_sor=bool(experiment_config.get("use_o3d_sor", False)),
        o3d_sor_nb_neighbors=int(experiment_config.get("o3d_sor_nb_neighbors", 5)),
        o3d_sor_std_ratio=float(experiment_config.get("o3d_sor_std_ratio", 2.0)),
        use_o3d_voxel=bool(experiment_config.get("use_o3d_voxel", False)),
        o3d_voxel_size_mm=float(experiment_config.get("o3d_voxel_size_mm", 5.0)),
        topo_min_persistence=float(experiment_config.get("topo_min_persistence", 0.35)),
        topo_background_cut=float(experiment_config.get("topo_background_cut", 0.0)),
        topo_x_bin_m=float(experiment_config.get("topo_x_bin_m", 0.01)),
        topo_z_bin_m=float(experiment_config.get("topo_z_bin_m", 0.01)),
        roll_sign=float(experiment_config.get("roll_sign", -1.0)),
        pitch_sign=float(experiment_config.get("pitch_sign", -1.0)),
        run_lai=bool(experiment_config.get("run_lai", False)),
        run_height=bool(experiment_config.get("run_height", False)),
        run_topology=bool(experiment_config.get("run_topology", True)),
        run_o3d_metrics=bool(experiment_config.get("run_o3d_metrics", False)),
        write_lidar_per_plot=bool(experiment_config.get("write_lidar_per_plot", True)),
        additional_scan_side_split=bool(experiment_config.get("additional_scan_side_split", False)),
        additional_scan_side_axis=str(experiment_config.get("additional_scan_side_axis", "x")),
        additional_scan_positive_side_label=str(experiment_config.get("additional_scan_positive_side_label", "right")),
        additional_scan_negative_side_label=str(experiment_config.get("additional_scan_negative_side_label", "left")),
    )


def phenotype_columns() -> list[str]:
    return [
        "experiment",
        "date",
        "scan_id",
        "row",
        "plot",
        "height_m",
        "lai_even",
        "lai_uneven",
        "point_density_m2",
        "plot_length_m",
        "plot_width_m",
        "stand_topo_per_m",
        "stand_topo_left_count",
        "stand_topo_right_count",
        "o3d_points",
        "o3d_voxels",
        "points",
        "lidar_scans",
        "lidar_angles",
    ]


def ensure_results_csv(path: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=phenotype_columns())
        writer.writeheader()


def append_trait_rows(results_csv: Path, experiment: str, date_str: str, scan_id: str, recs: Iterable[dict]) -> None:
    ensure_results_csv(results_csv)
    with open(results_csv, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=phenotype_columns())
        for rec in recs:
            row = {
                "experiment": experiment,
                "date": date_str,
                "scan_id": scan_id,
                "row": rec.get("row"),
                "plot": rec.get("plot"),
                "height_m": rec.get("height_m"),
                "lai_even": rec.get("lai_even"),
                "lai_uneven": rec.get("lai_uneven"),
                "point_density_m2": rec.get("point_density_m2"),
                "plot_length_m": rec.get("plot_length_m"),
                "plot_width_m": rec.get("plot_width_m"),
                "stand_topo_per_m": rec.get("stand_topo_per_m"),
                "stand_topo_left_count": rec.get("stand_topo_left_count"),
                "stand_topo_right_count": rec.get("stand_topo_right_count"),
                "o3d_points": rec.get("o3d_points"),
                "o3d_voxels": rec.get("o3d_voxels"),
                "points": rec.get("points"),
                "lidar_scans": rec.get("lidar_scans"),
                "lidar_angles": rec.get("lidar_angles"),
            }
            writer.writerow(row)


def extract_analysis_cfg(experiment_config: dict) -> dict:
    analysis_cfg = experiment_config.get("analysis", {})
    if isinstance(analysis_cfg, dict) and analysis_cfg:
        return analysis_cfg
    return experiment_config



def run_experiment_date(
    *,
    experiment: str,
    date_name: str,
    input_dir: Path,
    working_dir: Path,
    output_dir: Path,
    experiment_config: dict,
    experiment_analysis: dict,
    cart_id: str | None = None,
    force: bool = False,
    fusion_method: str | None = None,
) -> Path:
    cart_cfg_yaml = input_dir / "cart_config.yaml"
    if not input_dir.exists():
        raise FileNotFoundError(f"Date directory not found: {input_dir}")
    if not cart_cfg_yaml.exists():
        raise FileNotFoundError(f"Missing cart config YAML: {cart_cfg_yaml}")

    working_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    pairs, skipped = discover_scan_pairs(input_dir)
    calibration = read_calibration_from_cart_config(cart_cfg_yaml)
    effective_cart_id = cart_id or str(calibration.get("cart_id", "unknown"))

    cfg = build_config(experiment_analysis, force, cart_id=effective_cart_id, data_dir=input_dir)
    if fusion_method:
        cfg.fusion_method = fusion_method

    row_width_m = pipeline_core._to_m_units(cfg.row_width_u, cfg.dim_units)
    start_m = None if cfg.start_u is None else pipeline_core._to_m_units(cfg.start_u, cfg.dim_units)
    end_buffer_m = pipeline_core._to_m_units(cfg.end_buffer_u, cfg.dim_units)
    max_y_m = None if cfg.max_y_u is None else pipeline_core._to_m_units(cfg.max_y_u, cfg.dim_units)
    x_min_m = None if cfg.x_min_u is None else pipeline_core._to_m_units(cfg.x_min_u, cfg.dim_units)
    min_radius_m = None if cfg.min_radius_u is None else pipeline_core._to_m_units(cfg.min_radius_u, cfg.dim_units)

    context = StageContext(
        experiment=experiment,
        date_name=date_name,
        date_dir=input_dir,
        output_dir=output_dir,
        cfg=cfg,
        calibration=calibration,
        width_mm=row_width_m * 1000.0,
        x_min_mm=None if x_min_m is None else x_min_m * 1000.0,
        start_mm_global=0.0 if start_m is None else start_m * 1000.0,
        end_buffer_mm=end_buffer_m * 1000.0,
        y_max_mm=None if max_y_m is None else max_y_m * 1000.0,
        min_radius_mm=None if min_radius_m is None else min_radius_m * 1000.0,
    )

    pointcloud_out = output_dir / "pointclouds"
    pointcloud_out.mkdir(parents=True, exist_ok=True)
    results_csv = output_dir / "results.csv"
    ensure_results_csv(results_csv)

    for scan_id, lidar_fp, pico_fp in pairs:
        print(f"[Run] Processing scan {scan_id}")
        trait_rows: list[dict] = []
        for stage in DEFAULT_STAGES:
            result = stage.run(context, scan_id, lidar_fp, pico_fp)
            trait_rows.extend(result.trait_rows)
        append_trait_rows(results_csv, experiment, date_name, scan_id, trait_rows)
        print(f"[Success] {scan_id}: wrote {len(trait_rows)} phenotype row(s)")

    return results_csv

def main() -> None:
    args = parse_args()
    request = normalize_request(args)
    if not request.config_path.exists():
        raise FileNotFoundError(f"Experiment config not found: {request.config_path}")
    experiment_config = _load_yaml(request.config_path)
    analysis_cfg = extract_analysis_cfg(experiment_config)
    run_experiment_date(
        experiment=request.experiment,
        date_name=request.date_name,
        input_dir=request.date_dir,
        working_dir=request.working_dir,
        output_dir=request.output_dir,
        experiment_config=experiment_config,
        experiment_analysis=analysis_cfg,
        cart_id=request.cart_id_override,
        force=request.force,
        fusion_method=request.fusion_method,
    )


if __name__ == "__main__":
    main()
