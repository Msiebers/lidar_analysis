from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import yaml

try:
    from .plant_geometry import compute_plant_geometry_traits
except Exception:
    from plant_geometry import compute_plant_geometry_traits


_FLOAT_AUDIT_FIELDS = (
    "plant_height_m",
    "footprint_area_m2",
    "canopy_envelope_volume_m3",
    "canopy_occupied_volume_m3",
    "geometry_confidence",
    "geometry_boundary_fraction",
)
_INTEGER_AUDIT_FIELDS = (
    "geometry_selected_points",
    "geometry_footprint_cells",
    "geometry_height_cells",
)
_TEXT_AUDIT_FIELDS = (
    "geometry_qc_status",
    "geometry_qc_flags",
    "geometry_volume_method",
)


def _load_geometry_config(config_path: Path) -> dict[str, Any]:
    with config_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    if not isinstance(config, dict):
        raise ValueError(f"Config must contain a mapping: {config_path}")

    analysis = config.get("analysis", config)
    if not isinstance(analysis, dict):
        raise ValueError(f"Config analysis section must be a mapping: {config_path}")
    operations = analysis.get("pointcloud_ops", []) or []
    for operation in operations:
        if (
            isinstance(operation, dict)
            and operation.get("op") == "plant_geometry_trait"
            and operation.get("enabled", True)
        ):
            return dict(operation)
    raise ValueError(f"No enabled plant_geometry_trait operation in {config_path}")


def _identifier(value: Any) -> str:
    if isinstance(value, (float, np.floating)) and np.isfinite(value) and value.is_integer():
        return str(int(value))
    return str(value)


def _optional_float(row: pd.Series, key: str) -> float | None:
    value = row.get(key)
    if value is None or pd.isna(value):
        return None
    number = float(value)
    return number if np.isfinite(number) else None


def _geometry_context(row: pd.Series) -> dict[str, float]:
    context: dict[str, float] = {}
    for key in ("target_z_min_m", "target_z_max_m", "target_center_z_m"):
        value = _optional_float(row, key)
        if value is not None:
            context[key] = value
    return context


def _pointcloud_path(pointcloud_dir: Path, row: pd.Series) -> Path:
    row_id = _identifier(row["row"])
    filename = f"{row_id}_{row['plot']}_{row['scan_id']}.csv"
    if Path(filename).name != filename:
        raise ValueError(f"Unsafe point-cloud filename derived from results row: {filename!r}")
    path = (pointcloud_dir / filename).resolve()
    if pointcloud_dir.resolve() not in path.parents:
        raise ValueError(f"Point-cloud path escapes its input directory: {path}")
    if not path.is_file():
        raise FileNotFoundError(f"Missing point cloud for results row: {path}")
    return path


def _normalized_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value)


def _normalized_integer(value: Any) -> int | float:
    """Preserve missing support counts so the audit can report a mismatch."""
    if value is None or pd.isna(value):
        return float("nan")
    number = float(value)
    if not np.isfinite(number):
        return float("nan")
    return int(number) if number.is_integer() else number


def _audit_target(
    row: pd.Series,
    traits: dict[str, Any],
    diagnostics: dict[str, Any],
    *,
    tolerance: float,
) -> dict[str, Any]:
    audit: dict[str, Any] = {
        "date": row.get("date", ""),
        "scan_id": row["scan_id"],
        "row": _identifier(row["row"]),
        "plot": row["plot"],
        "crown_center_x_m": diagnostics.get("crown_center_x_m"),
        "crown_center_z_m": diagnostics.get("crown_center_z_m"),
        "crown_center_source": diagnostics.get("crown_center_source"),
    }
    mismatches: list[str] = []

    for key in _FLOAT_AUDIT_FIELDS:
        result_value = float(row[key])
        recomputed_value = float(traits[key])
        difference = abs(result_value - recomputed_value)
        audit[f"result_{key}"] = result_value
        audit[f"recomputed_{key}"] = recomputed_value
        audit[f"absolute_difference_{key}"] = difference
        if not np.isclose(result_value, recomputed_value, rtol=0.0, atol=tolerance, equal_nan=True):
            mismatches.append(key)

    for key in _INTEGER_AUDIT_FIELDS:
        result_value = _normalized_integer(row.get(key))
        recomputed_value = _normalized_integer(traits.get(key))
        audit[f"result_{key}"] = result_value
        audit[f"recomputed_{key}"] = recomputed_value
        both_missing = pd.isna(result_value) and pd.isna(recomputed_value)
        if not both_missing and result_value != recomputed_value:
            mismatches.append(key)

    for key in _TEXT_AUDIT_FIELDS:
        result_value = _normalized_text(row.get(key))
        recomputed_value = _normalized_text(traits.get(key))
        audit[f"result_{key}"] = result_value
        audit[f"recomputed_{key}"] = recomputed_value
        if result_value != recomputed_value:
            mismatches.append(key)

    audit["matches_final_result"] = not mismatches
    audit["mismatch_fields"] = ";".join(mismatches)
    return audit


def _target_key(row: pd.Series) -> str:
    return f"{_identifier(row['row'])}/{row['plot']}"


def _select_rows(results: pd.DataFrame, targets: Iterable[str] | None) -> pd.DataFrame:
    required = {
        "date",
        "scan_id",
        "row",
        "plot",
        *_FLOAT_AUDIT_FIELDS,
        *_INTEGER_AUDIT_FIELDS,
        *_TEXT_AUDIT_FIELDS,
    }
    missing = sorted(required.difference(results.columns))
    if missing:
        raise ValueError(f"Results CSV is missing required column(s): {missing}")

    requested = set(targets or [])
    if not requested:
        return results.copy()
    keys = results.apply(_target_key, axis=1)
    unknown = sorted(requested.difference(set(keys)))
    if unknown:
        raise ValueError(f"Requested target(s) not present in results: {unknown}")
    return results.loc[keys.isin(requested)].copy()


def _plot_points(points: pd.DataFrame, max_points: int) -> tuple[np.ndarray, ...]:
    x_m = pd.to_numeric(points["X"], errors="coerce").to_numpy(dtype=float) / 1000.0
    y_m = pd.to_numeric(points["Y"], errors="coerce").to_numpy(dtype=float) / 1000.0
    z_m = pd.to_numeric(points["Z"], errors="coerce").to_numpy(dtype=float) / 1000.0
    if "height_agl" in points.columns:
        height_m = (
            pd.to_numeric(points["height_agl"], errors="coerce").to_numpy(dtype=float)
            / 1000.0
        )
    else:
        finite_y = y_m[np.isfinite(y_m)]
        ground_m = float(np.quantile(finite_y, 0.05)) if finite_y.size else 0.0
        height_m = y_m - ground_m

    finite = np.isfinite(x_m) & np.isfinite(z_m) & np.isfinite(height_m)
    x_m, z_m, height_m = x_m[finite], z_m[finite], height_m[finite]
    if not x_m.size:
        raise ValueError("Point cloud has no finite X/Z/height values for review")
    if x_m.size > max_points:
        indices = np.linspace(0, x_m.size - 1, max_points, dtype=np.int64)
        x_m, z_m, height_m = x_m[indices], z_m[indices], height_m[indices]
    return x_m, z_m, height_m


def _render_review(
    reviewed: list[tuple[pd.Series, pd.DataFrame, dict[str, Any], dict[str, Any]]],
    output_path: Path,
    *,
    max_points: int,
) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Circle
    except ImportError as exc:
        raise RuntimeError(
            "Geometry review rendering requires matplotlib; install the repository's "
            "optional plotting dependency first"
        ) from exc

    figure, axes = plt.subplots(
        len(reviewed),
        3,
        figsize=(19.0, max(4.2 * len(reviewed), 5.0)),
        squeeze=False,
    )
    for target_index, (row, points, traits, diagnostics) in enumerate(reviewed):
        x_m, z_m, height_m = _plot_points(points, max_points)
        plan_ax, x_height_ax, z_height_ax = axes[target_index]
        scatter_kwargs = {
            "c": height_m,
            "cmap": "viridis",
            "s": 2.0,
            "alpha": 0.45,
            "linewidths": 0.0,
            "rasterized": True,
        }

        plan_ax.scatter(x_m, z_m, **scatter_kwargs)
        center_x = float(diagnostics["crown_center_x_m"])
        center_z = float(diagnostics["crown_center_z_m"])
        radius = float(diagnostics["maximum_crown_radius_m"])
        plan_ax.add_patch(Circle((center_x, center_z), radius, fill=False, color="red", lw=1.5))
        plan_ax.scatter([center_x], [center_z], marker="x", color="red", s=45, linewidths=1.5)
        for key in ("target_z_min_m", "target_z_max_m"):
            boundary = _optional_float(row, key)
            if boundary is not None:
                plan_ax.axhline(boundary, color="black", ls=":", lw=0.8, alpha=0.65)
        plan_ax.set_xlabel("X across row (m)")
        plan_ax.set_ylabel("Z travel direction (m)")
        plan_ax.set_aspect("equal", adjustable="box")
        plan_ax.set_title(
            f"{row['date']} row {_identifier(row['row'])} {row['plot']}\n"
            f"QC={traits['geometry_qc_status']}, height={traits['plant_height_m']:.3f} m, "
            f"footprint={traits['footprint_area_m2']:.4f} m², "
            f"cells={int(traits['geometry_footprint_cells'])}"
        )

        x_height_ax.scatter(x_m, height_m, **scatter_kwargs)
        z_height_ax.scatter(z_m, height_m, **scatter_kwargs)
        for axis, horizontal_label in (
            (x_height_ax, "X across row (m)"),
            (z_height_ax, "Z travel direction (m)"),
        ):
            axis.axhline(float(traits["plant_height_m"]), color="red", lw=1.2)
            axis.set_xlabel(horizontal_label)
            axis.set_ylabel("Height above ground (m)")
            axis.grid(True, alpha=0.20)
        x_height_ax.set_title("X-height side projection")
        z_height_ax.set_title(
            "Z-height side projection\n"
            f"envelope={traits['canopy_envelope_volume_m3']:.6f} m³, "
            f"occupied={traits['canopy_occupied_volume_m3']:.6f} m³"
        )

    figure.suptitle("Exact-marker Meadow Fescue geometry review", fontsize=15)
    figure.tight_layout(rect=(0.0, 0.0, 1.0, 0.995))
    figure.savefig(output_path, dpi=160, bbox_inches="tight")
    plt.close(figure)


def build_geometry_review(
    *,
    results_path: Path,
    pointcloud_dir: Path,
    config_path: Path,
    output_dir: Path,
    targets: Iterable[str] | None = None,
    max_points: int = 30_000,
    tolerance: float = 1e-9,
    allow_mismatch: bool = False,
) -> tuple[Path, Path]:
    results_path = results_path.resolve()
    pointcloud_dir = pointcloud_dir.resolve()
    config_path = config_path.resolve()
    output_dir = output_dir.resolve()
    if not results_path.is_file():
        raise FileNotFoundError(f"Missing results CSV: {results_path}")
    if not pointcloud_dir.is_dir():
        raise FileNotFoundError(f"Missing point-cloud directory: {pointcloud_dir}")
    if not config_path.is_file():
        raise FileNotFoundError(f"Missing config YAML: {config_path}")
    if output_dir == pointcloud_dir or pointcloud_dir in output_dir.parents:
        raise ValueError("Review output directory must be outside the point-cloud input directory")
    if max_points < 100:
        raise ValueError("max_points must be at least 100")

    operation = _load_geometry_config(config_path)
    rows = _select_rows(pd.read_csv(results_path), targets)
    if rows.empty:
        raise ValueError("No result rows selected for geometry review")

    reviewed: list[tuple[pd.Series, pd.DataFrame, dict[str, Any], dict[str, Any]]] = []
    audits: list[dict[str, Any]] = []
    for _, row in rows.iterrows():
        pointcloud_path = _pointcloud_path(pointcloud_dir, row)
        points = pd.read_csv(pointcloud_path)
        traits, diagnostics = compute_plant_geometry_traits(
            points,
            operation,
            context=_geometry_context(row),
        )
        audit = _audit_target(row, traits, diagnostics, tolerance=tolerance)
        audit["pointcloud_path"] = str(pointcloud_path)
        audits.append(audit)
        reviewed.append((row, points, traits, diagnostics))

    output_dir.mkdir(parents=True, exist_ok=True)
    audit_path = output_dir / f"{results_path.stem}_geometry_review_audit.csv"
    image_path = output_dir / f"{results_path.stem}_geometry_review.png"
    audit_frame = pd.DataFrame(audits)
    audit_frame.to_csv(audit_path, index=False)

    mismatched = audit_frame.loc[~audit_frame["matches_final_result"]]
    if not mismatched.empty and not allow_mismatch:
        details = ", ".join(
            f"{entry['row']}/{entry['plot']} ({entry['mismatch_fields']})"
            for _, entry in mismatched.iterrows()
        )
        raise ValueError(
            "Review recomputation does not match the final results; montage was not written. "
            f"Inspect {audit_path}. Mismatches: {details}"
        )

    _render_review(reviewed, image_path, max_points=max_points)
    return image_path, audit_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Recompute Meadow Fescue geometry using exact result-row marker bounds, "
            "audit it against the final CSV, and render a review montage."
        )
    )
    parser.add_argument("--results", required=True)
    parser.add_argument("--pointcloud-dir", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--target",
        action="append",
        default=[],
        help="Optional ROW/PLOT target such as 38/plant_2; repeat as needed",
    )
    parser.add_argument("--max-points", type=int, default=30_000)
    parser.add_argument("--tolerance", type=float, default=1e-9)
    parser.add_argument(
        "--allow-mismatch",
        action="store_true",
        help="Render even when recomputed metrics do not match the final result row",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    image_path, audit_path = build_geometry_review(
        results_path=Path(args.results),
        pointcloud_dir=Path(args.pointcloud_dir),
        config_path=Path(args.config),
        output_dir=Path(args.output_dir),
        targets=args.target,
        max_points=args.max_points,
        tolerance=args.tolerance,
        allow_mismatch=bool(args.allow_mismatch),
    )
    print(f"review_image={image_path}")
    print(f"review_audit={audit_path}")


if __name__ == "__main__":
    main()
