#!/usr/bin/env python3
"""Fail closed unless an expected-impacts matrix exactly follows the validated grid."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path


MODEL_NUISANCES = ("lumi24", "lumi25", "ttbar_xsec")
REQUIRED_LEDGER_COLUMNS = {
    "width_percent",
    "mass_GeV",
    "rMax",
    "expected_q50_r",
}


def read_points(path: Path) -> list[tuple[int, int, float]]:
    points: list[tuple[int, int, float]] = []
    for line_number, raw_line in enumerate(path.read_text().splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 3:
            raise ValueError(f"{path}:{line_number}: expected width mass rMax")
        width, mass, rmax = int(fields[0]), int(fields[1]), float(fields[2])
        if rmax <= 0 or not math.isfinite(rmax):
            raise ValueError(f"{path}:{line_number}: invalid rMax")
        points.append((width, mass, rmax))
    if len(points) != 12 or len(set((width, mass) for width, mass, _ in points)) != 12:
        raise ValueError(f"{path}: expected exactly 12 unique width/mass points")
    return points


def read_ledger(path: Path) -> dict[tuple[int, int], tuple[float, float]]:
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or not REQUIRED_LEDGER_COLUMNS.issubset(reader.fieldnames):
            raise ValueError(f"{path}: missing required expected-limit ledger columns")
        ledger: dict[tuple[int, int], tuple[float, float]] = {}
        for line_number, row in enumerate(reader, 2):
            key = (int(row["width_percent"]), int(row["mass_GeV"]))
            if key in ledger:
                raise ValueError(f"{path}:{line_number}: duplicate expected-limit ledger point {key}")
            rmax, q50 = float(row["rMax"]), float(row["expected_q50_r"])
            if not all(math.isfinite(value) and value > 0 for value in (rmax, q50)):
                raise ValueError(f"{path}:{line_number}: non-positive or non-finite ledger value")
            ledger[key] = (rmax, q50)
    return ledger


def validate(points_path: Path, ledger_path: Path, matrix_path: Path) -> int:
    points = read_points(points_path)
    ledger = read_ledger(ledger_path)
    expected_rows: list[tuple[int, int, float, str, float]] = []
    for width, mass, rmax in points:
        ledger_rmax, q50 = ledger.get((width, mass), (math.nan, math.nan))
        if not math.isclose(rmax, ledger_rmax, rel_tol=0, abs_tol=1e-12):
            raise ValueError(f"ledger rMax disagrees with points for w{width} M{mass}")
        if q50 >= 0.9 * rmax:
            raise ValueError(f"median expected r95 lacks rMax headroom for w{width} M{mass}")
        expected_rows.extend((width, mass, rmax, nuisance, q50) for nuisance in MODEL_NUISANCES)

    actual_rows: list[tuple[int, int, float, str, float]] = []
    for line_number, raw_line in enumerate(matrix_path.read_text().splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 5:
            raise ValueError(f"{matrix_path}:{line_number}: expected five columns")
        try:
            row = (int(fields[0]), int(fields[1]), float(fields[2]), fields[3], float(fields[4]))
        except ValueError as error:
            raise ValueError(f"{matrix_path}:{line_number}: malformed numeric value") from error
        if not math.isfinite(row[2]) or not math.isfinite(row[4]) or row[2] <= 0 or row[4] <= 0:
            raise ValueError(f"{matrix_path}:{line_number}: non-positive or non-finite rMax/rInject")
        actual_rows.append(row)

    if len(actual_rows) != len(expected_rows):
        raise ValueError(f"{matrix_path}: expected {len(expected_rows)} rows, found {len(actual_rows)}")
    for index, (actual, expected) in enumerate(zip(actual_rows, expected_rows), 1):
        actual_width, actual_mass, actual_rmax, actual_nuisance, actual_rinject = actual
        expected_width, expected_mass, expected_rmax, expected_nuisance, expected_rinject = expected
        if (actual_width, actual_mass, actual_nuisance) != (expected_width, expected_mass, expected_nuisance):
            raise ValueError(f"{matrix_path}: row {index} has an unexpected point/nuisance")
        if not math.isclose(actual_rmax, expected_rmax, rel_tol=0, abs_tol=1e-12):
            raise ValueError(f"{matrix_path}: row {index} changes rMax")
        if not math.isclose(actual_rinject, expected_rinject, rel_tol=0, abs_tol=1e-15):
            raise ValueError(f"{matrix_path}: row {index} rInject is not ledger expected_q50_r")
    return len(actual_rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--points", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--matrix", type=Path, required=True)
    args = parser.parse_args()
    rows = validate(args.points, args.ledger, args.matrix)
    print(f"EXPECTED_IMPACTS_MATRIX_OK rows={rows} points=12 nuisances=3")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
