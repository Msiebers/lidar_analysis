from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd


REQUIRED_POINT_COLUMNS = ("X", "Y", "Z", "RSSI")


@dataclass
class AnalysisTarget:
    target_id: str
    target_type: str
    scan_id: str

    row: str | None = None
    plot: str | None = None
    plant: str | None = None
    side: str | None = None

    source_indices: np.ndarray = field(default_factory=lambda: np.empty((0,), dtype=np.int32))

    # raw_points: target cloud immediately after reconstruction/masking/splitting.
    # This should not be modified by pointcloud ops.
    raw_points: pd.DataFrame = field(
        default_factory=lambda: pd.DataFrame(columns=list(REQUIRED_POINT_COLUMNS))
    )

    # current_points: active cloud used by pointcloud ops and point-cloud traits.
    current_points: pd.DataFrame = field(
        default_factory=lambda: pd.DataFrame(columns=list(REQUIRED_POINT_COLUMNS))
    )

    traits: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    op_history: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.source_indices = np.asarray(self.source_indices)

        self._validate_points(self.raw_points, "raw_points")
        self._validate_points(self.current_points, "current_points")

    @staticmethod
    def _validate_points(points: pd.DataFrame, label: str) -> None:
        missing = [c for c in REQUIRED_POINT_COLUMNS if c not in points.columns]
        if missing:
            raise ValueError(
                f"AnalysisTarget.{label} is missing required columns {missing}. "
                f"Available columns: {list(points.columns)}"
            )

    @property
    def scalar_columns(self) -> list[str]:
        return [c for c in self.current_points.columns if c not in {"X", "Y", "Z"}]

    @classmethod
    def from_points(
        cls,
        *,
        target_id: str,
        target_type: str,
        scan_id: str,
        points_df: pd.DataFrame,
        source_indices: np.ndarray,
        row: str | None = None,
        plot: str | None = None,
        plant: str | None = None,
        side: str | None = None,
    ) -> "AnalysisTarget":
        raw = points_df.copy(deep=True)

        return cls(
            target_id=target_id,
            target_type=target_type,
            scan_id=scan_id,
            row=row,
            plot=plot,
            plant=plant,
            side=side,
            source_indices=np.asarray(source_indices),
            raw_points=raw,
            current_points=raw.copy(deep=True),
        )