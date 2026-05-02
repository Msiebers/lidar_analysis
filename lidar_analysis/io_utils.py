from pathlib import Path


def is_lidar_file(path: Path) -> bool:
    return path.suffix.lower() == ".csv" and "_lidar_" in path.stem


def is_pico_file(path: Path) -> bool:
    return path.suffix.lower() == ".csv" and "_pico_" in path.stem


def sensor_pair_key(path: Path) -> str:
    stem = path.stem
    stem = stem.replace("_lidar_", "_SENSOR_")
    stem = stem.replace("_pico_", "_SENSOR_")
    return stem


def find_lidar_pico_pairs(date_dir: Path) -> list[tuple[str, Path, Path]]:
    files = [p for p in date_dir.iterdir() if p.is_file() and p.suffix.lower() == ".csv"]

    lidar_map = {}
    pico_map = {}

    for p in files:
        key = sensor_pair_key(p)
        if is_lidar_file(p):
            lidar_map[key] = p
        elif is_pico_file(p):
            pico_map[key] = p

    pairs = []
    for key in sorted(lidar_map.keys()):
        if key in pico_map:
            pairs.append((key, lidar_map[key], pico_map[key]))

    return pairs
