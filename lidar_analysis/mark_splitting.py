from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


_FT_TO_M = 0.3048


@dataclass(frozen=True)
class MarkSegment:
    target_type: str
    target_number: str
    label: str
    min_z: float
    max_z: float


def _to_m_units(value: float, dim_units: str) -> float:
    if str(dim_units).lower() == "m":
        return float(value)
    return float(value) * _FT_TO_M


def marker_buffer_mm(mark_z_buffer_u: float, dim_units: str) -> float:
    return _to_m_units(float(mark_z_buffer_u), dim_units) * 1000.0


def _clean_label(x) -> str:
    if pd.isna(x):
        return ""
    try:
        fx = float(x)
        if fx.is_integer():
            return str(int(fx))
    except Exception:
        pass
    return str(x).strip()


def marker_count_to_z_mm(
    encoder_count,
    step_mm: float,
    lidar_wheel_offset_mm: float,
) -> float:
    z = float(encoder_count) * float(step_mm) - float(lidar_wheel_offset_mm)
    return max(0.0, z)


def find_marker_file_for_scan(
    raw_dir: str | Path,
    scan_base: str,
    markers_dirname: str = "markers",
) -> Path | None:
    raw_dir = Path(raw_dir)
    search_dirs = [raw_dir / markers_dirname, raw_dir]

    exact_names = [
        f"{scan_base}_markers.csv",
        f"{scan_base}_marker.csv",
        f"{scan_base}.markers.csv",
        f"{scan_base}.marker.csv",
    ]

    for d in search_dirs:
        if not d.is_dir():
            continue
        for name in exact_names:
            p = d / name
            if p.is_file():
                return p

    candidates: list[Path] = []
    for d in search_dirs:
        if not d.is_dir():
            continue
        candidates.extend(sorted(d.glob(f"{scan_base}*marker*.csv")))
        candidates.extend(sorted(d.glob(f"{scan_base}*markers*.csv")))

    candidates = list(dict.fromkeys(candidates))

    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        raise ValueError(
            f"Multiple marker files matched {scan_base}: "
            + ", ".join(str(p) for p in candidates)
        )

    generic: list[Path] = []
    for d in search_dirs:
        if not d.is_dir():
            continue
        generic.extend(sorted(d.glob("*marker*.csv")))
        generic.extend(sorted(d.glob("*markers*.csv")))

    generic = list(dict.fromkeys(generic))

    if len(generic) == 1:
        return generic[0]
    if len(generic) > 1:
        raise ValueError(
            f"Could not choose marker file for {scan_base}. "
            f"Rename it to {scan_base}_markers.csv. Candidates: "
            + ", ".join(str(p) for p in generic)
        )

    return None


def _load_markers(marker_path: str | Path) -> pd.DataFrame:
    marker_path = Path(marker_path)
    df = pd.read_csv(marker_path)

    df = df.rename(columns={c: str(c).strip().lower() for c in df.columns})

    required = ["target_type", "target_number", "mark_role", "encoder_count"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"{marker_path} is missing required columns: {missing}")

    df["_target_type"] = df["target_type"].astype(str).str.strip().str.lower()
    df["_target_number"] = df["target_number"].apply(_clean_label)
    df["_mark_role"] = df["mark_role"].astype(str).str.strip().str.lower()
    df["_encoder_count"] = pd.to_numeric(df["encoder_count"], errors="coerce")

    if "marker_idx" in df.columns:
        df["_sort"] = pd.to_numeric(df["marker_idx"], errors="coerce")
    elif "time_s" in df.columns:
        df["_sort"] = pd.to_numeric(df["time_s"], errors="coerce")
    else:
        df["_sort"] = np.arange(len(df), dtype=float)

    df = df[np.isfinite(df["_encoder_count"])].copy()
    df = df[df["_target_number"] != ""].copy()
    df = df.sort_values("_sort").reset_index(drop=True)

    return df


def load_markers(marker_path: str | Path) -> pd.DataFrame:
    """Public marker loader for callers needing marker rows/metadata."""
    return _load_markers(marker_path)


def build_mark_segments(
    marker_path: str | Path,
    *,
    step_mm: float,
    lidar_wheel_offset_mm: float,
    z_buffer_mm: float,
    target_type: str = "auto",
    zmax_clip: float | None = None,
) -> list[MarkSegment]:
    df = _load_markers(marker_path)

    if df.empty:
        return []

    target_type = str(target_type).strip().lower()
    if target_type not in ("auto", "plot", "plant"):
        raise ValueError(f"Unknown mark_target_type={target_type!r}")

    if target_type != "auto":
        df = df[df["_target_type"] == target_type].copy()

    if df.empty:
        return []

    df["_z_mm"] = df["_encoder_count"].apply(
        lambda c: marker_count_to_z_mm(
            c,
            step_mm=step_mm,
            lidar_wheel_offset_mm=lidar_wheel_offset_mm,
        )
    )

    start_roles = {"start", "begin", "beg"}
    stop_roles = {"stop", "end", "finish"}
    center_roles = {"center", "mark", "point", "plant"}

    segments: list[MarkSegment] = []

    for (ttype, number), group in df.groupby(["_target_type", "_target_number"], sort=False):
        group = group.sort_values("_sort")

        pending_start: float | None = None
        made_pair = False

        for _, row in group.iterrows():
            role = str(row["_mark_role"])
            z = float(row["_z_mm"])

            if role in start_roles:
                pending_start = z
                continue

            if role in stop_roles and pending_start is not None:
                z1 = pending_start
                z2 = z

                lo = min(z1, z2) + float(z_buffer_mm)
                hi = max(z1, z2) - float(z_buffer_mm)

                lo = max(0.0, lo)
                if zmax_clip is not None:
                    hi = min(float(zmax_clip), hi)

                if hi > lo:
                    label = str(number) if ttype == "plot" else f"plant_{number}"
                    segments.append(
                        MarkSegment(
                            target_type=str(ttype),
                            target_number=str(number),
                            label=label,
                            min_z=lo,
                            max_z=hi,
                        )
                    )

                pending_start = None
                made_pair = True

        # If there was no usable start/stop pair, treat marks as center marks.
        # This is mainly for plant mode.
        if not made_pair:
            for _, row in group.iterrows():
                role = str(row["_mark_role"])
                if role in start_roles or role in stop_roles:
                    continue
                if role not in center_roles and str(ttype) == "plot":
                    continue

                center = float(row["_z_mm"])
                lo = max(0.0, center - float(z_buffer_mm))
                hi = center + float(z_buffer_mm)

                if zmax_clip is not None:
                    hi = min(float(zmax_clip), hi)

                if hi > lo:
                    label = str(number) if ttype == "plot" else f"plant_{number}"
                    segments.append(
                        MarkSegment(
                            target_type=str(ttype),
                            target_number=str(number),
                            label=label,
                            min_z=lo,
                            max_z=hi,
                        )
                    )

    return segments
