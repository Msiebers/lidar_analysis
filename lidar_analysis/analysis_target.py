from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import numpy as np
import pandas as pd


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
    raw_points: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=["X","Y","Z","RSSI"]))
    current_points: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=["X","Y","Z","RSSI"]))
    traits: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    op_history: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_points(cls, *, target_id: str, target_type: str, scan_id: str, points_df: pd.DataFrame, source_indices: np.ndarray, row: str | None=None, plot: str | None=None, side: str | None=None) -> "AnalysisTarget":
        raw = points_df.copy()
        return cls(
            target_id=target_id,
            target_type=target_type,
            scan_id=scan_id,
            row=row,
            plot=plot,
            side=side,
            source_indices=np.asarray(source_indices),
            raw_points=raw,
            current_points=raw.copy(),
        )
