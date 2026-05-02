from pathlib import Path
import csv
import datetime


def ensure_results_layout(experiment_dir: Path) -> dict:
    results_dir = experiment_dir / "results"
    pointcloud_dir = results_dir / "pointclouds"
    traits_dir = results_dir / "traits"
    state_dir = results_dir / "state"

    results_dir.mkdir(parents=True, exist_ok=True)
    pointcloud_dir.mkdir(parents=True, exist_ok=True)
    traits_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)

    return {
        "results_dir": results_dir,
        "pointcloud_dir": pointcloud_dir,
        "traits_dir": traits_dir,
        "state_dir": state_dir,
        "results_log": results_dir / "results_log.csv",
    }


def ensure_pointcloud_date_dir(pointcloud_root: Path, date_folder: str) -> Path:
    out = pointcloud_root / date_folder
    out.mkdir(parents=True, exist_ok=True)
    return out


def ensure_results_log(results_log: Path) -> None:
    if results_log.exists():
        return

    with open(results_log, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "run_id",
            "run_timestamp",
            "experiment",
            "date_folder",
            "algorithm",
            "status",
            "output_file",
            "notes",
        ])


def append_results_log(
    results_log: Path,
    experiment: str,
    date_folder: str,
    algorithm: str,
    status: str,
    output_file: str = "",
    notes: str = "",
    run_id: str | None = None,
) -> None:
    ensure_results_log(results_log)

    if run_id is None:
        run_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    run_timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open(results_log, "a", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            run_id,
            run_timestamp,
            experiment,
            date_folder,
            algorithm,
            status,
            output_file,
            notes,
        ])


def pointcloud_output_name(plot_name: str, cart_id: str, date_folder: str, experiment: str) -> str:
    return f"{plot_name}_{cart_id}_{date_folder}_{experiment}.csv"


def traits_output_name(date_folder: str) -> str:
    return f"{date_folder}_lidar_traits_summary.csv"


def completed_scans_path(state_dir: Path, date_folder: str) -> Path:
    return state_dir / f"completed_scans_{date_folder}.txt"
