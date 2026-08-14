#!/usr/bin/env python3
"""Validate one independent synthetic-Asimov fixed-r profile point."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate(path: Path, target_r: float, scan_rmax: float) -> dict[str, object]:
    try:
        import ROOT
    except ImportError as error:
        raise ValueError("PyROOT is required for fixed-point validation") from error
    ROOT.gROOT.SetBatch(True)
    root_file = ROOT.TFile.Open(str(path))
    if not root_file or root_file.IsZombie():
        raise ValueError(f"cannot open fixed-point ROOT: {path}")
    try:
        tree = root_file.Get("limit")
        if not tree:
            raise ValueError("fixed-point ROOT has no limit tree")
        present = {branch.GetName() for branch in tree.GetListOfBranches()}
        required = {"r", "deltaNLL", "quantileExpected"}
        if not required.issubset(present):
            raise ValueError(f"fixed-point tree missing branches: {sorted(required - present)}")
        entries: list[dict[str, float]] = []
        for entry in tree:
            record = {
                "r": float(entry.r),
                "deltaNLL": float(entry.deltaNLL),
                "quantileExpected": float(entry.quantileExpected),
            }
            for optional in ("nll", "nll0"):
                if optional in present:
                    record[optional] = float(getattr(entry, optional))
            if not all(math.isfinite(value) for value in record.values()):
                raise ValueError("fixed-point tree contains non-finite values")
            if record["r"] < 0 or record["r"] > scan_rmax:
                raise ValueError("fixed-point tree contains r outside diagnostic range")
            if record["deltaNLL"] < 0 or record["deltaNLL"] >= 1000:
                raise ValueError(f"invalid or sentinel deltaNLL={record['deltaNLL']}")
            entries.append(record)
        if not 1 <= len(entries) <= 2:
            raise ValueError(f"expected one fixed entry and at most one best-fit entry, found {len(entries)}")
        # Combine marks the unconditional best fit with quantileExpected=-1.
        # Profile points use a non-negative marker.
        fixed_entries = [entry for entry in entries if entry["quantileExpected"] > -0.5]
        if len(fixed_entries) != 1:
            raise ValueError(f"expected exactly one profiled fixed entry, found {len(fixed_entries)}")
        fixed = fixed_entries[0]
        if not math.isclose(fixed["r"], target_r, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError(f"fixed entry r={fixed['r']} does not match target {target_r}")
        return {
            "schema_version": 1,
            "method": "MultiDimFit_fixed_independent",
            "dataset_scope": "synthetic_asimov_only",
            "target_r": target_r,
            "diagnostic_scan_rMax": scan_rmax,
            "entry_count": len(entries),
            "fixed_entry": fixed,
            "entries": entries,
            "root_sha256": sha256_file(path),
        }
    finally:
        root_file.Close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--target-r", type=float, required=True)
    parser.add_argument("--scan-rmax", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not math.isfinite(args.target_r) or not math.isfinite(args.scan_rmax):
        raise ValueError("non-finite target or range")
    if args.target_r < 0 or args.scan_rmax <= 0 or args.target_r > args.scan_rmax:
        raise ValueError("target is outside diagnostic range")
    if args.output.exists():
        raise ValueError(f"refusing to overwrite output: {args.output}")
    payload = validate(args.path, args.target_r, args.scan_rmax)
    temporary = args.output.with_name(f".{args.output.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(args.output)
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        print(f"ASIMOV_FIXEDPOINT_VALIDATION_FAILED: {error}")
        raise SystemExit(2)
