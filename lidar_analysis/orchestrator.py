from __future__ import annotations

import csv
import shutil
from dataclasses import dataclass
from pathlib import Path

import yaml

try:
    from .central_runner import extract_analysis_cfg, run_experiment_date
    from .run_manifest import (
        compute_directory_signature,
        create_run,
        load_manifest,
        mark_published,
        save_manifest,
        should_process,
        update_run,
        utc_now,
    )
    from .scaffold_experiments import ensure_experiment_scaffold
except Exception:
    from central_runner import extract_analysis_cfg, run_experiment_date
    from run_manifest import (
        compute_directory_signature,
        create_run,
        load_manifest,
        mark_published,
        save_manifest,
        should_process,
        update_run,
        utc_now,
    )
    from scaffold_experiments import ensure_experiment_scaffold


POINTCLOUD_EXTS = {".ply", ".pcd", ".las", ".laz", ".csv"}
RESULT_NAMES = {"results.csv", "summary.csv"}
METADATA_NAMES = {
    "experiment_config.snapshot.yaml",
    "conditional_config.snapshot.yaml",
    "process.log",
}


@dataclass(frozen=True)
class PipelinePaths:
    raw_root: Path
    experiments_root: Path
    workspace_root: Path
    manifest_root: Path
    log_root: Path

    @property
    def cache_root(self) -> Path:
        return self.workspace_root / "cache"

    @property
    def cache_raw_root(self) -> Path:
        return self.cache_root / "raw"

    @property
    def runs_root(self) -> Path:
        return self.workspace_root / "runs"

    @property
    def published_cache_root(self) -> Path:
        return self.workspace_root / "published"


DEFAULT_PATHS = PipelinePaths(
    raw_root=Path("/mnt/cartcity/raw_data"),
    experiments_root=Path("/mnt/cartcity/experiments"),
    workspace_root=Path("/media/central/raw_mirror"),
    manifest_root=Path("/media/central/raw_mirror/manifests"),
    log_root=Path("/media/central/raw_mirror/logs"),
)


def now_str() -> str:
    return utc_now()


def append_log(log_path: Path, line: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"{now_str()} - {line}\n")


def ensure_workspace_dirs(paths: PipelinePaths) -> None:
    for p in [paths.cache_raw_root, paths.runs_root, paths.published_cache_root, paths.manifest_root, paths.log_root]:
        p.mkdir(parents=True, exist_ok=True)


def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def classify_output_file(item: Path, source_root: Path) -> tuple[str, Path]:
    rel = item.relative_to(source_root)
    name_lower = item.name.lower()
    suffix_lower = item.suffix.lower()
    rel_parts_lower = [p.lower() for p in rel.parts]

    if "pointclouds" in rel_parts_lower:
        idx = rel_parts_lower.index("pointclouds")
        subrel = Path(*rel.parts[idx + 1:]) if idx + 1 < len(rel.parts) else Path(item.name)
        return "pointclouds", subrel
    if name_lower in RESULT_NAMES:
        return "results", Path(item.name)
    if name_lower in METADATA_NAMES:
        return "scan_metadata", rel
    if suffix_lower in POINTCLOUD_EXTS and name_lower not in RESULT_NAMES:
        return "pointclouds", rel
    return "scan_metadata", rel


def build_output_package(source_dir: Path, package_dir: Path) -> None:
    reset_dir(package_dir)
    pointclouds_dir = package_dir / "pointclouds"
    results_dir = package_dir / "results"
    metadata_dir = package_dir / "scan_metadata"
    pointclouds_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir.mkdir(parents=True, exist_ok=True)

    all_files = [p for p in source_dir.rglob("*") if p.is_file()]
    if not all_files:
        raise FileNotFoundError(f"No output files found in staging directory: {source_dir}")

    for item in all_files:
        bucket, rel_dest = classify_output_file(item, source_dir)
        dest_root = {
            "pointclouds": pointclouds_dir,
            "results": results_dir,
            "scan_metadata": metadata_dir,
        }[bucket]
        dest = dest_root / rel_dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, dest)


def validate_output_package(package_dir: Path) -> None:
    results_csv = package_dir / "results" / "results.csv"
    if not results_csv.exists():
        raise FileNotFoundError(f"Missing required results.csv: {results_csv}")
    pointcloud_root = package_dir / "pointclouds"
    if not any(p.is_file() for p in pointcloud_root.rglob("*")):
        raise FileNotFoundError(f"No point cloud files found in: {pointcloud_root}")


def rebuild_all_results_csv(experiment: str, paths: PipelinePaths) -> None:
    exp_dir = paths.experiments_root / experiment
    results_root = exp_dir / "results"
    all_results_path = exp_dir / "all_results.csv"
    date_result_files = sorted(results_root.glob("*/results.csv"))
    if not date_result_files:
        if all_results_path.exists():
            all_results_path.unlink()
        return

    rows: list[dict] = []
    fieldnames: list[str] | None = None
    for fp in date_result_files:
        with open(fp, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                continue
            if fieldnames is None:
                fieldnames = list(reader.fieldnames)
            rows.extend(reader)

    if not fieldnames:
        return
    with open(all_results_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

def ensure_local_experiment_config(experiment: str, local_date_dir: Path, paths: PipelinePaths) -> Path:
    src = paths.experiments_root / experiment / "experiment_config.yaml"
    dst = local_date_dir / "experiment_config.yaml"
    if not src.exists():
        raise FileNotFoundError(f"Missing experiment_config.yaml: {src}")
    if not dst.exists():
        shutil.copy2(src, dst)
    return dst


def sync_raw_date(experiment: str, date_name: str, paths: PipelinePaths, *, restage: bool = True) -> Path:
    src = paths.raw_root / experiment / date_name
    dst = paths.cache_raw_root / experiment / date_name
    dst.parent.mkdir(parents=True, exist_ok=True)
    if restage or not dst.exists():
        reset_dir(dst)
        shutil.copytree(src, dst, dirs_exist_ok=True)
    return dst


def publish_output_package(experiment: str, date_name: str, run_id: str, package_dir: Path, paths: PipelinePaths) -> dict[str, str]:
    remote_exp_dir = paths.experiments_root / experiment
    immutable_run_dir = remote_exp_dir / "runs" / run_id
    current_dir = remote_exp_dir / "current" / date_name
    legacy_pointclouds_dir = remote_exp_dir / "pointclouds" / date_name
    legacy_results_dir = remote_exp_dir / "results" / date_name
    legacy_metadata_dir = remote_exp_dir / "scan_metadata" / date_name

    for target in [immutable_run_dir, current_dir, legacy_pointclouds_dir, legacy_results_dir, legacy_metadata_dir]:
        target.mkdir(parents=True, exist_ok=True)

    shutil.copytree(package_dir / "pointclouds", immutable_run_dir / "pointclouds", dirs_exist_ok=True)
    shutil.copytree(package_dir / "results", immutable_run_dir / "results", dirs_exist_ok=True)
    shutil.copytree(package_dir / "scan_metadata", immutable_run_dir / "scan_metadata", dirs_exist_ok=True)

    reset_dir(current_dir)
    shutil.copytree(package_dir / "pointclouds", current_dir / "pointclouds", dirs_exist_ok=True)
    shutil.copytree(package_dir / "results", current_dir / "results", dirs_exist_ok=True)
    shutil.copytree(package_dir / "scan_metadata", current_dir / "scan_metadata", dirs_exist_ok=True)

    reset_dir(legacy_pointclouds_dir)
    reset_dir(legacy_results_dir)
    reset_dir(legacy_metadata_dir)
    shutil.copytree(package_dir / "pointclouds", legacy_pointclouds_dir, dirs_exist_ok=True)
    shutil.copytree(package_dir / "results", legacy_results_dir, dirs_exist_ok=True)
    shutil.copytree(package_dir / "scan_metadata", legacy_metadata_dir, dirs_exist_ok=True)

    rebuild_all_results_csv(experiment, paths)

    return {
        "immutable_run_dir": str(immutable_run_dir),
        "current_dir": str(current_dir),
        "legacy_pointclouds_dir": str(legacy_pointclouds_dir),
        "legacy_results_dir": str(legacy_results_dir),
        "legacy_metadata_dir": str(legacy_metadata_dir),
    }


def experiment_config_path(experiment: str, paths: PipelinePaths) -> Path:
    return paths.experiments_root / experiment / "experiment_config.yaml"


def experiment_mode(experiment: str, paths: PipelinePaths) -> tuple[str, dict]:
    cfg = load_yaml(experiment_config_path(experiment, paths))
    mode = str(cfg.get("processing_mode", "off")).strip().lower()
    if mode not in {"off", "local", "auto_publish"}:
        raise ValueError(f"Invalid processing_mode={mode!r}")
    return mode, cfg


def raw_date_ready(date_dir: Path) -> bool:
    markers = [date_dir / "_READY", date_dir / "ready.yaml", date_dir / "ingest_manifest.yaml"]
    if any(p.exists() for p in markers):
        return True
    return (date_dir / "cart_config.yaml").exists()


def list_raw_experiments(paths: PipelinePaths) -> list[str]:
    if not paths.raw_root.exists():
        return []
    return sorted(p.name for p in paths.raw_root.iterdir() if p.is_dir())


def list_ready_dates(experiment: str, paths: PipelinePaths) -> list[str]:
    exp_root = paths.raw_root / experiment
    if not exp_root.exists():
        return []
    return sorted(p.name for p in exp_root.iterdir() if p.is_dir() and raw_date_ready(p))


def process_one_date(
    experiment: str,
    date_name: str,
    *,
    paths: PipelinePaths = DEFAULT_PATHS,
    force: bool = False,
    publish: bool = True,
    restage: bool = True,
) -> Path:
    ensure_workspace_dirs(paths)
    ensure_experiment_scaffold(experiment)

    watcher_log = paths.log_root / "pipeline.log"
    raw_dir = paths.raw_root / experiment / date_name
    raw_signature = compute_directory_signature(raw_dir)
    manifest = load_manifest(paths.manifest_root, experiment, date_name, str(raw_dir))
    manifest["ready"] = raw_date_ready(raw_dir)
    manifest["source_signature"] = raw_signature
    save_manifest(paths.manifest_root, manifest)

    run_id = now_str().replace(":", "").replace("-", "").replace("+00:00", "Z").replace("T", "_")
    run_root = paths.runs_root / experiment / date_name / run_id
    input_dir = sync_raw_date(experiment, date_name, paths, restage=restage)
    work_dir = run_root / "work"
    output_dir = run_root / "output"
    package_dir = run_root / "package"
    work_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    cfg_path = ensure_local_experiment_config(experiment, input_dir, paths)
    cfg = load_yaml(cfg_path)
    analysis_cfg = extract_analysis_cfg(cfg)

    create_run(
        manifest,
        run_id=run_id,
        workspace_dir=str(run_root),
        input_signature=raw_signature,
        config_path=str(cfg_path),
        notes="manual rerun" if force else "auto/manual process",
    )
    save_manifest(paths.manifest_root, manifest)
    append_log(watcher_log, f"START experiment={experiment} date={date_name} run_id={run_id}")

    try:
        update_run(manifest, run_id, status="processing")
        save_manifest(paths.manifest_root, manifest)

        run_experiment_date(
            experiment=experiment,
            date_name=date_name,
            input_dir=input_dir,
            working_dir=work_dir,
            output_dir=output_dir,
            experiment_config=cfg,
            experiment_analysis=analysis_cfg,
            force=force,
        )

        build_output_package(output_dir, package_dir)
        validate_output_package(package_dir)
        update_run(manifest, run_id, status="validated", extra={"package_dir": str(package_dir)})
        save_manifest(paths.manifest_root, manifest)

        if publish:
            published_paths = publish_output_package(experiment, date_name, run_id, package_dir, paths)
            mark_published(manifest, run_id, published_paths)
        save_manifest(paths.manifest_root, manifest)
        append_log(watcher_log, f"SUCCESS experiment={experiment} date={date_name} run_id={run_id}")
    except Exception as exc:
        update_run(manifest, run_id, status="failed", error=str(exc), extra={"package_dir": str(package_dir)})
        save_manifest(paths.manifest_root, manifest)
        append_log(watcher_log, f"FAILED experiment={experiment} date={date_name} run_id={run_id} error={exc}")
        raise

    return run_root


def poll_once(*, paths: PipelinePaths = DEFAULT_PATHS, force: bool = False, publish: bool = True) -> None:
    ensure_workspace_dirs(paths)
    watcher_log = paths.log_root / "pipeline.log"
    append_log(watcher_log, "Polling cycle start")
    for experiment in list_raw_experiments(paths):
        ensure_experiment_scaffold(experiment)
        mode, _cfg = experiment_mode(experiment, paths)
        if mode == "off":
            append_log(watcher_log, f"SKIP experiment={experiment} processing_mode=off")
            continue

        for date_name in list_ready_dates(experiment, paths):
            raw_dir = paths.raw_root / experiment / date_name
            signature = compute_directory_signature(raw_dir)
            manifest = load_manifest(paths.manifest_root, experiment, date_name, str(raw_dir))
            manifest["ready"] = True
            save_manifest(paths.manifest_root, manifest)
            if should_process(manifest, signature, force=force):
                publish_now = (mode == "auto_publish")
                process_one_date(
                    experiment,
                    date_name,
                    paths=paths,
                    force=force,
                    publish=publish_now,
                )
            else:
                append_log(watcher_log, f"NO_WORK experiment={experiment} date={date_name}")
    append_log(watcher_log, "Polling cycle end")
