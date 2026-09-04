from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
import csv
import dataclasses as _dc
from dataclasses import dataclass
import io
from pathlib import Path
import traceback
from typing import Iterable

import numpy as np
import pandas as pd
import yaml

try:
    from .config import AnalysisConfig, normalize_rssi_mode, normalize_rssi_transform, map_deprecated_analysis_keys, validate_mta_config
    from . import pipeline_core
except Exception:
    from config import AnalysisConfig, normalize_rssi_mode, normalize_rssi_transform, map_deprecated_analysis_keys, validate_mta_config
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
# Window splitting resolution
#
# New user-facing configs should use one workflow:
#
#     split_source: distance | marks
#     marks:
#       target_type: auto | plant | plot
#       buffer_u: ...
#
# Target = biological target from the scan filename.
# Window = distance- or mark-defined segment along the scan.
# Marks = files used to define windows.
#
# `buffer_u` is a single key in dim_units. Its dual meaning (symmetric for
# plant, inset for plot) is applied downstream in mark_splitting.build_mark_segments.
#
# Legacy keys (splitting_style, use_markers, mark_target_type,
# marker_target_type, top-level buffer_u, mark_z_buffer_u, marker_z_buffer_u,
# missing_mark_file, empty_mark_file, free_marks_as, and markers_dirname)
# are still accepted for backward compatibility and are resolved below. No
# deprecation warnings yet, by design.
# ---------------------------------------------------------------------------

_VALID_SPLITTING_STYLES = ("distance", "plant", "plot")


def resolve_splitting_style(experiment_config: dict) -> tuple[str, str]:
    """
    Resolve user-facing window splitting keys into the internal
    (split_source, mark_target_type) pair the rest of the pipeline uses.

    New configs should use split_source plus marks.target_type. The older
    splitting_style key is still accepted so existing configs keep working.
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
    User-facing key: `marks.buffer_u` (in dim_units).

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
    for key in (
        "mta_angle_bin_deg", "mta_fit_angle_min_deg", "mta_fit_angle_max_deg",
        "mta_min_rays_per_bin", "mta_min_path_m_per_bin", "mta_min_valid_fit_bins",
        "mta_min_solid_angle_coverage", "mta_max_observation_range_m",
    ):
        if isinstance(experiment_config.get(key), bool):
            raise ValueError(f"{key} must be numeric, not Boolean")

    return validate_mta_config(AnalysisConfig(
        data_dirs=[data_dir],
        calibration_dir=data_dir,
        cart_id=cart_id,
        split_source=str(split_source),
        mark_target_type=str(mark_target_type),
        mark_z_buffer_u=float(mark_z_buffer_u),
        markers_dirname=str(marks_cfg.get("dirname", experiment_config.get("markers_dirname", _DEFAULTS["markers_dirname"]))),
        missing_mark_file=str(missing_mark_file),
        write_marker_pointcloud=bool(write_marker_pointcloud),
        write_reference_points=bool(write_reference_points),
        write_window_pointcloud=bool(write_window_pointcloud),
        free_marks_as=str(free_marks_as),
        empty_mark_file=str(empty_mark_file),
        force_two_sided_targets=pick("force_two_sided_targets", "force_two_sided_targets", bool),

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
        rssi_norm_transform=normalize_rssi_transform(pick("rssi_norm_transform", "rssi_norm_transform", str)),
        use_rssi_filter=pick("use_rssi_filter", "use_rssi_filter", bool),
        use_local_ground_filter=pick("use_local_ground_filter", "use_local_ground_filter", bool),
        local_ground_x_bin_m=pick("local_ground_x_bin_m", "local_ground_x_bin_m", float),
        local_ground_z_bin_m=pick("local_ground_z_bin_m", "local_ground_z_bin_m", float),
        local_ground_quantile=pick("local_ground_quantile", "local_ground_quantile", float),
        local_ground_min_points_per_xz_bin=pick("local_ground_min_points_per_xz_bin", "local_ground_min_points_per_xz_bin", int),
        local_ground_seed_y_min_m=pick("local_ground_seed_y_min_m", "local_ground_seed_y_min_m"),
        local_ground_seed_y_max_m=pick("local_ground_seed_y_max_m", "local_ground_seed_y_max_m"),
        min_height_agl_m=pick("min_height_agl_m", "min_height_agl_m", float),
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
        run_mta=pick("run_mta", "run_mta", bool),
        mta_diagnostic=pick("mta_diagnostic", "mta_diagnostic", bool),
        mta_lo_deg=pick("mta_lo_deg", "mta_lo_deg", float),
        mta_hi_deg=pick("mta_hi_deg", "mta_hi_deg", float),
        mta_n_bins=pick("mta_n_bins", "mta_n_bins", int),
        mta_min_rays_per_bin=pick("mta_min_rays_per_bin", "mta_min_rays_per_bin", int),
        mta_angle_bin_deg=pick("mta_angle_bin_deg", "mta_angle_bin_deg", float),
        mta_fit_angle_min_deg=pick("mta_fit_angle_min_deg", "mta_fit_angle_min_deg", float),
        mta_fit_angle_max_deg=pick("mta_fit_angle_max_deg", "mta_fit_angle_max_deg", float),
        mta_min_path_m_per_bin=pick("mta_min_path_m_per_bin", "mta_min_path_m_per_bin", float),
        mta_min_valid_fit_bins=pick("mta_min_valid_fit_bins", "mta_min_valid_fit_bins", int),
        mta_min_solid_angle_coverage=pick("mta_min_solid_angle_coverage", "mta_min_solid_angle_coverage", float),
        mta_max_observation_range_m=(
            None if pick("mta_max_observation_range_m", "mta_max_observation_range_m") is None
            else pick("mta_max_observation_range_m", "mta_max_observation_range_m", float)
        ),
        run_height=pick("run_height", "run_height", bool),
        run_fad=pick("run_fad", "run_fad", bool),
        fad_height_percentile=pick("fad_height_percentile", "fad_height_percentile", float),
        fad_x_near_m=pick("fad_x_near_m", "fad_x_near_m", float),
        fad_y_min_m=pick("fad_y_min_m", "fad_y_min_m", float),
        fad_height_buffer_m=pick("fad_height_buffer_m", "fad_height_buffer_m", float),
        fad_grubbs_alpha=pick("fad_grubbs_alpha", "fad_grubbs_alpha", float),
        fad_g_function=pick("fad_g_function", "fad_g_function", str),
        fad_run_layers=pick("fad_run_layers", "fad_run_layers", bool),
        fad_layer_thickness_m=pick("fad_layer_thickness_m", "fad_layer_thickness_m"),
        fad_include_layer_columns=pick("fad_include_layer_columns", "fad_include_layer_columns", bool),
        run_pai=pick("run_pai", "run_pai", bool),
        pai_g_function=pick("pai_g_function", "pai_g_function", str),
        pai_g_value=pick("pai_g_value", "pai_g_value", float),
        pai_height_percentile=pick("pai_height_percentile", "pai_height_percentile", float),
        pai_grubbs_alpha=pick("pai_grubbs_alpha", "pai_grubbs_alpha", float),
        pai_y_min_m=pick("pai_y_min_m", "pai_y_min_m", float),
        pai_x_near_m=pick("pai_x_near_m", "pai_x_near_m", float),
        pai_height_buffer_m=pick("pai_height_buffer_m", "pai_height_buffer_m", float),
        pai_diagnostic=pick("pai_diagnostic", "pai_diagnostic", bool),
        pai_run_layers=pick("pai_run_layers", "pai_run_layers", bool),
        pai_run_joint_profile=pick("pai_run_joint_profile", "pai_run_joint_profile", bool),
        pai_run_conditional_profile=True,
        pai_layer_thickness_m=pick("pai_layer_thickness_m", "pai_layer_thickness_m"),
        pai_include_layer_columns=pick("pai_include_layer_columns", "pai_include_layer_columns", bool),
        write_lidar_per_plot=pick("write_lidar_per_plot", "write_lidar_per_plot", bool),
        pointcloud_ops=experiment_config.get("pointcloud_ops", []),
        pcl_backend=experiment_config.get("pcl_backend"),
        additional_scan_side_split=pick("additional_scan_side_split", "additional_scan_side_split", bool),
        additional_scan_side_axis=pick("additional_scan_side_axis", "additional_scan_side_axis", str),
        additional_scan_positive_side_label=pick("additional_scan_positive_side_label", "additional_scan_positive_side_label", str),
        additional_scan_negative_side_label=pick("additional_scan_negative_side_label", "additional_scan_negative_side_label", str),
    ))


def _pointcloud_op_enabled(cfg: AnalysisConfig, *names: str) -> bool:
    wanted = {str(n).strip().lower() for n in names}

    for op_cfg in getattr(cfg, "pointcloud_ops", []) or []:
        if not isinstance(op_cfg, dict):
            continue

        op_name = str(op_cfg.get("name", op_cfg.get("op", ""))).strip().lower()
        if op_name in wanted and op_cfg.get("enabled", True) is not False:
            return True

    return False

def _topology_internal_side_split_enabled(cfg: AnalysisConfig) -> bool:
    if bool(getattr(cfg, "force_two_sided_targets", False)):
        return False
    for op_cfg in getattr(cfg, "pointcloud_ops", []) or []:
        if not isinstance(op_cfg, dict):
            continue
        op_name = str(op_cfg.get("name", op_cfg.get("op", ""))).strip().lower()
        if op_name == "topology_trait" and op_cfg.get("enabled", True) is not False:
            return bool(op_cfg.get("split_sides_for_single_plot", False))
    return False


_RESULT_ID_FIELDS = (
    "experiment", "date", "scan_name", "scan_number", "plot", "side",
    "target_type", "target_id",
)
_RESULT_UNIQUE_FIELDS = ("experiment", "date", "scan_name", "scan_number", "plot", "side")


def _scan_number(scan_name: str) -> int | None:
    value = str(scan_name).strip()
    token = value[5:].split("_", 1)[0] if value.lower().startswith("scan_") else value
    return int(token) if token.isdigit() else None


def phenotype_columns(cfg: AnalysisConfig) -> list[str]:
    cols = list(_RESULT_ID_FIELDS)

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
    if bool(getattr(cfg, "run_mta", False)):
        cols.extend(["mta_deg", "mta_qc_pass"])

    if bool(getattr(cfg, "run_fad", False)):
        cols.extend(["fad_app_m2_m3", "fad_x_min_m", "fad_x_max_m"])
        if bool(getattr(cfg, "fad_run_layers", False)):
            cols.extend([
                "fad_lai_from_layers", "fad_integrated_m2_m2", "fad_n_layers",
                "fad_n_supported_layers", "fad_profile_support_fraction",
            ])

    if bool(getattr(cfg, "run_pai", False)):
        cols.extend(["pai_m2_m2", "pai_height_m", "pai_layer_thickness_m", "pai_n_layers"])

    cols.extend([
        "point_density_m2",
        "plot_length_m",
        "plot_width_m",
    ])

    if _pointcloud_op_enabled(cfg, "topology_trait"):
        cols.extend([
            "stand_topo_count",
            "stand_topo_per_m",
        ])
        if _topology_internal_side_split_enabled(cfg):
            cols.extend([
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

    if _pointcloud_op_enabled(cfg, "canopy_volume_2p5d"):
        cols.extend([
            "canopy_volume_2p5d_m3",
            "canopy_volume_2p5d_m3_m2",
            "canopy_volume_2p5d_occupied_cells",
            "canopy_volume_2p5d_total_cells",
            "canopy_volume_2p5d_observed_area_m2",
            "canopy_volume_2p5d_coverage_fraction",
        ])


    if _pointcloud_op_enabled(cfg, "voxel_count", "voxel_grid", "voxel_volume"):
        cols.extend([
            "voxel_count",
            "voxel_input_points",
            "voxel_input_min_x",
            "voxel_input_max_x",
            "voxel_size_m",
        ])

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
    recs = list(recs)
    base_fields = phenotype_columns(cfg)
    with open(results_csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        existing_fields = reader.fieldnames or []
        existing_rows = list(reader)

    layer_prefixes = ("fad_layer_",)
    if bool(getattr(cfg, "pai_include_layer_columns", False)):
        layer_prefixes += ("pai_layer_",)
    layer_fields = sorted({
        key
        for key in existing_fields
        if key.startswith(layer_prefixes) and key not in base_fields
    } | {
        key
        for rec in recs
        for key in rec
        if key.startswith(layer_prefixes) and key not in base_fields
    })
    insert_at = len(base_fields)
    fieldnames = base_fields[:insert_at] + layer_fields + base_fields[insert_at:]

    output_rows = []
    for rec in recs:
        row = dict(rec)
        scan_name = str(rec.get("scan_name") or scan_id)
        side = str(rec.get("side") or (rec.get("row") if rec.get("row") in {"left", "right"} else "none"))
        row.update({
            "experiment": experiment,
            "date": date_str,
            "scan_name": scan_name,
            "scan_number": _scan_number(scan_name),
            "plot": rec.get("plot"),
            "side": side,
            "target_type": rec.get("target_type", "plot"),
            "target_id": rec.get("target_id"),
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
            "fad_app_m2_m3": rec.get("fad_app_m2_m3"),
            "fad_lai_from_layers": rec.get("fad_lai_from_layers"),
            "fad_integrated_m2_m2": rec.get("fad_integrated_m2_m2"),
            "fad_n_layers": rec.get("fad_n_layers"),
            "point_density_m2": rec.get("point_density_m2"),
            "plot_length_m": rec.get("plot_length_m"),
            "plot_width_m": rec.get("plot_width_m"),
            "stand_topo_count": rec.get("stand_topo_count"),
            "stand_topo_per_m": rec.get("stand_topo_per_m"),
            "stand_topo_left_count": rec.get("stand_topo_left_count"),
            "stand_topo_right_count": rec.get("stand_topo_right_count"),
            "stand_topo_left_per_m": rec.get("stand_topo_left_per_m"),
            "stand_topo_right_per_m": rec.get("stand_topo_right_per_m"),
            "stacked_hull_volume_m3": rec.get("stacked_hull_volume_m3"),
            "max_spread_m": rec.get("max_spread_m"),
            "spread_at_50_m": rec.get("spread_at_50_m"),
            "canopy_volume_2p5d_m3": rec.get("canopy_volume_2p5d_m3"),
            "canopy_volume_2p5d_m3_m2": rec.get("canopy_volume_2p5d_m3_m2"),
            "canopy_volume_2p5d_occupied_cells": rec.get("canopy_volume_2p5d_occupied_cells"),
            "canopy_volume_2p5d_total_cells": rec.get("canopy_volume_2p5d_total_cells"),
            "canopy_volume_2p5d_observed_area_m2": rec.get("canopy_volume_2p5d_observed_area_m2"),
            "canopy_volume_2p5d_coverage_fraction": rec.get("canopy_volume_2p5d_coverage_fraction"),
            "voxel_count": rec.get("voxel_count"),
            "voxel_input_points": rec.get("voxel_input_points"),
            "voxel_input_min_x": rec.get("voxel_input_min_x"),
            "voxel_input_max_x": rec.get("voxel_input_max_x"),
            "voxel_size_m": rec.get("voxel_size_m"),
            "points": rec.get("points"),
            "lidar_scans": rec.get("lidar_scans"),
            "lidar_angles": rec.get("lidar_angles"),
        })

        output_rows.append({k: row.get(k) for k in fieldnames})

    all_rows = existing_rows + output_rows
    seen = set()
    duplicates = []
    for row in all_rows:
        identity = tuple(str(row.get(key) if row.get(key) is not None else "") for key in _RESULT_UNIQUE_FIELDS)
        if identity in seen:
            duplicates.append(dict(zip(_RESULT_UNIQUE_FIELDS, identity)))
        seen.add(identity)
    if duplicates:
        raise ValueError(f"Duplicate result identity: {duplicates}")

    def sort_key(row):
        try:
            scan_number = int(float(row.get("scan_number")))
        except (TypeError, ValueError):
            scan_number = 10**12
        return (
            str(row.get("date") or ""), scan_number, str(row.get("plot") or ""),
            str(row.get("side") or ""),
        )

    all_rows.sort(key=sort_key)
    frame = pd.DataFrame.from_records(all_rows, columns=fieldnames)
    for column in frame.columns.difference(_RESULT_ID_FIELDS):
        numeric = pd.to_numeric(frame[column], errors="coerce")
        if numeric.notna().sum() == frame[column].notna().sum():
            frame[column] = numeric
    pipeline_core.round_output_dataframe(frame).to_csv(
        results_csv, index=False, na_rep="", float_format="%.2f"
    )


def append_mta_diagnostics(
    path: Path,
    experiment: str,
    date_str: str,
    scan_id: str,
    recs: Iterable[dict],
) -> bool:
    rows = []
    for rec in recs:
        scan_name = str(rec.get("scan_name") or scan_id)
        side = str(rec.get("side") or (rec.get("row") if rec.get("row") in {"left", "right"} else "none"))
        identity = {
            "experiment": experiment,
            "date": date_str,
            "scan_name": scan_name,
            "scan_number": _scan_number(scan_name),
            "plot": rec.get("plot"),
            "side": side,
            "target_type": rec.get("target_type", "plot"),
            "target_id": rec.get("target_id"),
        }
        for diagnostic in rec.get("_mta_diagnostics", ()):
            rows.append(identity | dict(diagnostic))
    if not rows:
        return False

    existing = pd.read_csv(path, dtype={"scan_name": str}).to_dict("records") if path.exists() else []
    fieldnames = list(_RESULT_ID_FIELDS) + sorted(
        {key for row in existing + rows for key in row if key not in _RESULT_ID_FIELDS}
    )
    frame = pd.DataFrame.from_records(existing + rows, columns=fieldnames)
    frame = frame.sort_values(
        ["date", "scan_number", "plot", "side", "mta_direction_group", "mta_bin_role", "mta_bin_lower_deg"],
        kind="stable", na_position="last",
    )
    frame.to_csv(path, index=False, na_rep="", float_format="%.8g")
    return True


def append_pai_outputs(
    layer_path: Path,
    diagnostic_path: Path,
    experiment: str,
    date_str: str,
    scan_id: str,
    recs: Iterable[dict],
    cfg: AnalysisConfig,
) -> None:
    layer_rows = []
    diagnostic_rows = []
    for rec in recs:
        scan_name = str(rec.get("scan_name") or scan_id)
        identity = {
            "experiment": experiment, "date": date_str, "scan_name": scan_name,
            "scan_number": _scan_number(scan_name), "plot": rec.get("plot"),
            "side": rec.get("side", "none"), "target_type": rec.get("target_type", "plot"),
            "target_id": rec.get("target_id"),
        }
        layers = list(rec.get("_pai_layers", ()))
        diagnostic_base = identity | {
            "n_rays_total": rec.get("pai_n_rays_total"),
            "n_rays_intersecting_box": rec.get("pai_n_rays_intersecting_box"),
            "n_rays_observed": rec.get("pai_n_rays_observed"),
            "n_rays_rejected": int(rec.get("pai_n_rays_total") or 0) - int(rec.get("pai_n_rays_observed") or 0),
            "n_hits": rec.get("pai_n_hits"), "n_gap_rays": rec.get("pai_n_full_gaps"),
            "gap_fraction": rec.get("pai_gap_fraction"),
            "mean_chord_length_m": rec.get("pai_mean_chord_m"),
            "median_chord_length_m": rec.get("pai_median_chord_m"),
            "log_likelihood": rec.get("pai_log_likelihood"),
            "g_function": rec.get("pai_g_function"), "g_value": rec.get("pai_g_value"),
            "pai_height_m": rec.get("pai_height_m"),
            "whole_box_pad_m2_m3": rec.get("pai_whole_box_pad_m2_m3"),
            "whole_box_pai_m2_m2": rec.get("pai_whole_box_m2_m2"),
        }
        if cfg.pai_diagnostic and not layers:
            diagnostic_rows.append(diagnostic_base)
        finite_layers = [float(layer["pai_layer_m2_m2"]) for layer in layers
                         if pd.notna(layer.get("pai_layer_m2_m2"))]
        if layers and len(finite_layers) == len(layers) and pd.notna(rec.get("pai_m2_m2")):
            if not np.isclose(float(rec["pai_m2_m2"]), sum(finite_layers)):
                raise AssertionError("Total PAI must equal the sum of layer PAI")
        for layer in layers:
            thickness = float(layer["layer_thickness_m"])
            pad = layer.get("pad_layer_m2_m3")
            layer_pai = layer.get("pai_layer_m2_m2")
            if pd.notna(pad) and pd.notna(layer_pai) and not np.isclose(float(layer_pai), float(pad) * thickness):
                raise AssertionError("Layer PAI must equal PAD times layer thickness")
            if cfg.pai_diagnostic:
                diagnostic_rows.append(diagnostic_base | layer)

    def write(path: Path, rows: list[dict]) -> None:
        if not rows:
            return
        existing = pd.read_csv(path, dtype={"scan_name": str}).to_dict("records") if path.exists() else []
        fields = list(_RESULT_ID_FIELDS) + sorted(
            {key for row in existing + rows for key in row if key not in _RESULT_ID_FIELDS}
        )
        frame = pd.DataFrame.from_records(existing + rows, columns=fields)
        sort_columns = [key for key in ["date", "scan_number", "plot", "side", "layer_bottom_m"] if key in frame.columns]
        frame = frame.sort_values(
            sort_columns,
            kind="stable", na_position="last",
        )
        frame.to_csv(path, index=False, na_rep="", float_format="%.8g")

    write(layer_path, layer_rows)
    write(diagnostic_path, diagnostic_rows)


def extract_analysis_cfg(experiment_config: dict) -> dict:
    analysis_cfg = experiment_config.get("analysis", {})
    if isinstance(analysis_cfg, dict) and analysis_cfg:
        return analysis_cfg
    return experiment_config


def resolve_parallel_scans(experiment_config: dict) -> int | None:
    processing = experiment_config.get("processing")
    if processing is None:
        processing = {}
    if not isinstance(processing, dict):
        raise ValueError("processing must be a mapping")
    value = processing.get("parallel_scans")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("processing.parallel_scans must be null or a positive integer")
    return value


def _process_scan_worker(scan_id: str, kwargs: dict) -> tuple[str, list[dict], str, str | None]:
    output = io.StringIO()
    try:
        with redirect_stdout(output), redirect_stderr(output):
            rows = pipeline_core.process_scan(scan_base=scan_id, **kwargs) or []
        return scan_id, rows, output.getvalue(), None
    except Exception:
        return scan_id, [], output.getvalue(), traceback.format_exc()


def _completed_scans(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def _record_completed_scan(path: Path, scan_id: str) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{scan_id}\n")



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

    pointcloud_out = output_dir / "pointclouds"
    pointcloud_out.mkdir(parents=True, exist_ok=True)
    results_csv = output_dir / "results.csv"
    mta_diagnostics_csv = output_dir / "mta_diagnostics.csv"
    pai_layers_csv = output_dir / "pai_layers.csv"
    pai_diagnostics_csv = output_dir / "pai_diagnostics.csv"
    completed_path = output_dir / "completed_scans.txt"
    if force:
        completed_path.unlink(missing_ok=True)
        mta_diagnostics_csv.unlink(missing_ok=True)
        pai_layers_csv.unlink(missing_ok=True)
        pai_diagnostics_csv.unlink(missing_ok=True)
    if force or not completed_path.exists():
        ensure_results_csv(results_csv, cfg)
    elif not results_csv.exists():
        completed_path.unlink()
        ensure_results_csv(results_csv, cfg)

    completed = _completed_scans(completed_path)
    pending = [pair for pair in pairs if pair[0] not in completed]
    for scan_id in sorted(completed.intersection(scan_id for scan_id, _, _ in pairs)):
        print(f"[Skip] {scan_id}: already completed")
    if not pending:
        return results_csv

    common_kwargs = {
        "out_dir": str(pointcloud_out),
        "cfg": cfg,
        "width_mm": row_width_m * 1000.0,
        "start_mm_global": 0.0 if start_m is None else start_m * 1000.0,
        "end_buffer_mm": end_buffer_m * 1000.0,
        "y_max_mm": None if max_y_m is None else max_y_m * 1000.0,
        "x_min_mm": None if x_min_m is None else x_min_m * 1000.0,
        "min_radius_mm": None if min_radius_m is None else min_radius_m * 1000.0,
        "step_mm": calibration["step_mm"],
        "lidar_height_mm": calibration["lidar_height_mm"],
        "lidar_wheel_offset_mm": calibration["lidar_wheel_offset_mm"],
        "roll_offset": calibration["roll_offset_deg"],
        "pitch_offset": calibration["pitch_offset_deg"],
        "imu_offset_mm": np.asarray(calibration["imu_offset_mm"], dtype=float),
    }

    def finish(scan_id: str, trait_rows: list[dict]) -> None:
        append_trait_rows(results_csv, experiment, date_name, scan_id, trait_rows, cfg)
        if cfg.mta_diagnostic:
            append_mta_diagnostics(
                mta_diagnostics_csv, experiment, date_name, scan_id, trait_rows
            )
        if cfg.run_pai and cfg.pai_diagnostic:
            append_pai_outputs(
                pai_layers_csv, pai_diagnostics_csv,
                experiment, date_name, scan_id, trait_rows, cfg,
            )
        _record_completed_scan(completed_path, scan_id)
        print(f"[Success] {scan_id}: wrote {len(trait_rows)} phenotype row(s)")

    parallel_scans = resolve_parallel_scans(experiment_config)
    if parallel_scans is None:
        for scan_id, lidar_fp, pico_fp in pending:
            print(f"[Run] Processing scan {scan_id}")
            trait_rows = pipeline_core.process_scan(
                scan_base=scan_id,
                lidar_path=str(lidar_fp),
                pico_path=str(pico_fp),
                **common_kwargs,
            ) or []
            finish(scan_id, trait_rows)
        return results_csv

    jobs = []
    with ProcessPoolExecutor(max_workers=parallel_scans) as executor:
        for scan_id, lidar_fp, pico_fp in pending:
            print(f"[Run] Queueing scan {scan_id}")
            kwargs = dict(common_kwargs, lidar_path=str(lidar_fp), pico_path=str(pico_fp))
            jobs.append((scan_id, executor.submit(_process_scan_worker, scan_id, kwargs)))

        errors = []
        for scan_id, future in jobs:
            try:
                _, trait_rows, worker_output, error = future.result()
            except Exception:
                trait_rows, worker_output, error = [], "", traceback.format_exc()
            if worker_output:
                print(worker_output, end="" if worker_output.endswith("\n") else "\n")
            if error is None:
                finish(scan_id, trait_rows)
            else:
                errors.append((scan_id, error))
                print(f"[Error] {scan_id} failed")

    if errors:
        scan_id, error = errors[0]
        raise RuntimeError(f"Scan {scan_id} failed:\n{error}")

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
