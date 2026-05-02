import csv
from pathlib import Path


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    marker_dir = repo / "lidar_analysis" / "example_data" / "2026_04_28_1" / "markers"
    marker_files = sorted(marker_dir.glob("*.csv"))
    if not marker_files:
        raise SystemExit("No marker CSV found")
    marker_path = marker_files[0]
    rows = []
    with marker_path.open("r", newline="") as f:
        for r in csv.DictReader(f):
            if r.get("target_type", "").strip().lower() == "plant" and r.get("mark_role", "").strip().lower() == "center":
                rows.append(r)
    print(f"marker_file={marker_path}")
    print(f"plant_centers={len(rows)}")

    m_per_click = 0.000531
    lidar_wheel_offset_m = 0.0
    plant_marker_buffer_u = 0.25
    for r in rows:
        enc = float(r["encoder_count"])
        marker_z_m = max(0.0, enc * m_per_click - lidar_wheel_offset_m)
        z_min = marker_z_m - plant_marker_buffer_u
        z_max = marker_z_m + plant_marker_buffer_u
        print(f"plant {r['target_number']}: {z_min:.3f}m -> {z_max:.3f}m")

    if len(rows) != 3:
        raise SystemExit(f"Expected exactly three plant center markers, found {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
