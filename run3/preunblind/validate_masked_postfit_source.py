#!/usr/bin/env python3
"""Validate the fixed masked workspace state used for 2D postfit extraction."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys


MASKS = (
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


def variable_state(workspace: object, name: str, value: float) -> dict[str, object]:
    variable = workspace.var(name)
    if not variable:
        raise ValueError(f"workspace lacks {name}")
    actual = float(variable.getVal())
    constant = bool(variable.isConstant())
    if not math.isclose(actual, value, abs_tol=1e-12) or not constant:
        raise ValueError(f"unsafe workspace state for {name}: value={actual} constant={constant}")
    return {"value": actual, "constant": constant}


def validate(snapshot_path: Path, fit_path: Path, rmax: float) -> dict[str, object]:
    try:
        import ROOT
    except ImportError as error:
        raise ValueError("PyROOT is required for masked-postfit source validation") from error
    ROOT.gROOT.SetBatch(True)
    snapshot_file = ROOT.TFile.Open(str(snapshot_path))
    fit_file = ROOT.TFile.Open(str(fit_path))
    if not snapshot_file or snapshot_file.IsZombie():
        raise ValueError(f"cannot open snapshot ROOT: {snapshot_path}")
    if not fit_file or fit_file.IsZombie():
        raise ValueError(f"cannot open fit-result ROOT: {fit_path}")
    try:
        workspace = snapshot_file.Get("w")
        if not workspace or not workspace.getSnapshot("MultiDimFit"):
            raise ValueError("workspace lacks MultiDimFit snapshot")
        current = {name: variable_state(workspace, name, 1.0) for name in MASKS}
        current_r = variable_state(workspace, "r", 0.0)
        if not math.isclose(float(workspace.var("r").getMin()), 0.0, abs_tol=1e-12):
            raise ValueError("workspace r minimum is not zero")
        if not math.isclose(float(workspace.var("r").getMax()), rmax, abs_tol=1e-12):
            raise ValueError("workspace r maximum mismatch")
        if not workspace.loadSnapshot("MultiDimFit"):
            raise ValueError("failed to load MultiDimFit snapshot")
        saved = {name: variable_state(workspace, name, 1.0) for name in MASKS}
        saved_r = variable_state(workspace, "r", 0.0)
        fit = fit_file.Get("fit_mdf")
        if not fit or not fit.InheritsFrom("RooFitResult"):
            raise ValueError("fit-result ROOT lacks fit_mdf RooFitResult")
        status, cov_qual, edm = int(fit.status()), int(fit.covQual()), float(fit.edm())
        if status != 0 or cov_qual < 3 or not math.isfinite(edm) or edm > 0.01:
            raise ValueError(f"unhealthy fit_mdf: status={status} covQual={cov_qual} EDM={edm}")
        return {
            "schema_version": 1,
            "snapshot_sha256": sha256_file(snapshot_path),
            "fit_result_sha256": sha256_file(fit_path),
            "workspace_current_masks": current,
            "workspace_snapshot_masks": saved,
            "workspace_current_r": current_r,
            "workspace_snapshot_r": saved_r,
            "r_range": [0.0, rmax],
            "fit": {"status": status, "cov_qual": cov_qual, "edm": edm},
            "shape_extractor_mask_handling": "workspace_masks_one_constant_no_override",
        }
    finally:
        snapshot_file.Close()
        fit_file.Close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("fit_result", type=Path)
    parser.add_argument("--rmax", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError(f"refusing to overwrite output: {args.output}")
    result = validate(args.snapshot, args.fit_result, args.rmax)
    temporary = args.output.with_name(f".{args.output.name}.tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    temporary.replace(args.output)
    print(json.dumps({"MASKED_POSTFIT_SOURCE_OK": True, "fit": result["fit"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, TypeError) as error:
        print(f"MASKED_POSTFIT_SOURCE_FAILED: {error}", file=sys.stderr)
        raise SystemExit(2)
