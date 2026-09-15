from lidar_analysis import central_watcher


def test_output_completion_respects_pointcloud_setting(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (tmp_path / "results.csv").write_text("result\n", encoding="utf-8")
    config = source / "experiment_config.yaml"

    config.write_text("analysis:\n  generate_pointclouds: false\n", encoding="utf-8")
    assert central_watcher.local_output_complete(tmp_path)

    config.write_text("analysis:\n  generate_pointclouds: true\n", encoding="utf-8")
    assert not central_watcher.local_output_complete(tmp_path)

    pointclouds = tmp_path / "pointclouds"
    pointclouds.mkdir()
    (pointclouds / "scan.ply").write_text("ply\n", encoding="utf-8")
    assert central_watcher.local_output_complete(tmp_path)
