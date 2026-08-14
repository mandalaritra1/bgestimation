#!/usr/bin/env python3
"""Harvest blinded masked-background fit diagnostics without reading data yields."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
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


def finite(value: float, label: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} is not finite: {result}")
    return result


def finite_bound(value: float) -> float | None:
    result = float(value)
    return result if math.isfinite(result) else None


def parameter_record(parameter) -> dict[str, object]:
    value = finite(parameter.getVal(), f"{parameter.GetName()} value")
    error = finite(parameter.getError(), f"{parameter.GetName()} error")
    minimum = finite_bound(parameter.getMin())
    maximum = finite_bound(parameter.getMax())
    lower_sigma = None if error <= 0 or minimum is None else (value - minimum) / error
    upper_sigma = None if error <= 0 or maximum is None else (maximum - value) / error
    return {
        "name": parameter.GetName(),
        "value": value,
        "error": error,
        "range": [minimum, maximum],
        "distance_to_lower_in_sigma": lower_sigma,
        "distance_to_upper_in_sigma": upper_sigma,
        "near_boundary": bool(
            error > 0 and (
                lower_sigma is not None and lower_sigma < 0.1
                or upper_sigma is not None and upper_sigma < 0.1
            )
        ),
    }


def arg_map(collection) -> dict[str, object]:
    return {collection.at(index).GetName(): collection.at(index)
            for index in range(collection.getSize())}


def validate_snapshot(ROOT, path: Path, expected_rmax: float) -> dict[str, object]:
    root_file = ROOT.TFile.Open(str(path))
    if not root_file or root_file.IsZombie():
        raise ValueError(f"cannot open masked snapshot: {path}")
    try:
        workspace = root_file.Get("w")
        if not workspace or not workspace.getSnapshot("MultiDimFit"):
            raise ValueError("masked ROOT lacks workspace w or MultiDimFit snapshot")
        workspace.loadSnapshot("MultiDimFit")
        r = workspace.var("r")
        if not r or not r.isConstant() or not math.isclose(float(r.getVal()), 0.0, abs_tol=1e-12):
            raise ValueError("masked snapshot does not fix r=0")
        if not math.isclose(float(r.getMin()), 0.0, abs_tol=1e-12):
            raise ValueError("masked snapshot rMin is not zero")
        if not math.isclose(float(r.getMax()), expected_rmax, abs_tol=1e-12):
            raise ValueError("masked snapshot rMax mismatch")
        mask_state = {}
        for name in MASKS:
            variable = workspace.var(name)
            if not variable or not variable.isConstant() or not math.isclose(float(variable.getVal()), 1.0, abs_tol=1e-12):
                raise ValueError(f"masked snapshot does not freeze {name}=1")
            mask_state[name] = {"value": 1.0, "constant": True}
        model_config = workspace.obj("ModelConfig")
        nuisances = model_config.GetNuisanceParameters() if model_config else None
        nuisance_names: list[str] = []
        if nuisances:
            iterator = nuisances.createIterator()
            while True:
                variable = iterator.Next()
                if not variable:
                    break
                nuisance_names.append(variable.GetName())
        nuisance_names.sort()
        return {
            "sha256": sha256_file(path),
            "snapshot_name": "MultiDimFit",
            "r": {"value": 0.0, "range": [0.0, expected_rmax], "constant": True},
            "masked_channels": list(MASKS),
            "mask_state": mask_state,
            "model_config_nuisances": nuisance_names,
        }
    finally:
        root_file.Close()


def harvest_prefit_nuisances(ROOT, path: Path) -> tuple[dict[str, dict[str, object]], str]:
    root_file = ROOT.TFile.Open(str(path))
    if not root_file or root_file.IsZombie():
        raise ValueError(f"cannot open prefit workspace: {path}")
    try:
        workspace = root_file.Get("w")
        model_config = workspace.obj("ModelConfig") if workspace else None
        nuisances = model_config.GetNuisanceParameters() if model_config else None
        if not nuisances:
            raise ValueError("prefit workspace lacks ModelConfig nuisances")
        records: dict[str, dict[str, object]] = {}
        iterator = nuisances.createIterator()
        while True:
            variable = iterator.Next()
            if not variable:
                break
            records[variable.GetName()] = parameter_record(variable)
        expected = {"lumi24", "lumi25", "ttbar_xsec"}
        if set(records) != expected:
            raise ValueError(f"unexpected prefit nuisance set: {sorted(records)}")
        for name, record in records.items():
            if float(record["error"]) <= 0:
                raise ValueError(f"non-positive prefit uncertainty for {name}")
        return records, sha256_file(path)
    finally:
        root_file.Close()


def harvest_fit(
    ROOT, path: Path, prefit_nuisances: dict[str, dict[str, object]]
) -> dict[str, object]:
    root_file = ROOT.TFile.Open(str(path))
    if not root_file or root_file.IsZombie():
        raise ValueError(f"cannot open fit result: {path}")
    try:
        fit = root_file.Get("fit_mdf")
        if not fit:
            raise ValueError("fit result lacks fit_mdf")
        status = int(fit.status())
        cov_qual = int(fit.covQual())
        edm = finite(fit.edm(), "EDM")
        min_nll = finite(fit.minNll(), "minNll")
        if status != 0 or cov_qual < 3 or edm > 0.01:
            raise ValueError(
                f"untrusted fit status={status} covQual={cov_qual} EDM={edm}"
            )
        final = arg_map(fit.floatParsFinal())
        rpf_names = sorted(name for name in final if "rpf_par" in name)
        if len(rpf_names) != 18:
            raise ValueError(f"expected 18 RPF coefficients, found {len(rpf_names)}")
        qcd_bin_names = sorted(
            name for name in final
            if name.startswith("QCD_") and "Fail_Region" in name and "_bin_" in name
        )
        high_level_names = sorted(
            set(rpf_names) | {name for name in ("lumi24", "lumi25", "ttbar_xsec") if name in final}
        )
        if len(high_level_names) != 21:
            raise ValueError(
                f"expected 18 RPF plus three constrained parameters, found {len(high_level_names)}"
            )
        constrained = []
        for name in ("lumi24", "lumi25", "ttbar_xsec"):
            if name not in prefit_nuisances or name not in final:
                raise ValueError(f"missing constrained nuisance {name}")
            before = prefit_nuisances[name]
            after = parameter_record(final[name])
            initial_error = float(before["error"])
            constrained.append({
                "name": name,
                "prefit": before,
                "postfit": after,
                "pull": None if initial_error <= 0 else
                    (float(after["value"]) - float(before["value"])) / initial_error,
                "constraint": None if initial_error <= 0 else
                    float(after["error"]) / initial_error,
            })
        correlation = {
            row: {column: finite(fit.correlation(row, column), f"corr({row},{column})")
                  for column in high_level_names}
            for row in high_level_names
        }
        all_names = sorted(final)
        top_correlations = {}
        for name in high_level_names:
            ranked = sorted(
                ((other, abs(finite(fit.correlation(name, other), f"corr({name},{other})")),
                  finite(fit.correlation(name, other), f"corr({name},{other})"))
                 for other in all_names if other != name),
                key=lambda item: item[1],
                reverse=True,
            )[:5]
            top_correlations[name] = [
                {"parameter": other, "correlation": signed} for other, _, signed in ranked
            ]
        qcd_records = [parameter_record(final[name]) for name in qcd_bin_names]
        return {
            "sha256": sha256_file(path),
            "fit_key": "fit_mdf",
            "quality": {
                "status": status,
                "cov_qual": cov_qual,
                "edm": edm,
                "min_nll": min_nll,
            },
            "floating_parameter_count": len(final),
            "constrained_nuisances": constrained,
            "rpf_coefficients": [parameter_record(final[name]) for name in rpf_names],
            "qcd_bin_parameters": {
                "count": len(qcd_records),
                "near_boundary_count": sum(bool(record["near_boundary"]) for record in qcd_records),
                "near_boundary_names": [record["name"] for record in qcd_records if record["near_boundary"]],
            },
            "high_level_parameter_order": high_level_names,
            "high_level_correlation": correlation,
            "top_correlations": top_correlations,
        }
    finally:
        root_file.Close()


def write_atomic(payload: dict[str, object], output: Path) -> None:
    if output.exists():
        raise ValueError(f"refusing to overwrite output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp.{os.getpid()}")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--fit-result", type=Path, required=True)
    parser.add_argument("--prefit-workspace", type=Path, required=True)
    parser.add_argument("--rmax", type=float, required=True)
    parser.add_argument("--width", type=int, required=True, choices=(1, 10, 30))
    parser.add_argument("--mass", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not math.isfinite(args.rmax) or args.rmax <= 0 or args.mass <= 0:
        raise ValueError("invalid rMax or mass")
    try:
        import ROOT
    except ImportError as error:
        raise ValueError("PyROOT is required") from error
    ROOT.gROOT.SetBatch(True)
    if ROOT.gSystem.Load("libHiggsAnalysisCombinedLimit.so") < 0:
        raise ValueError("failed to load libHiggsAnalysisCombinedLimit.so")
    prefit_nuisances, prefit_sha256 = harvest_prefit_nuisances(
        ROOT, args.prefit_workspace
    )
    payload = {
        "schema_version": 1,
        "dataset_scope": "masked_observed_sidebands_only",
        "width_percent": args.width,
        "mass_GeV": args.mass,
        "rMax": args.rmax,
        "prefit_workspace": {
            "sha256": prefit_sha256,
            "model_config_nuisances": prefit_nuisances,
        },
        "snapshot": validate_snapshot(ROOT, args.snapshot, args.rmax),
        "fit": harvest_fit(ROOT, args.fit_result, prefit_nuisances),
        "interpretation_boundary": {
            "confirmed": "Only the four Pass Region1 channels are masked in this fit.",
            "not_inferred": "Fit quality alone is not evidence that the background model is physically sufficient.",
        },
    }
    write_atomic(payload, args.output)
    print(f"MASKED_FIT_DIAGNOSTICS_OK output={args.output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as error:
        print(f"MASKED_FIT_DIAGNOSTICS_FAILED: {error}", file=sys.stderr)
        raise SystemExit(2)
