#!/usr/bin/env python3
"""Fail-closed validation for the portable one-nuisance Asimov Impacts canary."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any


MASK_NAMES = (
    "mask_cen_Cen24Pass_Region1",
    "mask_cen_Cen25Pass_Region1",
    "mask_fwd_Fwd24Pass_Region1",
    "mask_fwd_Fwd25Pass_Region1",
)
MODEL_NUISANCES = ("lumi24", "lumi25", "ttbar_xsec")


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
        raise ValueError("PyROOT is required for snapshot validation") from error
    ROOT.gROOT.SetBatch(True)
    return ROOT


def validate_snapshot(path: Path, rmax: float) -> dict[str, object]:
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
        if not math.isclose(float(poi.getMax()), rmax, abs_tol=1e-12):
            raise ValueError("snapshot r maximum does not match production rMax")
        missing_masks = [name for name in MASK_NAMES if not workspace.var(name)]
        if missing_masks:
            raise ValueError(f"snapshot missing required masks: {missing_masks}")
        model_config = workspace.genobj("ModelConfig")
        nuisance_set = model_config.GetNuisanceParameters() if model_config else None
        if not nuisance_set:
            raise ValueError("snapshot lacks ModelConfig nuisances")
        iterator = nuisance_set.createIterator()
        nuisances: list[str] = []
        while variable := iterator.Next():
            nuisances.append(variable.GetName())
        if tuple(sorted(nuisances)) != MODEL_NUISANCES:
            raise ValueError(f"unexpected ModelConfig nuisances: {sorted(nuisances)}")
        variables = workspace.allVars()
        iterator = variables.createIterator()
        rpf_ranges: dict[str, tuple[float, float]] = {}
        while variable := iterator.Next():
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
            "r_range": [0.0, rmax],
            "required_masks": list(MASK_NAMES),
            "model_nuisances": list(MODEL_NUISANCES),
            "rpf_count": len(rpf_ranges),
            "positive_rpf_par0_count": positive_par0,
        }
    finally:
        root_file.Close()


def finite(value: Any, label: str) -> float:
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{label} is not finite")
    return float(value)


def finite_triplet(value: Any, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{label} is not a three-value interval")
    return [finite(item, label) for item in value]


def contains_forbidden_marker(value: Any) -> bool:
    if isinstance(value, str):
        lowered = value.lower()
        return "observed" in lowered or "data_obs" in lowered
    if isinstance(value, list):
        return any(contains_forbidden_marker(item) for item in value)
    if isinstance(value, dict):
        return any(contains_forbidden_marker(key) or contains_forbidden_marker(item) for key, item in value.items())
    return False


def validate_impacts_payload(payload: dict[str, Any], nuisance: str) -> dict[str, object]:
    if nuisance not in MODEL_NUISANCES:
        raise ValueError(f"unregistered ModelConfig nuisance: {nuisance}")
    if contains_forbidden_marker(payload):
        raise ValueError("forbidden non-synthetic marker in impacts JSON")
    if set(payload) != {"POIs", "params", "method"} or payload.get("method") != "default":
        raise ValueError("unexpected Impacts JSON top-level schema")
    pois = payload.get("POIs")
    params = payload.get("params")
    if not isinstance(pois, list) or len(pois) != 1 or not isinstance(params, list) or len(params) != 1:
        raise ValueError("Impacts JSON must contain exactly one POI and one named nuisance")
    poi = pois[0]
    param = params[0]
    if not isinstance(poi, dict) or poi.get("name") != "r":
        raise ValueError("Impacts POI is not exactly r")
    finite_triplet(poi.get("fit"), "POI r fit")
    if not isinstance(param, dict) or param.get("name") != nuisance:
        raise ValueError(f"Impacts nuisance is not exactly {nuisance}")
    finite_triplet(param.get("fit"), "nuisance fit")
    finite_triplet(param.get("r"), "nuisance r interval")
    impact = finite(param.get("impact_r"), "impact_r")
    if impact < 0:
        raise ValueError("impact_r is negative")
    return {
        "schema_version": 1,
        "dataset_scope": "synthetic_asimov_only",
        "poi": "r",
        "named_nuisance": nuisance,
        "impact_r": impact,
        "poi_fit": finite_triplet(poi["fit"], "POI r fit"),
        "nuisance_fit": finite_triplet(param["fit"], "nuisance fit"),
        "nuisance_r": finite_triplet(param["r"], "nuisance r interval"),
    }


def validate_parameter_fit(
    path: Path, nuisance: str, rmax: float
) -> dict[str, object]:
    if nuisance not in MODEL_NUISANCES:
        raise ValueError(f"unregistered ModelConfig nuisance: {nuisance}")
    if not math.isfinite(rmax) or rmax <= 0.0:
        raise ValueError(f"invalid production rMax: {rmax}")
    ROOT = import_root()
    root_file = ROOT.TFile.Open(str(path))
    if not root_file or root_file.IsZombie():
        raise ValueError(f"cannot open named Impacts ROOT: {path}")
    try:
        tree = root_file.Get("limit")
        if not tree:
            raise ValueError("named Impacts ROOT has no limit tree")
        present = {branch.GetName() for branch in tree.GetListOfBranches()}
        required = {"r", nuisance, "deltaNLL"}
        if not required.issubset(present):
            raise ValueError(
                f"named Impacts tree missing branches: {sorted(required - present)}"
            )
        records: list[dict[str, float]] = []
        for entry in tree:
            record = {
                "r": float(entry.r),
                nuisance: float(getattr(entry, nuisance)),
                "deltaNLL": float(entry.deltaNLL),
            }
            if not all(math.isfinite(value) for value in record.values()):
                raise ValueError("named Impacts tree contains a non-finite entry")
            if record["r"] < 0.0 or record["r"] > rmax:
                raise ValueError("named Impacts fit has r outside [0,rMax]")
            if record["deltaNLL"] < -1.0e-6:
                raise ValueError("named Impacts fit has a negative deltaNLL")
            if "fit_status" in present and int(entry.fit_status) != 0:
                raise ValueError("named Impacts tree records a nonzero fit status")
            records.append(record)
        if len(records) != 3:
            raise ValueError(
                f"expected exactly three named-impact entries, found {len(records)}"
            )
        return {
            "schema_version": 1,
            "dataset_scope": "synthetic_asimov_only",
            "named_nuisance": nuisance,
            "tree_entries": len(records),
            "required_branches": sorted(required),
            "fit_status_checked": "fit_status" in present,
            "root_sha256": sha256_file(path),
            "records": records,
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
    snapshot.add_argument("--rmax", type=float, required=True)
    snapshot.add_argument("--output", type=Path, required=True)
    impacts = subparsers.add_parser("impacts")
    impacts.add_argument("path", type=Path)
    impacts.add_argument("--nuisance", required=True)
    impacts.add_argument("--output", type=Path, required=True)
    parameter_fit = subparsers.add_parser("parameter-fit")
    parameter_fit.add_argument("path", type=Path)
    parameter_fit.add_argument("--nuisance", required=True)
    parameter_fit.add_argument("--rmax", type=float, required=True)
    parameter_fit.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "snapshot":
        if not math.isfinite(args.rmax) or args.rmax <= 0.0:
            raise ValueError("snapshot validation requires positive finite rMax")
        result = validate_snapshot(args.path, args.rmax)
    elif args.mode == "impacts":
        result = validate_impacts_payload(json.loads(args.path.read_text()), args.nuisance)
    else:
        result = validate_parameter_fit(args.path, args.nuisance, args.rmax)
    write_json(result, args.output)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (json.JSONDecodeError, OSError, ValueError) as error:
        print(f"ASIMOV_IMPACTS_VALIDATION_FAILED: {error}", file=sys.stderr)
        raise SystemExit(2)
