#!/usr/bin/env python3
"""Fail-closed validation for the portable synthetic-Asimov scan canary."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys


MASK_NAMES = (
    "mask_cen_Cen24Pass_Region1",
    "mask_cen_Cen25Pass_Region1",
    "mask_fwd_Fwd24Pass_Region1",
    "mask_fwd_Fwd25Pass_Region1",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def import_root():
    try:
        import ROOT
    except ImportError as error:
        raise ValueError("PyROOT is required for ROOT validation") from error
    ROOT.gROOT.SetBatch(True)
    return ROOT


def validate_snapshot(path: Path, production_rmax: float) -> dict[str, object]:
    ROOT = import_root()
    root_file = ROOT.TFile.Open(str(path))
    if not root_file or root_file.IsZombie():
        raise ValueError(f"cannot open snapshot ROOT: {path}")
    try:
        workspace = root_file.Get("w")
        if not workspace or not workspace.getSnapshot("MultiDimFit"):
            raise ValueError("snapshot lacks workspace w or MultiDimFit snapshot")
        workspace.loadSnapshot("MultiDimFit")
        poi = workspace.var("r")
        if not poi or not math.isclose(float(poi.getMin()), 0.0, abs_tol=1e-12):
            raise ValueError("snapshot r minimum is not zero")
        # float32-stored bound (e.g. 0.1 -> 0.10000000149011612)
        if not math.isclose(float(poi.getMax()), production_rmax, rel_tol=1e-6):
            raise ValueError("snapshot r maximum does not match production rMax")
        missing = [name for name in MASK_NAMES if not workspace.var(name)]
        if missing:
            raise ValueError(f"snapshot missing required masks: {missing}")
        variables = workspace.allVars()
        iterator = variables.createIterator()
        rpf_ranges: dict[str, tuple[float, float]] = {}
        while True:
            variable = iterator.Next()
            if not variable:
                break
            if "rpf_par" in variable.GetName():
                rpf_ranges[variable.GetName()] = (float(variable.getMin()), float(variable.getMax()))
        if len(rpf_ranges) != 18:
            raise ValueError(f"expected 18 RPF variables, found {len(rpf_ranges)}")
        positive_par0 = 0
        for name, (minimum, maximum) in rpf_ranges.items():
            expected_minimum = 0.001 if name.endswith("rpf_par0") else -50.0
            if name.endswith("rpf_par0"):
                positive_par0 += 1
            if not math.isclose(minimum, expected_minimum, abs_tol=1e-9) or not math.isclose(maximum, 50.0, abs_tol=1e-9):
                raise ValueError(f"non-physical RPF range for {name}: [{minimum}, {maximum}]")
        if positive_par0 != 4:
            raise ValueError(f"expected four positive rpf_par0 variables, found {positive_par0}")
        return {
            "schema_version": 1,
            "snapshot_name": "MultiDimFit",
            "snapshot_sha256": sha256_file(path),
            "production_r_range": [0.0, production_rmax],
            "required_masks": list(MASK_NAMES),
            "rpf_count": len(rpf_ranges),
            "positive_rpf_par0_count": positive_par0,
        }
    finally:
        root_file.Close()


def validate_scan(path: Path, diagnostic_rmax: float, grid_points: int) -> dict[str, object]:
    ROOT = import_root()
    root_file = ROOT.TFile.Open(str(path))
    if not root_file or root_file.IsZombie():
        raise ValueError(f"cannot open scan ROOT: {path}")
    try:
        tree = root_file.Get("limit")
        if not tree:
            raise ValueError("scan ROOT has no limit tree")
        required = {"r", "deltaNLL", "quantileExpected"}
        present = {branch.GetName() for branch in tree.GetListOfBranches()}
        if not required.issubset(present):
            raise ValueError(f"scan tree missing branches: {sorted(required - present)}")
        entries: list[dict[str, float]] = []
        for entry in tree:
            r_value = float(entry.r)
            delta_nll = float(entry.deltaNLL)
            quantile = float(entry.quantileExpected)
            if not all(math.isfinite(value) for value in (r_value, delta_nll, quantile)):
                raise ValueError("scan contains non-finite entry")
            if r_value < 0.0 or r_value > diagnostic_rmax:
                raise ValueError("scan r entry is outside diagnostic range")
            if delta_nll < -0.05:
                raise ValueError(f"scan deltaNLL below tolerance: {delta_nll}")
            entries.append({"r": r_value, "deltaNLL": delta_nll, "quantileExpected": quantile})
        # MultiDimFit grid writes one best-fit entry followed by exactly N grid entries.
        if len(entries) != grid_points + 1:
            raise ValueError(f"expected {grid_points + 1} limit entries, found {len(entries)}")
        # combine writes the free best-fit entry FIRST, then the N grid rows;
        # its quantileExpected flag is not a reliable discriminator across
        # versions, so select positionally.
        grid = entries[1:]
        if len(grid) != grid_points:
            raise ValueError(f"expected {grid_points} grid entries, found {len(grid)}")
        if entries[0]["deltaNLL"] > 1e-6:
            raise ValueError("first entry is not the best-fit row (deltaNLL != 0)")
        if not math.isclose(min(item["r"] for item in grid), 0.0, abs_tol=1e-9):
            raise ValueError("grid does not include r=0")
        if not math.isclose(max(item["r"] for item in grid), diagnostic_rmax, abs_tol=1e-9):
            raise ValueError("grid does not include the diagnostic r maximum")
        return {
            "schema_version": 1,
            "method": "MultiDimFit_grid",
            "dataset_scope": "synthetic_asimov_only",
            "production_rMax": 1.0,
            "diagnostic_scan_rMax": diagnostic_rmax,
            "grid_points": grid_points,
            "limit_tree_entries": len(entries),
            "scan_point_count": len(grid),
            "scan_sha256": sha256_file(path),
            "deltaNLL_min": min(item["deltaNLL"] for item in entries),
            "deltaNLL_max": max(item["deltaNLL"] for item in entries),
        }
    finally:
        root_file.Close()


def write_json(payload: dict[str, object], output: Path) -> None:
    if output.exists():
        raise ValueError(f"refusing to overwrite validation JSON: {output}")
    temporary = output.with_name(f".{output.name}.tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    temporary.replace(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="mode", required=True)
    snapshot = subparsers.add_parser("snapshot")
    snapshot.add_argument("path", type=Path)
    snapshot.add_argument("--production-rmax", type=float, required=True)
    snapshot.add_argument("--output", type=Path, required=True)
    scan = subparsers.add_parser("scan")
    scan.add_argument("path", type=Path)
    scan.add_argument("--diagnostic-rmax", type=float, required=True)
    scan.add_argument("--grid-points", type=int, required=True)
    scan.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "snapshot":
        # matrix mode: per-point production rMax from the ledger
        if not math.isfinite(args.production_rmax) or args.production_rmax <= 0:
            raise ValueError("production rMax must be finite and positive")
        payload = validate_snapshot(args.path, args.production_rmax)
    else:
        if not math.isfinite(args.diagnostic_rmax) or args.diagnostic_rmax <= 0 or args.grid_points != 41:
            raise ValueError("this canary requires a finite diagnostic range and exactly 41 grid points")
        payload = validate_scan(args.path, args.diagnostic_rmax, args.grid_points)
    write_json(payload, args.output)
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        print(f"ASIMOV_SCAN_VALIDATION_FAILED: {error}", file=sys.stderr)
        raise SystemExit(2)
