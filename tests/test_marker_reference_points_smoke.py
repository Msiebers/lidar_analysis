#!/usr/bin/env python3
from pathlib import Path
import tempfile
import csv

from lidar_analysis.config import AnalysisConfig
from lidar_analysis.pipeline_core import process_scan, write_marker_reference_points


def read_rows(p: Path):
    with open(p, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def test_marker_reference_points_smoke() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        m1 = root / 'scan_001_markers.csv'
        m1.write_text('marker_idx,target_type,target_number,mark_role,encoder_count,time_s\n1,free,,mark,5004,6.139892\n', encoding='utf-8')
        write_marker_reference_points('scan_001', str(m1), str(root), step_mm=1.0, lidar_wheel_offset_mm=0.0)
        out = root / 'scan_001_marker_points.csv'
        rows = read_rows(out)
        assert len(rows) == 1
        # Marker reference file is now exactly three columns: X, Y, Z.
        assert set(rows[0].keys()) == {'X', 'Y', 'Z'}

        m2 = root / 'scan_002_markers.csv'
        m2.write_text('marker_idx,target_type,target_number,mark_role,encoder_count,time_s\n1,free,,mark,100,1.0\n2,free,,mark,200,2.0\n', encoding='utf-8')
        write_marker_reference_points('scan_002', str(m2), str(root), step_mm=1.0, lidar_wheel_offset_mm=0.0)
        rows = read_rows(root / 'scan_002_marker_points.csv')
        assert len(rows) == 2

        m3 = root / 'scan_003_markers.csv'
        m3.write_text('', encoding='utf-8')
        write_marker_reference_points('scan_003', str(m3), str(root), step_mm=1.0, lidar_wheel_offset_mm=0.0)
        assert not (root / 'scan_003_marker_points.csv').exists()


def test_distance_splitting_still_writes_marker_reference_points() -> None:
    fixture = Path(__file__).parents[1] / 'lidar_analysis' / 'example_data' / '2026_04_28_1'
    scan = '2&1_1_20_multi02_2026_04_28_1_Vetch_PDS_2026'
    cfg = AnalysisConfig(
        data_dirs=[fixture], calibration_dir=fixture, cart_id='test',
        split_source='distance', split_u=None, make_point_cloud=False,
        write_reference_points=True, markers_dirname='markers',
        use_imu=False, fusion_method='interp',
    )

    with tempfile.TemporaryDirectory() as td:
        process_scan(
            scan_base=scan,
            lidar_path=str(fixture / f'{scan}_lidar.csv'),
            pico_path=str(fixture / f'{scan}_pico.csv'),
            out_dir=td, cfg=cfg,
            width_mm=5000.0, start_mm_global=0.0, end_buffer_mm=0.0,
            y_max_mm=None, x_min_mm=None, min_radius_mm=None,
            step_mm=1.0, lidar_height_mm=1000.0,
        )
        rows = read_rows(Path(td) / f'{scan}_marker_points.csv')
        assert len(rows) == 3


if __name__ == '__main__':
    test_marker_reference_points_smoke()
    print('PASS')
