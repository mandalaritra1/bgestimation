#!/usr/bin/env python3
"""Validate the 12 x 4 injection matrix and all three start definitions."""

from __future__ import annotations

import argparse
import math
from pathlib import Path


LABELS = {"bkg", "half", "one", "two"}
SCALES = {"bkg": 0.0, "half": 0.5, "one": 1.0, "two": 2.0}


def load_points(path: Path) -> dict[tuple[int, int], str]:
    points: dict[tuple[int, int], str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        width, mass, rmax = line.split()
        key = (int(width), int(mass))
        if key in points:
            raise ValueError(f"duplicate point: {key}")
        points[key] = rmax
    if len(points) != 12:
        raise ValueError(f"expected 12 points, found {len(points)}")
    return points


def validate(points_path: Path, matrix_path: Path) -> tuple[int, int]:
    points = load_points(points_path)
    rows_by_point: dict[tuple[int, int], dict[str, tuple[float, ...]]] = {
        point: {} for point in points
    }
    rows = 0
    for line_number, raw in enumerate(matrix_path.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 8:
            raise ValueError(f"{matrix_path}:{line_number}: expected 8 columns")
        width, mass, rmax, label, *numeric = fields
        point = (int(width), int(mass))
        if point not in points or not math.isclose(float(rmax), float(points[point]), rel_tol=0, abs_tol=1e-12):
            raise ValueError(f"unknown point or altered rMax at line {line_number}")
        if label not in LABELS or label in rows_by_point[point]:
            raise ValueError(f"invalid or duplicate label at line {line_number}: {label}")
        values = tuple(float(value) for value in numeric)
        if any(not math.isfinite(value) for value in values):
            raise ValueError(f"non-finite injection/start at line {line_number}")
        injected, start_zero, start_injected, start_halfmax = values
        rmax_value = float(rmax)
        if not math.isclose(start_zero, 0.0, rel_tol=0, abs_tol=1e-15):
            raise ValueError(f"start_zero is not zero at line {line_number}")
        if not math.isclose(start_injected, injected, rel_tol=1e-11, abs_tol=1e-15):
            raise ValueError(f"start_injected mismatch at line {line_number}")
        if not math.isclose(start_halfmax, 0.5 * rmax_value, rel_tol=1e-11, abs_tol=1e-15):
            raise ValueError(f"third start is not exactly 0.5*rMax at line {line_number}")
        if injected < 0.0 or injected >= 0.9 * rmax_value:
            raise ValueError(f"injected r lacks physical rMax headroom at line {line_number}")
        rows_by_point[point][label] = values
        rows += 1
    if rows != 48 or any(set(records) != LABELS for records in rows_by_point.values()):
        raise ValueError(f"matrix is not 12 points x 4 injections: rows={rows}")
    for point, records in rows_by_point.items():
        one = records["one"][0]
        if one <= 0.0:
            raise ValueError(f"non-positive median expected r95 for {point}")
        for label, scale in SCALES.items():
            injected = records[label][0]
            if not math.isclose(injected, scale * one, rel_tol=1e-11, abs_tol=1e-15):
                raise ValueError(f"injection scale mismatch for {point} {label}")
    return rows, rows * 3


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--points", type=Path, required=True)
    parser.add_argument("--matrix", type=Path, required=True)
    args = parser.parse_args()
    rows, fits = validate(args.points, args.matrix)
    print(f"INJECTION_MATRIX_OK rows={rows} fit_attempts={fits} third_start=0.5*rMax")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
