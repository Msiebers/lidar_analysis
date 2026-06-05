from __future__ import annotations

import argparse
import csv
import dataclasses as _dc
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

try:
    from .config import AnalysisConfig, normalize_rssi_mode, map_deprecated_analysis_keys
    from .pipeline_stages import DEFAULT_STAGES, StageContext
    from . import pipeline_core
except Exception:
    from config import AnalysisConfig, normalize_rssi_mode, map_deprecated_analysis_keys
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
    p.add_argument("--fusion", default="interp", choices=["interp", "imu_interp", "pps"], help="Fusion method")
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


# ---------------------------------------------------------------------------
# Canonical marker / splitting resolution
#
# Going forward there is ONE marker decision in an experiment config:
#
#     splitting_style: distance | plant | plot
#
#   distance : no markers; split by distance (split_u / n_plots).
#   plant    : markers required; each mark is one plant.
#              window = mark_z +/- buffer_u  (symmetric, both sides).
#   plot     : markers required; start/stop mark pairs bound each plot.
#              window = start_z + buffer_u .. stop_z - buffer_u  (inset).
#
# `buffer_u` is a single key (in dim_units). Its dual meaning (symmetric for
# plant, inset for plot) is applied downstream in
# mark_splitting.build_mark_segments; it is NOT a separate toggle.
#
# Choosing `plant` or `plot` implies markers are required. If markers are
# missing the run is allowed to fail hard (that is intended, not an error to
# paper over).
#
# Legacy keys (split_source, use_markers, marks.target_type,
# mark_target_type, marker_target_type, marks.buffer_u, mark_z_buffer_u,
# marker_z_buffer_u) are still accepted for backward compatibility and are
# resolved below. No deprecation warnings yet, by design.
# ---------------------------------------------------------------------------

_VALID_SPLITTING_STYLES = ("distance", "plant", "plot")


def resolve_splitting_style(experiment_config: dict) -> tuple[str, str]:
    """
    Resolve the single canonical marker decision into the internal
    (split_source, mark_target_type) pair the rest of the pipeline uses:

        distance -> ("distance", "auto")
        plant    -> ("marks", "plant")
        plot     -> ("marks", "plot")

    If the canonical `splitting_style` key is absent, fall back to the
    legacy keys so existing configs keep working unchanged.
    """
    style = experiment_config.get("splitting_style")
    if style is not None:
        style = str(style).strip().lower()
        if style not in _VALID_SPLITTING_STYLES:
            raise ValueError(
                f"splitting_style must be one of {_VALID_SPLITTING_STYLES}; got {style!r}"
            )
        if style == "distance":
            return "distance", "auto"
        return "marks", style

    # ---- legacy fallback (silent, behavior-preserving) ----
    marks_cfg = experiment_config.get("marks", {}) or {}
    split_source = experiment_config.get("split_source")
    if split_source is None:
        split_source = "marks" if bool(experiment_config.get("use_markers", False)) else "distance"
    split_source = str(split_source).strip().lower()

    mark_target_type = (
        marks_cfg.get("target_type")
        or experiment_config.get("mark_target_type")
        or experiment_config.get("marker_target_type")
        or "auto"
    )
    mark_target_type = str(mark_target_type).strip().lower()
    return split_source, mark_target_type


def resolve_buffer_u(experiment_config: dict) -> float:
    """
    Single canonical key: `buffer_u` (in dim_units).

    Legacy aliases accepted silently; first present value wins:
        buffer_u, marks.buffer_u, mark_z_buffer_u, marker_z_buffer_u
    """
    marks_cfg = experiment_config.get("marks", {}) or {}
    for value in (
        experiment_config.get("buffer_u"),
        marks_cfg.get("buffer_u"),
        experiment_config.get("mark_z_buffer_u"),
        experiment_config.get("marker_z_buffer_u"),
    ):
        if value is not None:
            return float(value)
    return 0.0


def build_config(experiment_config: dict, force: bool, cart_id: str, data_dir: Path) -> AnalysisConfig:
    marks_cfg = experiment_config.get("marks", {}) or {}

    split_source, mark_target_type = resolve_splitting_style(experiment_config)
    mark_z_buffer_u = resolve_buffer_u(experiment_config)

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
    write_reference_points = (
        marks_cfg.get("write_reference_points")
        if marks_cfg.get("write_reference_points") is not None
        else bool(write_marker_pointcloud)
    )
    write_window_pointcloud = (
        marks_cfg.get("write_window_pointcloud")
        if marks_cfg.get("write_window_pointcloud") is not None
        else False
    )
    free_marks_as = (
        marks_cfg.get("free_marks_as")
        if marks_cfg.get("free_marks_as") is not None
        else experiment_config.get("free_marks_as")
        if experiment_config.get("free_marks_as") is not None
        else "none"
    )
    empty_mark_file = (
        marks_cfg.get("empty_file")
        if marks_cfg.get("empty_file") is not None
        else experiment_config.get("empty_mark_file")
        if experiment_config.get("empty_mark_file") is not None
        else "skip"
    )

    # Defaults come from the AnalysisConfig dataclass (single source of truth).
    # `pick` reads the YAML value if present, else the dataclass default, and
    # applies the same type coercion the old inline literals used (including
    # the same failure behavior on bad values).
    _DEFAULTS = {f.name: f.default for f in _dc.fields(AnalysisConfig)
                 if f.default is not _dc.MISSING}

    def pick(yaml_key: str, field: str, cast=None):
        value = experiment_config.get(yaml_key, _DEFAULTS[field])
        return cast(value) if cast is not None else value

    experiment_config = map_deprecated_analysis_keys(experiment_config)

    return AnalysisConfig(
        data_dirs=[data_dir],
        calibration_dir=data_dir,
        cart_id=cart_id,
        split_source=str(split_source),
        mark_target_type=str(mark_target_type),
        mark_z_buffer_u=float(mark_z_buffer_u),
        markers_dirname=pick("markers_dirname", "markers_dirname", str),
        missing_mark_file=str(missing_mark_file),
        write_marker_pointcloud=bool(write_marker_pointcloud),
        write_reference_points=bool(write_reference_points),
        write_window_pointcloud=bool(write_window_pointcloud),
        free_marks_as=str(free_marks_as),
        empty_mark_file=str(empty_mark_file),

        make_point_cloud=pick("generate_pointclouds", "make_point_cloud", bool),
        overwrite_outputs=pick("overwrite_pointclouds", "overwrite_outputs", bool),
        reprocess_scans=force,

        use_imu=bool(experiment_config.get("use_imu", experiment_config.get("apply_imu", _DEFAULTS["use_imu"]))),
        imu_zero_mode=pick("imu_zero_mode", "imu_zero_mode", str),
        imu_zero_fraction=pick("imu_zero_fraction", "imu_zero_fraction", float),
        use_heading=pick("use_heading", "use_heading", bool),
        heading_sign=pick("heading_sign", "heading_sign", float),

        normalize_rssi=pick("normalize_rssi", "normalize_rssi", bool),
        rssi_norm_mode=normalize_rssi_mode(pick("rssi_norm_mode", "rssi_norm_mode", str)),
        use_rssi_filter=pick("use_rssi_filter", "use_rssi_filter", bool),
        rssi_min=pick("rssi_min", "rssi_min"),
        rssi_max=pick("rssi_max", "rssi_max"),

        fusion_method=pick("fusion_method", "fusion_method", str),
        dim_units=pick("dim_units", "dim_units", str),
        row_width_u=pick("row_width_u", "row_width_u", float),
        start_u=pick("start_u", "start_u"),
        split_u=pick("split_u", "split_u", float),
        end_buffer_u=pick("end_buffer_u", "end_buffer_u", float),
        max_y_u=pick("max_y_u", "max_y_u"),
        x_min_u=pick("x_min_u", "x_min_u"),
        min_radius_u=pick("min_radius_u", "min_radius_u"),
        roll_sign=pick("roll_sign", "roll_sign", float),
        pitch_sign=pick("pitch_sign", "pitch_sign", float),
        run_lai=pick("run_lai", "run_lai", bool),
        run_height=pick("run_height", "run_height", bool),
        write_lidar_per_plot=pick("write_lidar_per_plot", "write_lidar_per_plot", bool),
        pointcloud_ops=experiment_config.get("pointcloud_ops", []),
        pcl_backend=experiment_config.get("pcl_backend"),
        additional_scan_side_split=pick("additional_scan_side_split", "additional_scan_side_split", bool),
        additional_scan_side_axis=pick("additional_scan_side_axis", "additional_scan_side_axis", str),
        additional_scan_positive_side_label=pick("additional_scan_positive_side_label", "additional_scan_positive_side_label", str),
        additional_scan_negative_side_label=pick("additional_scan_negative_side_label", "additional_scan_negative_side_label", str),
    )


def _pointcloud_op_enabled(cfg: AnalysisConfig, *names: str) -> bool:
    wanted = {str(n).strip().lower() for n in names}

    for op_cfg in getattr(cfg, "pointcloud_ops", []) or []:
        if not isinstance(op_cfg, dict):
            continue

        op_name = str(op_cfg.get("name", op_cfg.get("op", ""))).strip().lower()
        if op_name in wanted and op_cfg.get("enabled", True) is not False:
            return True

    return False


def phenotype_columns(cfg: AnalysisConfig) -> list[str]:
    cols = [
        "experiment",
        "date",
        "scan_id",
        "row",
        "plot",
    ]

    if bool(getattr(cfg, "run_height", False)):
        cols.append("height_m")

    if bool(getattr(cfg, "run_lai", False)):
        cols.extend([
            "lai_even",
            "lai_uneven",
            # "lai_even_gap_fraction_ring_1",
            # "lai_even_gap_fraction_ring_2",
            # "lai_even_gap_fraction_ring_3",
            # "lai_even_gap_fraction_ring_4",
            # "lai_even_gap_fraction_ring_5",
            # "lai_uneven_gap_fraction_ring_1",
            # "lai_uneven_gap_fraction_ring_2",
            # "lai_uneven_gap_fraction_ring_3",
            # "lai_uneven_gap_fraction_ring_4",
            # "lai_uneven_gap_fraction_ring_5",
            # "lai_n_scans",
            # "lai_n_angles",
            # "lai_n_rays",
            # "lai_gap_distance_m",
            # "lai_even_corrected_zero_gap_bins",
            # "lai_uneven_corrected_zero_gap_bins",
            # "lai_angle_column_used",
            # "lai_distance_column_used",
            # "lai_n_missing_range",
            # "lai_n_missing_angle",
        ])

    cols.extend([
        "point_density_m2",
        "plot_length_m",
        "plot_width_m",
    ])

    if _pointcloud_op_enabled(cfg, "topology_trait"):
        cols.extend([
            "stand_topo_per_m",
            "stand_topo_left_count",
            "stand_topo_right_count",
            "stand_topo_left_per_m",
            "stand_topo_right_per_m",
        ])

    if _pointcloud_op_enabled(cfg, "slice_structure_trait"):
        cols.extend([
            "stacked_hull_volume_m3",
            "max_spread_m",
            "spread_at_50_m",
        ])

    if _pointcloud_op_enabled(cfg, "voxel_count", "voxel_grid", "voxel_volume"):
        cols.append("voxel_count")

    cols.extend([
        "points",
        "lidar_scans",
        "lidar_angles",
    ])

    return cols


def ensure_results_csv(path: Path, cfg: AnalysisConfig) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=phenotype_columns(cfg))
        writer.writeheader()


def append_trait_rows(
    results_csv: Path,
    experiment: str,
    date_str: str,
    scan_id: str,
    recs: Iterable[dict],
    cfg: AnalysisConfig,
) -> None:
    fieldnames = phenotype_columns(cfg)

    with open(results_csv, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)

        for rec in recs:
            row = {
                "experiment": experiment,
                "date": date_str,
                "scan_id": rec.get("scan", scan_id),
                "row": rec.get("row"),
                "plot": rec.get("plot"),
                "height_m": rec.get("height_m"),
                "lai_even": rec.get("lai_even"),
                "lai_uneven": rec.get("lai_uneven"),
                # "lai_even_gap_fraction_ring_1": rec.get("lai_even_gap_fraction_ring_1"),
                # "lai_even_gap_fraction_ring_2": rec.get("lai_even_gap_fraction_ring_2"),
                # "lai_even_gap_fraction_ring_3": rec.get("lai_even_gap_fraction_ring_3"),
                # "lai_even_gap_fraction_ring_4": rec.get("lai_even_gap_fraction_ring_4"),
                # "lai_even_gap_fraction_ring_5": rec.get("lai_even_gap_fraction_ring_5"),
                # "lai_uneven_gap_fraction_ring_1": rec.get("lai_uneven_gap_fraction_ring_1"),
                # "lai_uneven_gap_fraction_ring_2": rec.get("lai_uneven_gap_fraction_ring_2"),
                # "lai_uneven_gap_fraction_ring_3": rec.get("lai_uneven_gap_fraction_ring_3"),
                # "lai_uneven_gap_fraction_ring_4": rec.get("lai_uneven_gap_fraction_ring_4"),
                # "lai_uneven_gap_fraction_ring_5": rec.get("lai_uneven_gap_fraction_ring_5"),
                # "lai_n_scans": rec.get("lai_n_scans"),
                # "lai_n_angles": rec.get("lai_n_angles"),
                # "lai_n_rays": rec.get("lai_n_rays"),
                # "lai_gap_distance_m": rec.get("lai_gap_distance_m"),
                # "lai_even_corrected_zero_gap_bins": rec.get("lai_even_corrected_zero_gap_bins"),
                # "lai_uneven_corrected_zero_gap_bins": rec.get("lai_uneven_corrected_zero_gap_bins"),
                # "lai_angle_column_used": rec.get("lai_angle_column_used"),
                # "lai_distance_column_used": rec.get("lai_distance_column_used"),
                # "lai_n_missing_range": rec.get("lai_n_missing_range"),
                # "lai_n_missing_angle": rec.get("lai_n_missing_angle"),
                "point_density_m2": rec.get("point_density_m2"),
                "plot_length_m": rec.get("plot_length_m"),
                "plot_width_m": rec.get("plot_width_m"),
                "stand_topo_per_m": rec.get("stand_topo_per_m"),
                "stand_topo_left_count": rec.get("stand_topo_left_count"),
                "stand_topo_right_count": rec.get("stand_topo_right_count"),
                "stand_topo_left_per_m": rec.get("stand_topo_left_per_m"),
                "stand_topo_right_per_m": rec.get("stand_topo_right_per_m"),
                "stacked_hull_volume_m3": rec.get("stacked_hull_volume_m3"),
                "max_spread_m": rec.get("max_spread_m"),
                "spread_at_50_m": rec.get("spread_at_50_m"),
                "voxel_count": rec.get("voxel_count"),
                "points": rec.get("points"),
                "lidar_scans": rec.get("lidar_scans"),
                "lidar_angles": rec.get("lidar_angles"),
            }

            writer.writerow({k: row.get(k) for k in fieldnames})


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
    ensure_results_csv(results_csv, cfg)

    for scan_id, lidar_fp, pico_fp in pairs:
        print(f"[Run] Processing scan {scan_id}")
        trait_rows: list[dict] = []
        for stage in DEFAULT_STAGES:
            result = stage.run(context, scan_id, lidar_fp, pico_fp)
            trait_rows.extend(result.trait_rows)
        append_trait_rows(results_csv, experiment, date_name, scan_id, trait_rows, cfg)
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
