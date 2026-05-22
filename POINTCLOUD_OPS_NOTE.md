# Pointcloud Ops Runtime Note

- `lidar_analysis.pointcloud_ops.apply_pointcloud_ops(...)` is now the active pointcloud-ops entrypoint.
- It runs per split target in `pipeline_core.analyze_plot(...)`, after splitting/masking and before trait calculation.
- Supported ops: `bilateral_scalar_filter`, `scalar_range_filter`, `sor_filter`, `voxel_volume`/`voxel_grid`/`voxel_count`.
- Ops are applied in exact YAML order from `analysis.pointcloud_ops`.
- Backend selection is routed through a Python interface (`scipy`, `pcl`, `pclpy`, `python_pcl` names accepted). In this step, the active implementation is Python/SciPy.
- No standalone `cpp_ops/build` executable is required by the runtime pipeline.
- Golden comparison flow: run the pipeline on the fixture and compare produced counts/summary rows against saved expected artifacts (without invoking old C++ binaries).
