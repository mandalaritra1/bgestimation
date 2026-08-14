#!/usr/bin/env python3
"""Validate the masked-GoF snapshot contract and saturated-GoF outputs."""

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


def validate_snapshot(path: Path, rmax: float) -> dict[str, object]:
    ROOT = import_root()
    root_file = ROOT.TFile.Open(str(path))
    if not root_file or root_file.IsZombie():
        raise ValueError(f"cannot open snapshot ROOT: {path}")
    try:
        workspace = root_file.Get("w")
        if not workspace:
            raise ValueError("snapshot has no RooWorkspace named w")
        if not workspace.getSnapshot("MultiDimFit"):
            raise ValueError("workspace has no MultiDimFit snapshot")
        workspace.loadSnapshot("MultiDimFit")

        poi = workspace.var("r")
        if not poi:
            raise ValueError("workspace has no r parameter")
        if not math.isclose(float(poi.getMin()), 0.0, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError(f"r minimum is not physical: {poi.getMin()}")
        # float32-stored bound: 0.02 arrives as 0.019999999552965164
        if not math.isclose(float(poi.getMax()), rmax, rel_tol=1e-6, abs_tol=0.0):
            raise ValueError(f"r maximum {poi.getMax()} does not match rMax={rmax}")

        missing_masks = [name for name in MASK_NAMES if not workspace.var(name)]
        if missing_masks:
            raise ValueError(f"missing required masks: {missing_masks}")

        variables = workspace.allVars()
        iterator = variables.createIterator()
        rpf_ranges: dict[str, tuple[float, float]] = {}
        while True:
            variable = iterator.Next()
            if not variable:
                break
            name = variable.GetName()
            if "rpf_par" in name:
                rpf_ranges[name] = (float(variable.getMin()), float(variable.getMax()))
        if len(rpf_ranges) != 18:
            raise ValueError(f"expected 18 RPF variables, found {len(rpf_ranges)}")
        positive_par0 = 0
        for name, (minimum, maximum) in rpf_ranges.items():
            expected_minimum = 0.001 if name.endswith("rpf_par0") else -50.0
            if name.endswith("rpf_par0"):
                positive_par0 += 1
            if not math.isclose(minimum, expected_minimum, rel_tol=0.0, abs_tol=1e-9):
                raise ValueError(f"{name} minimum {minimum}, expected {expected_minimum}")
            if not math.isclose(maximum, 50.0, rel_tol=0.0, abs_tol=1e-9):
                raise ValueError(f"{name} maximum {maximum}, expected 50")
        if positive_par0 != 4:
            raise ValueError(f"expected four positive rpf_par0 variables, found {positive_par0}")
        return {
            "schema_version": 1,
            "snapshot": str(path),
            "snapshot_sha256": sha256_file(path),
            "snapshot_name": "MultiDimFit",
            "r_range": [0.0, rmax],
            "required_masks": list(MASK_NAMES),
            "rpf_count": len(rpf_ranges),
            "positive_rpf_par0_count": positive_par0,
        }
    finally:
        root_file.Close()


def read_limit_values(path: Path) -> list[float]:
    ROOT = import_root()
    root_file = ROOT.TFile.Open(str(path))
    if not root_file or root_file.IsZombie():
        raise ValueError(f"cannot open GoF ROOT: {path}")
    try:
        tree = root_file.Get("limit")
        if not tree:
            raise ValueError(f"{path} has no limit tree")
        values: list[float] = []
        for entry in tree:
            value = float(entry.limit)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"invalid saturated-GoF statistic in {path}: {value}")
            values.append(value)
        return values
    finally:
        root_file.Close()


def validate_results(data_path: Path, toys_path: Path, toy_count: int, seed: int) -> dict[str, object]:
    observed = read_limit_values(data_path)
    toys = read_limit_values(toys_path)
    if len(observed) != 1:
        raise ValueError(f"expected one observed sideband statistic, found {len(observed)}")
    if len(toys) != toy_count:
        raise ValueError(f"expected {toy_count} toy statistics, found {len(toys)}")
    return {
        "schema_version": 1,
        "algorithm": "saturated",
        "data_scope": "observed_sideband_only",
        "pass_region_masks": "all_on_frozen",
        "r_state": "fixed_zero",
        "toy_seed": seed,
        "toy_count": toy_count,
        "observed_statistic": observed[0],
        "toy_statistics": toys,
    }


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
    snapshot_parser = subparsers.add_parser("snapshot")
    snapshot_parser.add_argument("path", type=Path)
    snapshot_parser.add_argument("--rmax", type=float, required=True)
    snapshot_parser.add_argument("--output", type=Path, required=True)
    result_parser = subparsers.add_parser("results")
    result_parser.add_argument("--data", type=Path, required=True)
    result_parser.add_argument("--toys", type=Path, required=True)
    result_parser.add_argument("--toy-count", type=int, required=True)
    result_parser.add_argument("--seed", type=int, required=True)
    result_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "snapshot":
        if not math.isfinite(args.rmax) or args.rmax <= 0:
            raise ValueError("rMax must be positive and finite")
        payload = validate_snapshot(args.path, args.rmax)
    else:
        if args.toy_count <= 0 or args.seed <= 0:
            raise ValueError("toy count and seed must be positive")
        payload = validate_results(args.data, args.toys, args.toy_count, args.seed)
    write_json(payload, args.output)
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        print(f"PORTABLE_GOF_VALIDATION_FAILED: {error}", file=sys.stderr)
        raise SystemExit(2)
