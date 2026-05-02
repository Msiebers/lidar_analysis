from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ManifestKey:
    experiment: str
    date_name: str


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def save_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False)


def manifest_path(manifest_root: Path, experiment: str, date_name: str) -> Path:
    return manifest_root / experiment / f"{date_name}.yaml"


def default_manifest(experiment: str, date_name: str, raw_path: str) -> dict[str, Any]:
    return {
        "experiment_name": experiment,
        "date": date_name,
        "raw_path": raw_path,
        "ready": False,
        "source_signature": None,
        "status": "discovered",
        "latest_run_id": None,
        "published_run_id": None,
        "runs": [],
        "updated_at": utc_now(),
    }


def load_manifest(manifest_root: Path, experiment: str, date_name: str, raw_path: str) -> dict[str, Any]:
    path = manifest_path(manifest_root, experiment, date_name)
    data = load_yaml(path)
    if not data:
        data = default_manifest(experiment, date_name, raw_path)
    data.setdefault("experiment_name", experiment)
    data.setdefault("date", date_name)
    data.setdefault("raw_path", raw_path)
    data.setdefault("ready", False)
    data.setdefault("source_signature", None)
    data.setdefault("status", "discovered")
    data.setdefault("latest_run_id", None)
    data.setdefault("published_run_id", None)
    data.setdefault("runs", [])
    data.setdefault("updated_at", utc_now())
    return data


def save_manifest(manifest_root: Path, manifest: dict[str, Any]) -> Path:
    manifest["updated_at"] = utc_now()
    path = manifest_path(manifest_root, manifest["experiment_name"], manifest["date"])
    save_yaml(path, manifest)
    return path


def _find_run(manifest: dict[str, Any], run_id: str) -> dict[str, Any] | None:
    for run in manifest.get("runs", []):
        if run.get("run_id") == run_id:
            return run
    return None


def create_run(
    manifest: dict[str, Any],
    *,
    run_id: str,
    workspace_dir: str,
    input_signature: str,
    config_path: str,
    cart_id: str | None = None,
    notes: str = "",
) -> dict[str, Any]:
    run = {
        "run_id": run_id,
        "status": "staged",
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "workspace_dir": workspace_dir,
        "input_signature": input_signature,
        "config_path": config_path,
        "cart_id": cart_id,
        "notes": notes,
        "error": None,
        "published_paths": {},
    }
    manifest.setdefault("runs", []).append(run)
    manifest["latest_run_id"] = run_id
    manifest["source_signature"] = input_signature
    manifest["status"] = "staged"
    return run


def update_run(
    manifest: dict[str, Any],
    run_id: str,
    *,
    status: str,
    error: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run = _find_run(manifest, run_id)
    if run is None:
        raise KeyError(f"Run {run_id} not found in manifest")
    run["status"] = status
    run["updated_at"] = utc_now()
    if error is not None:
        run["error"] = error
    if extra:
        run.update(extra)
    manifest["latest_run_id"] = run_id
    manifest["status"] = status
    return run


def mark_published(manifest: dict[str, Any], run_id: str, published_paths: dict[str, str]) -> dict[str, Any]:
    run = update_run(manifest, run_id, status="published", extra={"published_paths": published_paths})
    manifest["published_run_id"] = run_id
    manifest["status"] = "published"
    return run


def should_process(manifest: dict[str, Any], current_signature: str, *, force: bool = False) -> bool:
    if force:
        return True
    if not manifest.get("ready", False):
        return False
    published_run_id = manifest.get("published_run_id")
    if not published_run_id:
        return True
    if manifest.get("source_signature") != current_signature:
        return True
    latest_run = _find_run(manifest, manifest.get("latest_run_id") or "")
    if latest_run and latest_run.get("status") == "failed":
        return True
    return False


def compute_directory_signature(path: Path) -> str:
    digest = sha256()
    digest.update(str(path.resolve()).encode("utf-8"))
    if not path.exists():
        digest.update(b"missing")
        return digest.hexdigest()

    for item in sorted(p for p in path.rglob("*") if p.is_file()):
        rel = item.relative_to(path)
        stat = item.stat()
        digest.update(str(rel).encode("utf-8"))
        digest.update(str(stat.st_size).encode("utf-8"))
        digest.update(str(int(stat.st_mtime_ns)).encode("utf-8"))
    return digest.hexdigest()
