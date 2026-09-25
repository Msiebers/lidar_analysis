"""Researcher-facing presentation metadata for AnalysisConfig fields.

AnalysisConfig (config_schema.py's introspection of it) owns field existence,
type, and default. This module owns everything a human needs to make sense
of a field in a form: label, description, grouping, and editability tier.
The two are deliberately separate files so this one can be read and edited
by a person without touching introspection logic, and so config.py can
change shape without this module's presentation choices being authoritative
over what fields actually exist.

Sourcing discipline (per the Phase 1 audit): every description below is
drawn from something that already exists in the repository -- the real
`full_experiment_config_template.yaml`'s own inline comments, docstrings in
mta.py/pai.py/fad.py/pointcloud_ops.py, validator error messages in
config.py, or config.py's own code comments (e.g. the "Deprecated
compatibility shims" comment covering write_o3d_ply/run_o3d_metrics/
run_topology, and default_analysis_yaml_dict()'s exclusion list, both read
directly before writing this file). Nothing here asserts that a setting is
scientifically "better" in one position or another -- only what it controls.

No YAML translation lives here. Whether a field's YAML key matches its
Python name (most do) or differs (a handful documented in the Phase 1 audit,
e.g. generate_pointclouds -> make_point_cloud) is Web-P1B's concern. A field
description below may *mention* the differing YAML key name for a researcher
reading the field later, since that's just informational prose -- but no
translation logic exists in this module.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

from lidar_analysis.webapp.config_schema import (
    analysis_config_field_names,
    introspect_analysis_config_fields,
)


class Tier(enum.Enum):
    """Editability/visibility tier for a field or pointcloud_ops parameter."""

    BASIC = "basic"
    ADVANCED = "advanced"
    EXPERT = "expert"
    LOCKED = "locked"
    HIDDEN_SYSTEM = "hidden_system"


class ControlType(enum.Enum):
    """The fundamental widget a field's *type* implies -- independent of
    tier. A LOCKED field still has a real control_type (e.g. NUMBER for
    mta_fit_angle_min_deg); tier/read_only governs whether it's editable,
    control_type governs what widget would render it."""

    TOGGLE = "toggle"
    NUMBER = "number"
    TEXT = "text"
    SELECT = "select"
    PATH = "path"
    POINTCLOUD_OPS_PIPELINE = "pointcloud_ops_pipeline"  # see PointcloudOpMetadata
    RAW = "raw"  # unstructured dict/list with no dedicated widget yet (pcl_backend)


@dataclass(frozen=True)
class FieldMetadata:
    name: str
    label: str
    description: str
    section: str
    tier: Tier
    control_type: ControlType
    choices: tuple[str, ...] = ()
    read_only: bool = False
    locked_value: Any = None  # set only when tier is LOCKED


def _basic(name, label, desc, section, ctrl, **kw):
    return FieldMetadata(name, label, desc, section, Tier.BASIC, ctrl, **kw)


def _advanced(name, label, desc, section, ctrl, **kw):
    return FieldMetadata(name, label, desc, section, Tier.ADVANCED, ctrl, **kw)


def _expert(name, label, desc, section, ctrl, **kw):
    return FieldMetadata(name, label, desc, section, Tier.EXPERT, ctrl, **kw)


def _locked(name, label, desc, section, ctrl, locked_value, **kw):
    return FieldMetadata(
        name, label, desc, section, Tier.LOCKED, ctrl,
        read_only=True, locked_value=locked_value, **kw
    )


def _hidden(name, label, desc, section, ctrl, **kw):
    return FieldMetadata(
        name, label, desc, section, Tier.HIDDEN_SYSTEM, ctrl,
        read_only=True, **kw
    )


# ---------------------------------------------------------------------------
# Sections, matching the Phase 1 audit's proposed form hierarchy.
# ---------------------------------------------------------------------------
S_LAYOUT = "Experiment / plot layout"
S_FUSION = "Fusion & IMU"
S_RSSI = "RSSI"
S_GROUND = "Ground filtering"
S_RAYBOX = "Shared ray-box geometry"
S_MTA = "Traits / MTA"
S_HEIGHT = "Traits / Height"
S_FAD = "Traits / FAD"
S_PAI = "Traits / PAI & Z-PAI"
S_OUTPUT = "Output"
S_POINTCLOUD = "Point-cloud processing pipeline"
S_SYSTEM = "System (not YAML-configurable)"


UI_METADATA: dict[str, FieldMetadata] = {}


def _register(*entries: FieldMetadata) -> None:
    for entry in entries:
        UI_METADATA[entry.name] = entry


# --- System: supplied outside experiment_config.yaml entirely -------------
_register(
    _hidden("data_dirs", "Data directories", "Populated by the runner from the experiment's raw scan directory. Not part of experiment_config.yaml -- build_config() receives this as a separate argument.", S_SYSTEM, ControlType.PATH),
    _hidden("calibration_dir", "Calibration directory", "Populated by the runner from cart_config.yaml's location. Not part of experiment_config.yaml.", S_SYSTEM, ControlType.PATH),
    _hidden("cart_id", "Cart ID", "Comes from cart_config.yaml, not the experiment YAML.", S_SYSTEM, ControlType.TEXT),
    _hidden("reprocess_scans", "Reprocess scans", "Set from the --force command-line flag when the pipeline is run. experiment_config.yaml has no effect on this value.", S_SYSTEM, ControlType.TOGGLE),
    _hidden("pai_run_conditional_profile", "PAI conditional profile", "build_config() always sets this to True regardless of what experiment_config.yaml says -- there is currently no way to configure it from the YAML file.", S_SYSTEM, ControlType.TOGGLE),
    _hidden("write_o3d_ply", "Write Open3D .ply", "config.py's own comment: a deprecated compatibility shim kept so old pipeline_core references don't crash while O3D/topology code is being pruned. Must stay False; should not appear in new experiment configs.", S_SYSTEM, ControlType.TOGGLE),
    _hidden("run_o3d_metrics", "Run Open3D metrics", "Same deprecated-shim comment as write_o3d_ply. Not referenced anywhere in the current pipeline's actual processing code.", S_SYSTEM, ControlType.TOGGLE),
    _hidden("run_topology", "Run topology (legacy top-level flag)", "Same deprecated-shim comment as write_o3d_ply. Topology-based stand counting today is controlled by the topology_trait pointcloud_ops entry, not this field -- this field is not referenced in pipeline_core.py's actual processing.", S_SYSTEM, ControlType.TOGGLE),
    _hidden("mta_lo_deg", "MTA low angle (legacy)", "Deprecated alias for mta_fit_angle_min_deg, silently mapped by map_deprecated_analysis_keys() if the new key is absent. This tool always writes the current key name instead.", S_SYSTEM, ControlType.NUMBER),
    _hidden("mta_hi_deg", "MTA high angle (legacy)", "Deprecated alias for mta_fit_angle_max_deg. See mta_lo_deg.", S_SYSTEM, ControlType.NUMBER),
    _hidden("mta_n_bins", "MTA bin count (legacy)", "Deprecated alias used to derive mta_angle_bin_deg when the modern key is absent. See mta_lo_deg.", S_SYSTEM, ControlType.NUMBER),
)

# --- Experiment / plot layout ----------------------------------------------
_register(
    _basic("split_source", "Splitting method", "How scans are divided into plots: by fixed distance along the row, or by marker files that identify each plant or plot.", S_LAYOUT, ControlType.SELECT, choices=("distance", "plant", "plot")),
    _basic("mark_target_type", "Marker target type", "When splitting by markers, what kind of target each marker identifies.", S_LAYOUT, ControlType.SELECT, choices=("auto", "plant", "plot")),
    _advanced("mark_z_buffer_u", "Marker buffer", "Extra buffer distance added around each marker window, in dim_units.", S_LAYOUT, ControlType.NUMBER),
    _advanced("markers_dirname", "Markers folder name", "Subfolder name (relative to the scan) containing marker files.", S_LAYOUT, ControlType.TEXT),
    _advanced("missing_mark_file", "Missing marker file behavior", "What to do when a plot's marker file is missing.", S_LAYOUT, ControlType.SELECT, choices=("error", "skip", "distance")),
    _expert("write_marker_pointcloud", "Write marker point cloud", "Write an extra diagnostic point-cloud file for each marker window.", S_LAYOUT, ControlType.TOGGLE),
    _expert("write_reference_points", "Write reference points", "Write the raw reference points used to place each marker window.", S_LAYOUT, ControlType.TOGGLE),
    _expert("write_window_pointcloud", "Write window point cloud", "Write the point cloud captured inside each marker's analysis window.", S_LAYOUT, ControlType.TOGGLE),
    _advanced("free_marks_as", "Unassigned marker handling", "How to treat markers not tied to a specific plot/plant.", S_LAYOUT, ControlType.SELECT, choices=("none", "plant", "plot")),
    _advanced("empty_mark_file", "Empty marker file behavior", "What to do when a marker file exists but is empty.", S_LAYOUT, ControlType.SELECT, choices=("skip", "error", "distance")),
    _expert("force_two_sided_targets", "Force two-sided targets", "Force otherwise single-target field scan names into left/right derived outputs. Only for reprocessing old single-target scans for side-aware traits; normal two-sided scans should use '&' in the scan name instead.", S_LAYOUT, ControlType.TOGGLE),
    _basic("analyze_one_side", "Analyze one side only", "Process only one side (left or right) of each scan instead of both.", S_LAYOUT, ControlType.TOGGLE),
    _basic("analyze_side", "Side to analyze", "Which side to process when 'analyze one side only' is enabled. Required (left or right) whenever that toggle is on.", S_LAYOUT, ControlType.SELECT, choices=("left", "right")),
    _expert("additional_scan_side_split", "Legacy additional-scan side split", "Legacy scan_* additional scans only. Normal field scans should use '&' in the scan name for natural two-sided outputs.", S_LAYOUT, ControlType.TOGGLE),
    _expert("additional_scan_side_axis", "Legacy side-split axis", "Axis used to split legacy additional scans into sides.", S_LAYOUT, ControlType.SELECT, choices=("x",)),
    _expert("additional_scan_positive_side_label", "Positive-side label (legacy)", "Label used for the positive-axis side in legacy additional-scan splitting.", S_LAYOUT, ControlType.TEXT),
    _expert("additional_scan_negative_side_label", "Negative-side label (legacy)", "Label used for the negative-axis side in legacy additional-scan splitting.", S_LAYOUT, ControlType.TEXT),
    _advanced("dim_units", "Distance units", "Units used for plot geometry: feet or meters.", S_LAYOUT, ControlType.SELECT, choices=("ft", "m")),
    _basic("row_width_u", "Row width", "Width of one row/plot, in dim_units.", S_LAYOUT, ControlType.NUMBER),
    _advanced("start_u", "Start offset", "Distance masked off at the start of a scan, in dim_units.", S_LAYOUT, ControlType.NUMBER),
    _advanced("split_u", "Split offset", "Distance offset used when splitting continuous scans into plots, in dim_units.", S_LAYOUT, ControlType.NUMBER),
    _advanced("end_buffer_u", "End buffer", "Distance masked off at the end of a scan, in dim_units.", S_LAYOUT, ControlType.NUMBER),
    _basic("n_plots", "Number of plots", "Expected number of plots in a continuous scan. Leave unset to let the pipeline infer it.", S_LAYOUT, ControlType.NUMBER),
    _advanced("max_y_u", "Maximum height mask", "Global height mask applied before analysis, in dim_units. Leave unset for no mask.", S_LAYOUT, ControlType.NUMBER),
    _advanced("x_min_u", "Minimum lateral distance", "Global lateral-distance mask applied before analysis, in dim_units.", S_LAYOUT, ControlType.NUMBER),
    _advanced("min_radius_u", "Minimum radius mask", "Global minimum-range mask applied before analysis, in dim_units.", S_LAYOUT, ControlType.NUMBER),
)

# --- Fusion & IMU ------------------------------------------------------------
_register(
    _basic("fusion_method", "Fusion method", "How the LiDAR and encoder/IMU data streams are time-aligned: interp (software clock interpolation), imu_interp (uses the IMU's own timestamp stream for orientation), or pps (hardware pulse-per-second clock lock).", S_FUSION, ControlType.SELECT, choices=("interp", "imu_interp", "pps")),
    _basic("use_imu", "Use IMU", "Whether IMU roll/pitch/yaw is used to correct scan geometry for cart motion on uneven ground.", S_FUSION, ControlType.TOGGLE),
    _advanced("imu_zero_mode", "IMU zero mode", "How the IMU's zero orientation is established.", S_FUSION, ControlType.SELECT, choices=("dense_median", "calibration")),
    _advanced("imu_zero_fraction", "IMU zero fraction", "Fraction of samples used to establish the IMU zero orientation when imu_zero_mode is dense_median.", S_FUSION, ControlType.NUMBER),
    _expert("use_heading", "Use heading", "Whether IMU heading (yaw) is applied, in addition to roll/pitch.", S_FUSION, ControlType.TOGGLE),
    _expert("heading_sign", "Heading sign", "Sign correction applied to IMU heading. Mounting-specific.", S_FUSION, ControlType.NUMBER),
    _expert("roll_sign", "Roll sign", "Sign correction applied to IMU roll. Per the template's own comment: mounting-specific, validate from the physical ground plane rather than assuming left/right symmetry.", S_FUSION, ControlType.NUMBER),
    _expert("pitch_sign", "Pitch sign", "Sign correction applied to IMU pitch. Mounting-specific, same caveat as roll_sign.", S_FUSION, ControlType.NUMBER),
)

# --- RSSI --------------------------------------------------------------------
_register(
    _advanced("normalize_rssi", "Normalize RSSI", "Whether LiDAR return-intensity (RSSI) is normalized by scan angle before use, correcting for sensor-geometry bias unrelated to what's being measured.", S_RSSI, ControlType.TOGGLE),
    _advanced("rssi_norm_mode", "RSSI normalization mode", "Method used to normalize RSSI within each scan angle.", S_RSSI, ControlType.SELECT, choices=("percentile", "zscore")),
    _advanced("rssi_norm_transform", "RSSI normalization transform", "Transform applied after normalization.", S_RSSI, ControlType.SELECT, choices=("none", "sqrt", "log1p", "exponential")),
    _advanced("use_rssi_filter", "Filter by RSSI", "Whether points are filtered by their (normalized) return intensity.", S_RSSI, ControlType.TOGGLE),
    _advanced("rssi_min", "RSSI minimum", "Minimum RSSI value retained when use_rssi_filter is on. Leave unset for no lower bound.", S_RSSI, ControlType.NUMBER),
    _advanced("rssi_max", "RSSI maximum", "Maximum RSSI value retained when use_rssi_filter is on. Leave unset for no upper bound.", S_RSSI, ControlType.NUMBER),
)

# --- Ground filtering ---------------------------------------------------------
_register(
    _basic("use_local_ground_filter", "Use local ground filter (legacy key)", "Legacy compatibility key for apply_ground_filter -- template's own comment. Setting either this or apply_ground_filter sets both.", S_GROUND, ControlType.TOGGLE),
    _basic("apply_ground_filter", "Apply local ground filter", "Estimate ground height locally (per grid cell) rather than assuming one flat global height, so height/volume traits correct for uneven terrain.", S_GROUND, ControlType.TOGGLE),
    _advanced("local_ground_x_bin_m", "Ground grid cell width (X)", "Horizontal grid cell size for local ground estimation, meters.", S_GROUND, ControlType.NUMBER),
    _advanced("local_ground_z_bin_m", "Ground grid cell length (Z)", "Grid cell size along the row for local ground estimation, meters.", S_GROUND, ControlType.NUMBER),
    _advanced("local_ground_quantile", "Ground quantile", "Height percentile within each grid cell used as that cell's ground estimate (low, since ground points should be the lowest points before canopy).", S_GROUND, ControlType.NUMBER),
    _advanced("local_ground_min_points_per_xz_bin", "Minimum points per ground cell", "Minimum point count required in a grid cell before its ground estimate is trusted.", S_GROUND, ControlType.NUMBER),
    _expert("local_ground_seed_y_min_m", "Ground seed band minimum", "Only raw height values in this band may seed a ground cell's estimate.", S_GROUND, ControlType.NUMBER),
    _expert("local_ground_seed_y_max_m", "Ground seed band maximum", "Upper bound of the ground-cell seeding band. See local_ground_seed_y_min_m.", S_GROUND, ControlType.NUMBER),
    _expert("local_ground_fallback_y_m", "Ground fallback height", "Height value used for a grid cell with no trustworthy local ground estimate.", S_GROUND, ControlType.NUMBER),
    _advanced("min_height_agl_m", "Minimum height above ground", "Points below this height-above-ground are excluded from analysis.", S_GROUND, ControlType.NUMBER),
)

# --- Shared ray-box geometry (PAI / Z-PAI / FAD / MTA) ------------------------
_register(
    _advanced("ray_box_ground_mode", "Ray-box ground mode", "Whether the shared ray-box geometry (used by PAI, Z-PAI, FAD, and MTA) references the local ground grid or a single global height.", S_RAYBOX, ControlType.SELECT, choices=("local_grid", "global_y")),
    _advanced("ray_box_bottom_agl_m", "Ray-box bottom height", "Lower bound of the shared ray-box, height above ground, meters.", S_RAYBOX, ControlType.NUMBER),
    _advanced("ray_box_x_near_m", "Ray-box near distance", "Near-field exclusion distance from the LiDAR centerline for the shared ray-box.", S_RAYBOX, ControlType.NUMBER),
    _advanced("ray_box_height_percentile", "Ray-box height percentile", "Height percentile (with outlier rejection) used to set the top of the shared ray-box.", S_RAYBOX, ControlType.NUMBER),
    _expert("ray_box_height_buffer_m", "Ray-box height buffer", "Extra buffer added above the percentile-derived ray-box height.", S_RAYBOX, ControlType.NUMBER),
    _expert("ray_box_grubbs_alpha", "Ray-box outlier alpha", "Significance threshold for Grubbs outlier rejection when determining ray-box height.", S_RAYBOX, ControlType.NUMBER),
    _advanced("ray_box_layer_thickness_m", "Ray-box layer thickness", "Vertical layer thickness used when the ray-box is analyzed in layers.", S_RAYBOX, ControlType.NUMBER),
    _expert("ray_box_diagnostic", "Write ray-box diagnostics", "Write ray_box_diagnostics.csv for FAD, MTA, PAI, and Z-PAI.", S_RAYBOX, ControlType.TOGGLE),
)

# --- Traits: Height ------------------------------------------------------------
_register(
    _basic("run_height", "Compute height", "Compute canopy height as the 99th percentile of point height, with outlier rejection. The pipeline's own docstring labels this the 'Legacy canopy-height metric' -- present since the project's first commit, never replaced.", S_HEIGHT, ControlType.TOGGLE),
)

# --- Traits: MTA -----------------------------------------------------------
_register(
    _basic("run_mta", "Compute MTA", "Compute Mean Tilt Angle -- the apparent average inclination of canopy elements -- via the LI-COR/Lang gap-fraction inversion method (bounded_lang_v1).", S_MTA, ControlType.TOGGLE),
    _locked("mta_fit_angle_min_deg", "MTA fit angle minimum", "The bounded_lang_v1 method requires this fixed at 25 degrees -- config.py's validator rejects any other value.", S_MTA, ControlType.NUMBER, locked_value=25.0),
    _locked("mta_fit_angle_max_deg", "MTA fit angle maximum", "The bounded_lang_v1 method requires this fixed at 65 degrees -- config.py's validator rejects any other value.", S_MTA, ControlType.NUMBER, locked_value=65.0),
    _advanced("mta_angle_bin_deg", "MTA angle bin width", "Width of each angular bin used in the MTA fit, degrees.", S_MTA, ControlType.NUMBER),
    _advanced("mta_min_rays_per_bin", "MTA minimum rays per bin", "Minimum number of rays required in an angular bin before it's used in the MTA fit.", S_MTA, ControlType.NUMBER),
    _advanced("mta_min_path_m_per_bin", "MTA minimum path length per bin", "Minimum total ray path length required in an angular bin before it's used in the fit, meters.", S_MTA, ControlType.NUMBER),
    _advanced("mta_min_valid_fit_bins", "MTA minimum valid fit bins", "Minimum number of angular bins that must pass quality checks for an MTA estimate to be produced.", S_MTA, ControlType.NUMBER),
    _advanced("mta_min_solid_angle_coverage", "MTA minimum solid angle coverage", "Minimum fraction of solid angle that must be covered by valid bins for an MTA estimate to be produced.", S_MTA, ControlType.NUMBER),
    _advanced("mta_max_observation_range_m", "MTA maximum observation range", "Maximum ray range treated as a valid observation (also shared by PAI/Z-PAI). Leave unset for no limit.", S_MTA, ControlType.NUMBER),
    _expert("mta_diagnostic", "Write MTA diagnostics", "Write extra MTA diagnostic output.", S_MTA, ControlType.TOGGLE),
    _basic("run_lai", "Compute LAI", "Compute apparent Leaf Area Index from angular gap fraction, analogous to optical canopy analyzers (LAI-2000/2200-style). A related but distinct calculation from PAI below.", S_MTA, ControlType.TOGGLE),
)

# --- Traits: FAD -----------------------------------------------------------
_register(
    _basic("run_fad", "Compute FAD", "Compute apparent Foliage/Plant Area Density within the shared ray-box, using ray path-length and interception distance -- unlike whole-view gap-fraction methods, this is constrained to the defined plot volume.", S_FAD, ControlType.TOGGLE),
    _advanced("fad_height_percentile", "FAD height percentile", "Height percentile (with outlier rejection) used to determine the FAD box's upper bound.", S_FAD, ControlType.NUMBER),
    _expert("fad_x_near_m", "FAD near distance", "Near face of the FAD box, measured from the LiDAR centerline.", S_FAD, ControlType.NUMBER),
    _advanced("fad_y_min_m", "FAD minimum height", "Lower bound of the FAD box, height above ground.", S_FAD, ControlType.NUMBER),
    _expert("fad_height_buffer_m", "FAD height buffer", "Extra buffer added above the percentile-derived FAD box height.", S_FAD, ControlType.NUMBER),
    _expert("fad_grubbs_alpha", "FAD outlier alpha", "Significance threshold for Grubbs outlier rejection when determining FAD box height.", S_FAD, ControlType.NUMBER),
    _locked("fad_g_function", "FAD projection function", "Only 'spherical' (randomly oriented canopy elements, G=0.5) is currently implemented.", S_FAD, ControlType.SELECT, locked_value="spherical", choices=("spherical",)),
    _advanced("fad_run_layers", "Compute FAD by layer", "Compute FAD within vertical layers rather than as a single whole-box value.", S_FAD, ControlType.TOGGLE),
    _advanced("fad_layer_thickness_m", "FAD layer thickness", "Vertical layer thickness when fad_run_layers is on, meters.", S_FAD, ControlType.NUMBER),
    _expert("fad_include_layer_columns", "Include FAD layer columns", "Write one results.csv column per vertical layer, in addition to the integrated value.", S_FAD, ControlType.TOGGLE),
)

# --- Traits: PAI & Z-PAI -----------------------------------------------------
_register(
    _basic("run_pai", "Compute PAI", "Compute Plant Area Index via gap-fraction inversion within the shared ray-box.", S_PAI, ControlType.TOGGLE),
    _basic("run_z_pai", "Compute Z-PAI", "Compute Plant Area Index via the Zhao first-event maximum-likelihood method -- a distinct estimator from PAI above, sharing the same ray-box geometry.", S_PAI, ControlType.TOGGLE),
    _locked("pai_g_function", "PAI projection function", "Only 'spherical' (randomly oriented canopy elements) is currently implemented.", S_PAI, ControlType.SELECT, locked_value="spherical", choices=("spherical",)),
    _expert("pai_g_value", "PAI G value", "The projection coefficient used under the spherical leaf-angle assumption.", S_PAI, ControlType.NUMBER),
    _advanced("pai_height_percentile", "PAI height percentile", "Height percentile (with outlier rejection) used to determine the PAI box's upper bound.", S_PAI, ControlType.NUMBER),
    _expert("pai_grubbs_alpha", "PAI outlier alpha", "Significance threshold for Grubbs outlier rejection when determining PAI box height.", S_PAI, ControlType.NUMBER),
    _advanced("pai_y_min_m", "PAI minimum height", "Lower bound of the PAI box, height above ground.", S_PAI, ControlType.NUMBER),
    _expert("pai_x_near_m", "PAI near distance", "Near face of the PAI box, measured from the LiDAR centerline.", S_PAI, ControlType.NUMBER),
    _expert("pai_height_buffer_m", "PAI height buffer", "Extra buffer added above the percentile-derived PAI box height.", S_PAI, ControlType.NUMBER),
    _expert("pai_diagnostic", "Write PAI diagnostics", "Write extra PAI diagnostic output.", S_PAI, ControlType.TOGGLE),
    _expert("pai_run_layers", "Compute PAI by layer", "Compute PAI within vertical layers.", S_PAI, ControlType.TOGGLE),
    _expert("pai_run_joint_profile", "PAI joint profile", "Compute a joint PAI/Z-PAI vertical profile.", S_PAI, ControlType.TOGGLE),
    _advanced("pai_layer_thickness_m", "PAI layer thickness", "Vertical layer thickness when PAI layer options are on, meters.", S_PAI, ControlType.NUMBER),
    _expert("pai_include_layer_columns", "Include PAI layer columns", "Write one results.csv column per vertical layer, in addition to the integrated value.", S_PAI, ControlType.TOGGLE),
)

# --- Output ------------------------------------------------------------------
_register(
    _basic("make_point_cloud", "Generate point clouds", "Generate and save point-cloud files for each plot, in addition to the phenotype trait table. (YAML key: generate_pointclouds.)", S_OUTPUT, ControlType.TOGGLE),
    _advanced("overwrite_outputs", "Overwrite existing point clouds", "Overwrite existing point-cloud files instead of skipping already-generated ones. (YAML key: overwrite_pointclouds.)", S_OUTPUT, ControlType.TOGGLE),
    _advanced("write_lidar_per_plot", "Write raw LiDAR per plot", "Write the raw per-plot LiDAR point data alongside the trait results.", S_OUTPUT, ControlType.TOGGLE),
)

# --- Point-cloud processing pipeline (top-level field only; nested op
#     parameters are a separate schema concept, see PointcloudOpMetadata) ---
_register(
    _basic("pointcloud_ops", "Point-cloud processing pipeline", "An ordered list of point-cloud filtering/trait operations, each run in sequence on the previous op's output. See the dedicated pipeline schema (POINTCLOUD_OP_METADATA) for each operation's own parameters.", S_POINTCLOUD, ControlType.POINTCLOUD_OPS_PIPELINE),
    _expert("pcl_backend", "Point-cloud backend", "Optional backend selection. Template's own comment: pointcloud_ops currently support scipy only; leave unset.", S_POINTCLOUD, ControlType.RAW),
)


# ---------------------------------------------------------------------------
# Point-cloud operations: a separate, ordered, nested schema -- these are
# NOT flattened into fake top-level AnalysisConfig fields. Parameter names,
# defaults, and the canonical order below are taken directly from
# full_experiment_config_template.yaml, confirmed against the current
# pointcloud_ops.py dispatch (apply_pointcloud_ops) during the Phase 1 audit.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PointcloudOpParamMetadata:
    name: str
    label: str
    description: str
    control_type: ControlType
    default: Any = None
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class PointcloudOpMetadata:
    op_name: str
    label: str
    description: str
    parameters: tuple[PointcloudOpParamMetadata, ...] = field(default_factory=tuple)


# Canonical order per the real template config; pointcloud_ops is a
# sequential pipeline where each op transforms what the next one sees, so
# this order is meaningful, not incidental. Reordering is out of scope for
# Phase 1 (no drag-and-drop) -- the UI numbers these 1-8 to make the
# sequence visible rather than presenting them as independent checkboxes.
POINTCLOUD_OP_ORDER: tuple[str, ...] = (
    "scalar_range_filter",
    "sor_filter",
    "bilateral_scalar_filter",
    "height_range_filter",
    "voxel_count",
    "topology_trait",
    "slice_structure_trait",
    "canopy_volume_2p5d",
)

POINTCLOUD_OP_METADATA: dict[str, PointcloudOpMetadata] = {
    "scalar_range_filter": PointcloudOpMetadata(
        "scalar_range_filter", "Scalar range filter",
        "Keep only points whose named scalar value falls within a min/max range.",
        (
            PointcloudOpParamMetadata("scalar", "Scalar field", "Which scalar column to filter on (e.g. rssi_norm).", ControlType.TEXT, default="rssi_norm"),
            PointcloudOpParamMetadata("min", "Minimum", "Lower bound, inclusive. Leave unset for no lower bound.", ControlType.NUMBER, default=0.0),
            PointcloudOpParamMetadata("max", "Maximum", "Upper bound, inclusive. Leave unset for no upper bound.", ControlType.NUMBER, default=None),
        ),
    ),
    "sor_filter": PointcloudOpMetadata(
        "sor_filter", "Statistical outlier removal (SOR)",
        "Standard point-cloud noise removal: flags a point as an outlier if its mean distance to its k nearest neighbors exceeds the cloud-wide average by more than std_ratio standard deviations.",
        (
            PointcloudOpParamMetadata("mean_k", "Neighbors (k)", "Number of nearest neighbors averaged per point.", ControlType.NUMBER, default=3),
            PointcloudOpParamMetadata("std_ratio", "Std-dev ratio", "How many standard deviations above the mean neighbor-distance counts as an outlier.", ControlType.NUMBER, default=2.0),
        ),
    ),
    "bilateral_scalar_filter": PointcloudOpMetadata(
        "bilateral_scalar_filter", "Bilateral scalar filter",
        "Edge-preserving smoothing of a scalar field: nearby points with similar existing values are weighted more heavily than distant or dissimilar ones, smoothing noise without blurring real edges.",
        (
            PointcloudOpParamMetadata("scalar", "Scalar field", "Which scalar column to smooth.", ControlType.TEXT, default="rssi_norm"),
            PointcloudOpParamMetadata("sigma_spatial", "Spatial sigma", "Spatial weighting falloff, meters.", ControlType.NUMBER, default=0.03),
            PointcloudOpParamMetadata("sigma_range", "Range sigma", "Value-similarity weighting falloff.", ControlType.NUMBER, default=2.5),
            PointcloudOpParamMetadata("radius", "Neighbor radius", "Maximum distance to consider a neighbor, meters.", ControlType.NUMBER, default=0.06),
            PointcloudOpParamMetadata("min_neighbors", "Minimum neighbors", "Minimum neighbor count required to update a point's value.", ControlType.NUMBER, default=1),
            PointcloudOpParamMetadata("max_neighbors", "Maximum neighbors", "Cap on neighbors considered per point. 0 means no cap.", ControlType.NUMBER, default=0),
            PointcloudOpParamMetadata("replace_scalar", "Replace original", "Overwrite the original scalar column instead of writing a new one.", ControlType.TOGGLE, default=False),
            PointcloudOpParamMetadata("output_scalar", "Output field name", "Name of the new column, when not replacing the original.", ControlType.TEXT, default="rssi_norm_bilateral"),
        ),
    ),
    "height_range_filter": PointcloudOpMetadata(
        "height_range_filter", "Height range filter",
        "Keep only points whose coordinate on the given axis falls within a min/max range.",
        (
            PointcloudOpParamMetadata("axis", "Axis", "Which coordinate axis to filter on.", ControlType.SELECT, default="Y", choices=("X", "Y", "Z")),
            PointcloudOpParamMetadata("min_m", "Minimum", "Lower bound, meters. Leave unset for no lower bound.", ControlType.NUMBER, default=0.05),
            PointcloudOpParamMetadata("max_m", "Maximum", "Upper bound, meters. Leave unset for no upper bound.", ControlType.NUMBER, default=None),
        ),
    ),
    "voxel_count": PointcloudOpMetadata(
        "voxel_count", "Voxel count",
        "Discretize the point cloud into cubic voxels and count occupied voxels -- a structural volume proxy.",
        (
            PointcloudOpParamMetadata("voxel_size_m", "Voxel size", "Edge length of each cubic voxel, meters.", ControlType.NUMBER, default=0.05),
        ),
    ),
    "topology_trait": PointcloudOpMetadata(
        "topology_trait", "Topology-based stand count",
        "Counts distinct plant/stand locations using persistent homology -- a peak survives only if its persistence (how long it stays a distinct local maximum as a threshold sweeps down) exceeds min_persistence, filtering out noise while keeping real local peaks. The pipeline's own docstring labels this 'Legacy topology stand count.'",
        (
            PointcloudOpParamMetadata("min_persistence", "Minimum persistence", "Persistence threshold (fraction of point-cloud height) a peak must exceed to count as a detected plant.", ControlType.NUMBER, default=0.35),
            PointcloudOpParamMetadata("z_bin_m", "Z bin size", "Grid cell size used when projecting points for peak detection, meters.", ControlType.NUMBER, default=0.05),
            PointcloudOpParamMetadata("include_per_m2", "Include per-m2 count", "Also report stand count normalized by plot area, not just by plot length.", ControlType.TOGGLE, default=False),
            PointcloudOpParamMetadata("split_sides_for_single_plot", "Split sides for single plot", "Report left/right stand counts separately for a single-plot target.", ControlType.TOGGLE, default=False),
            PointcloudOpParamMetadata("skip_whole_when_split", "Skip whole-plot count when split", "Omit the combined whole-plot count when sides are split.", ControlType.TOGGLE, default=False),
            PointcloudOpParamMetadata("write_topology_objects", "Write topology objects", "Write the detected peak objects to a diagnostic file.", ControlType.TOGGLE, default=False),
        ),
    ),
    "slice_structure_trait": PointcloudOpMetadata(
        "slice_structure_trait", "Slice structure (volume / spread)",
        "Per height-slice, keeps only the largest connected point clump (rejecting disconnected noise/neighboring vegetation), then sums clump-area x slice-thickness across slices. Despite the historical name, the resulting stacked_hull_volume_m3 column is not a literal convex hull -- the pipeline's own docstring notes this explicitly: 'now means closed largest-clump slice volume.'",
        (
            PointcloudOpParamMetadata("slice_height_m", "Slice thickness", "Vertical thickness of each analysis slice, meters.", ControlType.NUMBER, default=0.05),
            PointcloudOpParamMetadata("height_axis", "Height axis", "Which axis is treated as vertical.", ControlType.SELECT, default="Y", choices=("X", "Y", "Z")),
            PointcloudOpParamMetadata("spread_axis", "Spread axis", "Which axis is treated as lateral spread.", ControlType.SELECT, default="X", choices=("X", "Y", "Z")),
            PointcloudOpParamMetadata("length_axis", "Length axis", "Which axis is treated as along-row length.", ControlType.SELECT, default="Z", choices=("X", "Y", "Z")),
            PointcloudOpParamMetadata("percentile_height", "Percentile height", "Height percentile used within each slice.", ControlType.NUMBER, default=50.0),
            PointcloudOpParamMetadata("min_points_per_slice", "Minimum points per slice", "Minimum point count required to analyze a slice.", ControlType.NUMBER, default=5),
            PointcloudOpParamMetadata("clump_grid_m", "Clump grid size", "Grid cell size used for connected-component (clump) detection, meters.", ControlType.NUMBER, default=0.05),
            PointcloudOpParamMetadata("clump_connectivity", "Clump connectivity", "Grid connectivity used to group cells into one clump.", ControlType.SELECT, default="8", choices=("4", "8")),
        ),
    ),
    "canopy_volume_2p5d": PointcloudOpMetadata(
        "canopy_volume_2p5d", "Canopy volume (2.5D grid)",
        "Grids the horizontal footprint into cells, takes a height percentile per occupied cell (no clump-filtering -- every occupied cell counts, unlike slice_structure_trait), and sums height x cell-area. Also reports observed_area_m2, the occupied-cell footprint area, and a coverage_fraction diagnostic.",
        (
            PointcloudOpParamMetadata("cell_size_m", "Grid cell size", "Horizontal grid cell edge length, meters. Must be > 0.", ControlType.NUMBER, default=0.01),
            PointcloudOpParamMetadata("height_percentile", "Height percentile", "Height percentile used within each grid cell. Must be between 0 and 100.", ControlType.NUMBER, default=95.0),
        ),
    ),
}


def all_analysis_config_field_names_covered() -> bool:
    """True if UI_METADATA accounts for exactly the AnalysisConfig fields
    that currently exist -- no more, no less. The real coverage test lives
    in tests/webapp/test_ui_metadata_coverage.py; this is a convenience
    the metadata module itself exposes."""
    return set(UI_METADATA.keys()) == analysis_config_field_names()
