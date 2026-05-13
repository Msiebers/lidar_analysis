#!/usr/bin/env python3
from pathlib import Path
import tempfile
import csv

from lidar_analysis.pipeline_core import write_marker_reference_points


def read_rows(p: Path):
    with open(p, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        m1 = root / 'scan_001_markers.csv'
        m1.write_text('marker_idx,target_type,target_number,mark_role,encoder_count,time_s\n1,free,,mark,5004,6.139892\n', encoding='utf-8')
        write_marker_reference_points('scan_001', str(m1), str(root), step_mm=1.0, lidar_wheel_offset_mm=0.0)
        out = root / 'scan_001_marker_points.csv'
        rows = read_rows(out)
        assert len(rows) == 1
        assert set(['X','Y','Z','marker_idx','target_type','target_number','mark_role','encoder_count','time_s','scan_id']).issubset(rows[0].keys())

        m2 = root / 'scan_002_markers.csv'
        m2.write_text('marker_idx,target_type,target_number,mark_role,encoder_count,time_s\n1,free,,mark,100,1.0\n2,free,,mark,200,2.0\n', encoding='utf-8')
        write_marker_reference_points('scan_002', str(m2), str(root), step_mm=1.0, lidar_wheel_offset_mm=0.0)
        rows = read_rows(root / 'scan_002_marker_points.csv')
        assert len(rows) == 2

        m3 = root / 'scan_003_markers.csv'
        m3.write_text('', encoding='utf-8')
        write_marker_reference_points('scan_003', str(m3), str(root), step_mm=1.0, lidar_wheel_offset_mm=0.0)
        assert not (root / 'scan_003_marker_points.csv').exists()

    print('PASS')


if __name__ == '__main__':
    main()
