#!/usr/bin/env python3

from pathlib import Path
import argparse
import pandas as pd


def convert_file(path: Path) -> str:
    df = pd.read_csv(path)

    new_cols = {"time_s", "count", "roll_deg", "pitch_deg", "yaw_deg", "pps"}
    old_cols = {"time_s", "count", "heading", "roll", "pitch", "pps_raw"}

    if new_cols.issubset(df.columns):
        return f"[SKIP already converted] {path}"

    missing = old_cols - set(df.columns)
    if missing:
        return f"[SKIP missing columns] {path} missing {sorted(missing)}"

    out = pd.DataFrame({
        "time_s": df["time_s"],
        "count": df["count"],
        "roll_deg": df["roll"],
        "pitch_deg": df["pitch"],
        "yaw_deg": df["heading"],
        "pps": df["pps_raw"],
    })

    out.to_csv(path, index=False)
    return f"[CONVERTED] {path}"


def main():
    parser = argparse.ArgumentParser(
        description="Convert old Pico CSV files to current schema without changing values."
    )
    parser.add_argument("folder", help="Folder containing *_pico.csv files")
    args = parser.parse_args()

    folder = Path(args.folder).expanduser().resolve()
    if not folder.exists():
        raise SystemExit(f"Folder does not exist: {folder}")

    pico_files = sorted(folder.rglob("*_pico.csv"))
    if not pico_files:
        raise SystemExit(f"No *_pico.csv files found under: {folder}")

    for path in pico_files:
        print(convert_file(path))

    print(f"\nDone. Checked {len(pico_files)} Pico file(s).")


if __name__ == "__main__":
    main()