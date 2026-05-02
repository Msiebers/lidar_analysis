#!/usr/bin/env python3
import argparse
import csv


def load_points(path: str, decimals: int):
    rows = {}
    with open(path, "r", newline="") as f:
        r = csv.DictReader(f)
        needed = {"X", "Y", "Z", "rssi_norm"}
        missing = needed - set(r.fieldnames or [])
        if missing:
            raise SystemExit(f"{path} missing columns: {sorted(missing)}")
        for row in r:
            k = (round(float(row["X"]), decimals), round(float(row["Y"]), decimals), round(float(row["Z"]), decimals))
            rows[k] = float(row["rssi_norm"])
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("distance_csv")
    ap.add_argument("marker_csv")
    ap.add_argument("--coord-decimals", type=int, default=4)
    ap.add_argument("--rssi-tol", type=float, default=1e-6)
    args = ap.parse_args()

    d = load_points(args.distance_csv, args.coord_decimals)
    m = load_points(args.marker_csv, args.coord_decimals)
    keys = sorted(set(d).intersection(m))
    print(f"distance_points={len(d)} marker_points={len(m)} matched_points={len(keys)}")
    if not keys:
        print("status=FAIL")
        return 1

    mism = 0
    max_abs = 0.0
    for k in keys:
        diff = abs(d[k] - m[k])
        if diff > args.rssi_tol:
            mism += 1
        if diff > max_abs:
            max_abs = diff

    print(f"rssi_norm_tol={args.rssi_tol} mismatches={mism} max_abs_diff={max_abs:.8f}")
    print("status=PASS" if mism == 0 else "status=FAIL")
    return 0 if mism == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
