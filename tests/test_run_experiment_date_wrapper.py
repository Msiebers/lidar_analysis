import inspect
import sys

from lidar_analysis import central_runner, run_experiment_date

def test_wrapper_thin():
    src = inspect.getsource(run_experiment_date.call_runner)
    assert 'central_runner' in src


def test_processing_cli_has_no_config_overrides(monkeypatch):
    argv = [
        "run", "--experiment", "exp", "--date", "2026_07_01",
        "--input", "/input", "--working", "/work", "--output", "/output",
    ]
    for module in (run_experiment_date, central_runner):
        monkeypatch.setattr(sys, "argv", argv)
        args = module.parse_args()
        assert not hasattr(args, "fusion")
        assert not hasattr(args, "force")
        assert not hasattr(args, "cart_id")
