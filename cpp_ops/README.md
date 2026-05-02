# cpp_ops (Phase 1 scaffold)

Build:

```bash
sudo apt install libpcl-dev
cmake -S cpp_ops -B cpp_ops/build
cmake --build cpp_ops/build -j
```

Executable:
- `cpp_ops/build/pcl_pointcloud_ops_batch`

Manifest format CSV:
`target_id,input_csv,output_csv,ops_config_json`

Phase 1 behavior:
- Reads manifest
- Copies each input CSV to output CSV (no-op)
- Preserves columns

Manual smoke test:

```bash
cat > /tmp/pcl_manifest.csv <<EOF
 target_id,input_csv,output_csv,ops_config_json
 demo,/path/in.csv,/path/out.csv,{"mode":"copy"}
EOF
cpp_ops/build/pcl_pointcloud_ops_batch /tmp/pcl_manifest.csv
```
