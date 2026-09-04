import csv
from concurrent.futures import ThreadPoolExecutor

import pytest

from lidar_analysis import central_runner
from lidar_analysis.config import AnalysisConfig
from lidar_analysis.pipeline_core import Plot, _apply_additional_scan_side_split, _fad_x_bounds_for_plot


def _inputs(tmp_path, scan_ids=("001", "002", "003")):
    input_dir = tmp_path / "input"
    input_dir.mkdir(parents=True)
    (input_dir / "cart_config.yaml").write_text(
        "cart_id: test\nm_per_click: 0.001\nlidar_height_m: 1.0\n",
        encoding="utf-8",
    )
    for scan_id in scan_ids:
        (input_dir / f"{scan_id}_lidar.csv").write_text("", encoding="utf-8")
        (input_dir / f"{scan_id}_pico.csv").write_text("", encoding="utf-8")
    return input_dir


def _run(tmp_path, parallel_scans, monkeypatch, process_scan, experiment_analysis=None):
    input_dir = _inputs(tmp_path)
    output_dir = tmp_path / "output"
    monkeypatch.setattr(central_runner.pipeline_core, "process_scan", process_scan)
    return central_runner.run_experiment_date(
        experiment="exp",
        date_name="2026_08_26",
        input_dir=input_dir,
        working_dir=tmp_path / "work",
        output_dir=output_dir,
        experiment_config={"processing": {"parallel_scans": parallel_scans}},
        experiment_analysis=experiment_analysis or {},
    ), output_dir


def _rows(scan_base, **_kwargs):
    return [{"scan_name": scan_base, "row": "r", "plot": "1", "side": "none",
             "target_type": "plot", "target_id": "r_1", "points": 1}]


def _additional_target_rows(scan_base, **_kwargs):
    cfg = AnalysisConfig(data_dirs=[], calibration_dir=None, cart_id="test")
    cfg.additional_scan_side_split = True
    cfg.additional_scan_positive_side_label = "right"
    cfg.additional_scan_negative_side_label = "left"
    plots = [
        Plot("scan", str(number), bounds, ".", scan_base=f"scan_{scan_base}")
        for number, bounds in ((1, (10.0, 90.0)), (2, (210.0, 290.0)))
    ]
    for plot in plots:
        plot.split_source = "marks"
        plot.target_type = "plot"
        plot.target_number = plot.letter
    targets = _apply_additional_scan_side_split(plots, f"scan_{scan_base}", cfg)
    rows = []
    for target in targets:
        x_min, x_max = _fad_x_bounds_for_plot(target, ["scan", "scan"], 1.5)
        rows.append({
            "scan_name": scan_base,
            "row": target.side_label,
            "side": target.side_label,
            "plot": target.letter,
            "target_type": "plot",
            "target_id": f"plot_{target.letter}",
            "plot_length_m": (target.max_z - target.min_z) / 1000.0,
            "fad_x_min_m": x_min,
            "fad_x_max_m": x_max,
            "pai_pad_m2_m3": 1.25,
            "pai_m2_m2": 0.5,
            "points": 1,
        })
    return rows


def test_parallel_scans_validation():
    assert central_runner.resolve_parallel_scans({"processing": {"parallel_scans": None}}) is None
    assert central_runner.resolve_parallel_scans({"processing": {"parallel_scans": 2}}) == 2
    assert central_runner.resolve_parallel_scans({"processing": {"parallel_scans": 4}}) == 4
    with pytest.raises(ValueError):
        central_runner.resolve_parallel_scans({"processing": []})
    for value in (0, -1, True, 2.5, "2"):
        with pytest.raises(ValueError):
            central_runner.resolve_parallel_scans({"processing": {"parallel_scans": value}})


def test_null_runs_sequentially_and_records_completion(tmp_path, monkeypatch):
    calls = []

    def process_scan(scan_base, **kwargs):
        calls.append(scan_base)
        return _rows(scan_base, **kwargs)

    monkeypatch.setattr(
        central_runner,
        "ProcessPoolExecutor",
        lambda **_kwargs: pytest.fail("sequential mode created an executor"),
    )
    results, output = _run(tmp_path, None, monkeypatch, process_scan)

    assert calls == ["001", "002", "003"]
    assert (output / "completed_scans.txt").read_text(encoding="utf-8").splitlines() == calls
    with open(results, newline="", encoding="utf-8") as f:
        assert [row["scan_name"] for row in csv.DictReader(f)] == calls


def test_parallel_two_has_no_duplicate_rows_and_skips_completed(tmp_path, monkeypatch):
    worker_counts = []

    class Executor(ThreadPoolExecutor):
        def __init__(self, max_workers):
            worker_counts.append(max_workers)
            super().__init__(max_workers=max_workers)

    monkeypatch.setattr(central_runner, "ProcessPoolExecutor", Executor)
    results, output = _run(tmp_path, 2, monkeypatch, _rows)

    with open(results, newline="", encoding="utf-8") as f:
        first = list(csv.DictReader(f))
    assert worker_counts == [2]
    assert [row["scan_name"] for row in first] == ["001", "002", "003"]
    assert (output / "completed_scans.txt").read_text(encoding="utf-8").splitlines() == ["001", "002", "003"]

    central_runner.run_experiment_date(
        experiment="exp",
        date_name="2026_08_26",
        input_dir=tmp_path / "input",
        working_dir=tmp_path / "work",
        output_dir=output,
        experiment_config={"processing": {"parallel_scans": 2}},
        experiment_analysis={},
    )
    with open(results, newline="", encoding="utf-8") as f:
        assert list(csv.DictReader(f)) == first


def test_parallel_failure_preserves_successful_scans(tmp_path, monkeypatch):
    class Executor(ThreadPoolExecutor):
        pass

    def process_scan(scan_base, **kwargs):
        if scan_base == "002":
            raise RuntimeError("broken scan")
        return _rows(scan_base, **kwargs)

    monkeypatch.setattr(central_runner, "ProcessPoolExecutor", Executor)
    with pytest.raises(RuntimeError, match="002"):
        results, output = _run(tmp_path, 2, monkeypatch, process_scan)

    output = tmp_path / "output"
    with open(output / "results.csv", newline="", encoding="utf-8") as f:
        assert [row["scan_name"] for row in csv.DictReader(f)] == ["001", "003"]
    assert (output / "completed_scans.txt").read_text(encoding="utf-8").splitlines() == ["001", "003"]


def test_additional_target_identity_matches_sequential_and_parallel(tmp_path, monkeypatch):
    analysis = {"run_fad": True, "run_pai": True, "pai_run_layers": False}
    _, sequential_output = _run(
        tmp_path / "sequential", None, monkeypatch, _additional_target_rows, analysis
    )

    class Executor(ThreadPoolExecutor):
        pass

    monkeypatch.setattr(central_runner, "ProcessPoolExecutor", Executor)
    _, parallel_output = _run(
        tmp_path / "parallel", 2, monkeypatch, _additional_target_rows, analysis
    )

    def identities(output):
        with open(output / "results.csv", newline="", encoding="utf-8") as f:
            return [
                (
                    row["scan_name"], row["side"], row["plot"], row["plot_length_m"],
                    row["fad_x_min_m"], row["fad_x_max_m"], row["pai_m2_m2"],
                )
                for row in csv.DictReader(f)
            ]

    expected = [
        (scan, side, plot, "0.08", x_min, x_max, "0.50")
        for scan in ("001", "002", "003")
        for side, plot, x_min, x_max in (
            ("left", "1", "-1.50", "-0.00"),
            ("right", "1", "0.00", "1.50"),
            ("left", "2", "-1.50", "-0.00"),
            ("right", "2", "0.00", "1.50"),
        )
    ]
    assert identities(sequential_output) == expected
    assert identities(parallel_output) == expected


def test_mta_diagnostics_are_single_opt_in_file_and_do_not_change_main_results(
    tmp_path, monkeypatch, capsys,
):
    def rows(scan_base, cfg, **_kwargs):
        records = []
        for plot, side, value in (("1", "left", 41.0), ("2", "right", 52.0), ("3", "left", 63.0)):
            record = {
                "scan_name": scan_base, "plot": plot, "side": side,
                "target_type": "plot", "target_id": f"plot_{plot}_{side}",
                "mta_deg": value, "mta_method": "bounded_lang_v1",
                "mta_qc_pass": True, "mta_status": "ok", "points": 1,
            }
            if cfg.mta_diagnostic:
                record["_mta_diagnostics"] = [{
                    "mta_direction_group": "all", "mta_bin_role": "fit",
                    "mta_bin_lower_deg": 25.0, "mta_bin_upper_deg": 30.0,
                    "mta_bin_used_for_fit": True,
                }]
            records.append(record)
        return records

    off_results, off_output = _run(
        tmp_path / "off", None, monkeypatch, rows,
        {"run_mta": True, "mta_diagnostic": False},
    )
    on_results, on_output = _run(
        tmp_path / "on", None, monkeypatch, rows,
        {"run_mta": True, "mta_diagnostic": True},
    )
    assert not (off_output / "mta_diagnostics.csv").exists()
    assert [path.name for path in on_output.glob("*mta*.csv")] == ["mta_diagnostics.csv"]

    with open(off_results, newline="", encoding="utf-8") as f:
        off_reader = csv.DictReader(f)
        off_rows = list(off_reader)
    with open(on_results, newline="", encoding="utf-8") as f:
        on_reader = csv.DictReader(f)
        on_rows = list(on_reader)
    assert off_reader.fieldnames == on_reader.fieldnames
    assert [name for name in off_reader.fieldnames if name.startswith("mta_")] == ["mta_deg", "mta_qc_pass"]
    expected = [
        (scan, plot, side, value)
        for scan in ("001", "002", "003")
        for plot, side, value in (("1", "left", "41.00"), ("2", "right", "52.00"), ("3", "left", "63.00"))
    ]
    assert [(row["scan_name"], row["plot"], row["side"], row["mta_deg"]) for row in off_rows] == expected
    assert [(row["scan_name"], row["plot"], row["side"], row["mta_deg"]) for row in on_rows] == expected
    assert {row["mta_qc_pass"] for row in off_rows + on_rows} == {"True"}
    with open(on_output / "mta_diagnostics.csv", newline="", encoding="utf-8") as f:
        diagnostic_rows = list(csv.DictReader(f))
    assert len(diagnostic_rows) == 9
    assert {"experiment", "date", "scan_name", "scan_number", "plot", "side"} <= set(diagnostic_rows[0])
    assert "[MTA" not in capsys.readouterr().out


def test_pai_layer_columns_go_to_results_when_enabled(tmp_path, monkeypatch):
    def rows(scan_base, cfg, **_kwargs):
        record = {
            "scan_name": scan_base, "plot": "1", "side": "left",
            "target_type": "plot", "target_id": "plot_1_left",
            "pai_m2_m2": 0.3, "pai_height_m": 1.0,
            "pai_layer_thickness_m": 0.5, "pai_n_layers": 2,
            "pai_pad_m2_m3": 99.0, "pai_whole_box_m2_m2": 88.0,
            "pai_n_rays_total": 10, "pai_n_rays_intersecting_box": 8,
            "pai_n_rays_observed": 6, "pai_n_hits": 2, "pai_n_full_gaps": 4,
            "pai_gap_fraction": 2 / 3, "pai_mean_chord_m": 0.7,
            "pai_median_chord_m": 0.6, "pai_log_likelihood": -4.0,
            "pai_g_function": "spherical", "pai_g_value": 0.5,
            "_pai_layers": [
                {"layer_bottom_m": 0.0, "layer_top_m": 0.5, "layer_mid_m": 0.25,
                 "layer_thickness_m": 0.5, "pad_layer_m2_m3": 0.2,
                 "pai_layer_m2_m2": 0.1},
                {"layer_bottom_m": 0.5, "layer_top_m": 1.0, "layer_mid_m": 0.75,
                 "layer_thickness_m": 0.5, "pad_layer_m2_m3": 0.4,
                 "pai_layer_m2_m2": 0.2},
            ],
        }
        if cfg.pai_include_layer_columns:
            record.update({
                "pai_layer_000_050_conditional_pai_m2_m2": 0.1,
                "pai_layer_050_100_conditional_pai_m2_m2": 0.2,
            })
        return [record]

    main, off = _run(tmp_path / "off", None, monkeypatch, rows, {"run_pai": True})
    _, layers = _run(
        tmp_path / "layers", None, monkeypatch, rows,
        {"run_pai": True, "pai_include_layer_columns": True},
    )
    _, diagnostics = _run(
        tmp_path / "diagnostics", None, monkeypatch, rows,
        {"run_pai": True, "pai_diagnostic": True},
    )

    with open(main, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        main_rows = list(reader)
    assert [name for name in reader.fieldnames if name.startswith("pai_")] == [
        "pai_m2_m2", "pai_height_m", "pai_layer_thickness_m", "pai_n_layers",
    ]
    assert all(row["pai_m2_m2"] == "0.30" for row in main_rows)
    assert not list(off.glob("pai_*.csv"))
    assert not (layers / "pai_layers.csv").exists()
    assert not (layers / "pai_diagnostics.csv").exists()
    assert (diagnostics / "pai_diagnostics.csv").exists()
    assert not (diagnostics / "pai_layers.csv").exists()

    with open(layers / "results.csv", newline="", encoding="utf-8") as f:
        layer_reader = csv.DictReader(f)
        layer_rows = list(layer_reader)
    assert len(layer_rows) == 3
    assert "pai_layer_000_050_conditional_pai_m2_m2" in layer_reader.fieldnames
    assert "pai_layer_050_100_conditional_pai_m2_m2" in layer_reader.fieldnames
    assert {row["pai_layer_000_050_conditional_pai_m2_m2"] for row in layer_rows} == {"0.10"}
    with open(diagnostics / "pai_diagnostics.csv", newline="", encoding="utf-8") as f:
        diagnostic_reader = csv.DictReader(f)
        diagnostic_rows = list(diagnostic_reader)
    assert len(diagnostic_rows) == 6
    assert "pad_layer_m2_m3" in diagnostic_reader.fieldnames
    assert "whole_box_pai_m2_m2" in diagnostic_reader.fieldnames


def test_pai_diagnostics_write_whole_box_rows_without_layers(tmp_path, monkeypatch):
    def rows(scan_base, cfg, **_kwargs):
        return [{
            "scan_name": scan_base, "plot": "1", "side": "left",
            "target_type": "plot", "target_id": "plot_1_left",
            "pai_m2_m2": 0.3, "pai_height_m": 1.0,
            "pai_layer_thickness_m": 0.5, "pai_n_layers": 0,
            "pai_whole_box_pad_m2_m3": 0.3, "pai_whole_box_m2_m2": 0.3,
            "pai_n_rays_total": 10, "pai_n_rays_intersecting_box": 8,
            "pai_n_rays_observed": 6, "pai_n_hits": 2, "pai_n_full_gaps": 4,
            "pai_gap_fraction": 2 / 3, "pai_mean_chord_m": 0.7,
            "pai_median_chord_m": 0.6, "pai_log_likelihood": -4.0,
            "pai_g_function": "spherical", "pai_g_value": 0.5,
        }]

    _, output = _run(
        tmp_path / "diagnostics_no_layers", None, monkeypatch, rows,
        {"run_pai": True, "pai_diagnostic": True},
    )

    with open(output / "pai_diagnostics.csv", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) == 3
    assert "whole_box_pai_m2_m2" in reader.fieldnames
    assert "layer_bottom_m" not in reader.fieldnames
    assert [row["scan_name"] for row in rows] == ["001", "002", "003"]


def test_pai_output_rejects_inconsistent_layer_arithmetic(tmp_path):
    cfg = AnalysisConfig(
        data_dirs=[], calibration_dir=tmp_path, cart_id="test",
        run_pai=True, pai_include_layer_columns=True,
    )
    rec = {
        "scan_name": "scan_001", "plot": "1", "side": "left",
        "pai_m2_m2": 0.1,
        "_pai_layers": [{
            "layer_bottom_m": 0.0, "layer_top_m": 0.5, "layer_mid_m": 0.25,
            "layer_thickness_m": 0.5, "pad_layer_m2_m3": 0.2,
            "pai_layer_m2_m2": 0.1,
        }],
    }
    with pytest.raises(AssertionError, match="Total PAI"):
        central_runner.append_pai_outputs(
            tmp_path / "layers.csv", tmp_path / "diagnostics.csv",
            "exp", "2026_08_26", "scan_001", [rec | {"pai_m2_m2": 0.2}], cfg,
        )
    with pytest.raises(AssertionError, match="Layer PAI"):
        central_runner.append_pai_outputs(
            tmp_path / "layers.csv", tmp_path / "diagnostics.csv",
            "exp", "2026_08_26", "scan_001",
            [rec | {"_pai_layers": [rec["_pai_layers"][0] | {"pad_layer_m2_m3": 0.4}]}], cfg,
        )


def test_true_duplicate_result_identity_raises(tmp_path):
    cfg = AnalysisConfig(data_dirs=[], calibration_dir=tmp_path, cart_id="test")
    path = tmp_path / "results.csv"
    central_runner.ensure_results_csv(path, cfg)
    duplicate = {
        "scan_name": "scan_003", "plot": "3", "side": "left",
        "target_type": "plot", "target_id": "plot_3_left", "points": 1,
    }
    with pytest.raises(ValueError, match="Duplicate result identity"):
        central_runner.append_trait_rows(
            path, "exp", "2026_08_26", "scan_003",
            [duplicate, duplicate | {"target_id": "different_internal_id"}], cfg,
        )
