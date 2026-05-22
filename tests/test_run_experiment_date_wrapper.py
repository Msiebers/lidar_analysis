import inspect
from lidar_analysis import run_experiment_date

def test_wrapper_thin():
    src = inspect.getsource(run_experiment_date.call_runner)
    assert 'central_runner' in src
