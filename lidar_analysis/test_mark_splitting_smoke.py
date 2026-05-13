#!/usr/bin/env python3
from pathlib import Path
import tempfile

from lidar_analysis.mark_splitting import build_mark_segments


def write_csv(path: Path, text: str) -> None:
    path.write_text(text, encoding='utf-8')


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)

        # 1/2 free mark => plant 1 with buffer window
        p1 = d / 'free1.csv'
        write_csv(p1, 'marker_idx,target_type,target_number,mark_role,encoder_count,time_s\n1,free,,mark,500,1.0\n')
        segs = build_mark_segments(p1, step_mm=1.0, lidar_wheel_offset_mm=0.0, z_buffer_mm=100.0, target_type='plant', free_marks_as='plant')
        assert len(segs) == 1
        assert segs[0].target_number == '1'
        assert segs[0].label == 'plant_1'

        # 3 multiple free marks => sequential plants
        p2 = d / 'free3.csv'
        write_csv(p2, 'marker_idx,target_type,target_number,mark_role,encoder_count,time_s\n1,free,,mark,100,1.0\n2,free,,mark,200,2.0\n3,free,,mark,300,3.0\n')
        segs = build_mark_segments(p2, step_mm=1.0, lidar_wheel_offset_mm=0.0, z_buffer_mm=10.0, target_type='plant', free_marks_as='plant')
        assert [s.target_number for s in segs] == ['1', '2', '3']

        # 4 empty file no crash
        p3 = d / 'empty.csv'
        p3.write_text('', encoding='utf-8')
        segs = build_mark_segments(p3, step_mm=1.0, lidar_wheel_offset_mm=0.0, z_buffer_mm=10.0, target_type='plant', free_marks_as='plant')
        assert segs == []

        # 5 existing start/stop still works
        p4 = d / 'start_stop.csv'
        write_csv(p4, 'marker_idx,target_type,target_number,mark_role,encoder_count,time_s\n1,plant,7,start,100,1.0\n2,plant,7,stop,300,2.0\n')
        segs = build_mark_segments(p4, step_mm=1.0, lidar_wheel_offset_mm=0.0, z_buffer_mm=10.0, target_type='plant', free_marks_as='none')
        assert len(segs) == 1
        assert segs[0].target_number == '7'

    print('PASS')


if __name__ == '__main__':
    main()
