from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

try:
    from .config import AnalysisConfig
    from . import pipeline_core
except Exception:
    from config import AnalysisConfig
    import pipeline_core


@dataclass
class StageContext:
    experiment: str
    date_name: str
    date_dir: Path
    output_dir: Path
    cfg: AnalysisConfig
    calibration: dict
    width_mm: float
    start_mm_global: float
    y_max_mm: float | None
    end_buffer_mm: float
    x_min_mm: float | None
    min_radius_mm: float | None


@dataclass
class ScanResult:
    scan_id: str
    trait_rows: list[dict]


class ScanStage(Protocol):
    name: str

    def run(self, context: StageContext, scan_id: str, lidar_fp: Path, pico_fp: Path) -> ScanResult:
        ...


class ProcessScanStage:
    name = "process_scan"

    def run(self, context: StageContext, scan_id: str, lidar_fp: Path, pico_fp: Path) -> ScanResult:
        recs = pipeline_core.process_scan(
            scan_base=scan_id,
            lidar_path=str(lidar_fp),
            pico_path=str(pico_fp),
            out_dir=str(context.output_dir / "pointclouds"),
            cfg=context.cfg,
            width_mm=context.width_mm,
            start_mm_global=context.start_mm_global,
            end_buffer_mm=context.end_buffer_mm,
            y_max_mm=context.y_max_mm,
            x_min_mm=context.x_min_mm,
            min_radius_mm=context.min_radius_mm,
            step_mm=context.calibration["step_mm"],
            lidar_height_mm=context.calibration["lidar_height_mm"],
            lidar_wheel_offset_mm=context.calibration["lidar_wheel_offset_mm"],
            roll_offset=context.calibration["roll_offset_deg"],
            pitch_offset=context.calibration["pitch_offset_deg"],
            imu_offset_mm=np.asarray(context.calibration["imu_offset_mm"], dtype=float),
        )
        return ScanResult(scan_id=scan_id, trait_rows=recs or [])


DEFAULT_STAGES: list[ScanStage] = [ProcessScanStage()]
