Tiny three-plant marker fixture.

This fixture is cropped/downsampled from a real scan and is intended for Codex/developer tests.

Files:
- lidar.csv: downsampled LiDAR CSV
- pico.csv: cropped Pico CSV
- markers/marker.csv: three plant center markers

Marker CSV schema:
marker_idx,target_type,target_number,mark_role,encoder_count,time_s

Expected markers:
1. plant 1 center
2. plant 2 center
3. plant 3 center

This fixture is not intended for biological analysis. It is only for testing marker-aware splitting and basic pipeline execution.
