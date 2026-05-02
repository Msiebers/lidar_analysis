# cpp_ops

Phase 1 scaffold for PCL-backed point cloud operations.

Python remains the field-specific controller. This executable is intended for heavier point-cloud operations that can be run in batches from a manifest.

## Build

```bash
sudo apt install libpcl-dev
cmake -S cpp_ops -B cpp_ops/build
cmake --build cpp_ops/build -j
