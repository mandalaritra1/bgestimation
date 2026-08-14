#!/usr/bin/env python3
"""Serialize a saved Combine RooFitResult without silently accepting bad input.

This is deliberately a harvester, not a fit-quality validator: downstream code
can apply analysis-specific status, EDM, and boundary criteria from the emitted
machine-readable record.
"""

import argparse
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import ROOT
except ImportError:  # pragma: no cover - depends on the CMSSW runtime
    ROOT = None


class HarvestError(RuntimeError):
    """Raised for incomplete or non-finite fit information."""


def finite_number(value: Any, label: str) -> float:
    """Return a finite float or refuse to emit a partially valid record."""
    try:
        numeric_value = float(value)
    except (TypeError, ValueError) as error:
        raise HarvestError(f"{label} is not numeric: {value!r}") from error
    if not math.isfinite(numeric_value):
        raise HarvestError(f"{label} is not finite: {numeric_value!r}")
    return numeric_value


def call_finite(object_: Any, method_name: str, label: str) -> float:
    method = getattr(object_, method_name, None)
    if not callable(method):
        raise HarvestError(f"{label} has no {method_name}() accessor")
    return finite_number(method(), f"{label}.{method_name}()")


def call_integer(object_: Any, method_name: str, label: str) -> int:
    """Read a finite integer-valued RooFit diagnostic."""
    numeric_value = call_finite(object_, method_name, label)
    if not numeric_value.is_integer():
        raise HarvestError(f"{label}.{method_name}() is not integer-valued: {numeric_value!r}")
    return int(numeric_value)


def optional_bound(variable: Any, method_name: str, label: str) -> Optional[float]:
    """Read a finite RooRealVar bound; represent an unbounded side as null."""
    method = getattr(variable, method_name, None)
    if not callable(method):
        return None
    raw_value = method()
    try:
        return finite_number(raw_value, f"{label}.{method_name}()")
    except HarvestError as error:
        # RooFit uses +/- infinity for a legitimate unbounded nuisance.  JSON
        # cannot represent that faithfully, so emit null rather than accepting
        # a non-finite numeric value.
        try:
            if math.isinf(float(raw_value)):
                return None
        except (TypeError, ValueError):
            pass
        raise error


def asymmetric_errors(variable: Any, label: str) -> Tuple[Optional[float], Optional[float]]:
    """Return asymmetric errors when RooFit reports that they are available."""
    has_asym = getattr(variable, "hasAsymError", None)
    if callable(has_asym) and not bool(has_asym()):
        return None, None

    low_accessor = next(
        (
            name
            for name in ("getErrorLo", "getAsymErrorLo")
            if callable(getattr(variable, name, None))
        ),
        None,
    )
    high_accessor = next(
        (
            name
            for name in ("getErrorHi", "getAsymErrorHi")
            if callable(getattr(variable, name, None))
        ),
        None,
    )
    if low_accessor is None or high_accessor is None:
        return None, None

    return (
        call_finite(variable, low_accessor, label),
        call_finite(variable, high_accessor, label),
    )


def boundary_record(value: float, minimum: Optional[float], maximum: Optional[float]) -> Dict[str, Any]:
    """Describe proximity to finite RooRealVar bounds using a fixed tolerance."""
    if minimum is None or maximum is None:
        return {
            "accessible": False,
            "outside_bounds": False,
            "at_min": False,
            "at_max": False,
            "near_min": False,
            "near_max": False,
            "tolerance": None,
        }
    if maximum < minimum:
        raise HarvestError(f"invalid bounds: min={minimum} exceeds max={maximum}")

    span = maximum - minimum
    tolerance = max(1.0e-9, 1.0e-6 * span)
    return {
        "accessible": True,
        "outside_bounds": value < minimum or value > maximum,
        "at_min": value == minimum,
        "at_max": value == maximum,
        "near_min": value - minimum <= tolerance,
        "near_max": maximum - value <= tolerance,
        "tolerance": tolerance,
    }


def parameter_record(variable: Any) -> Dict[str, Any]:
    """Extract one final floating parameter with no implicit numeric fallbacks."""
    name = str(variable.GetName())
    label = f"parameter {name!r}"
    value = call_finite(variable, "getVal", label)
    error = call_finite(variable, "getError", label)
    minimum = optional_bound(variable, "getMin", label)
    maximum = optional_bound(variable, "getMax", label)
    error_low, error_high = asymmetric_errors(variable, label)

    constant_accessor = getattr(variable, "isConstant", None)
    if not callable(constant_accessor):
        raise HarvestError(f"{label} has no isConstant() accessor")
    return {
        "name": name,
        "value": value,
        "error": error,
        "error_low": error_low,
        "error_high": error_high,
        "min": minimum,
        "max": maximum,
        "constant": bool(constant_accessor()),
        "boundary": boundary_record(value, minimum, maximum),
    }


def parse_metadata(values: List[str]) -> Dict[str, str]:
    metadata: Dict[str, str] = {}
    for item in values:
        if "=" not in item:
            raise HarvestError(f"metadata must be key=value, got {item!r}")
        key, value = item.split("=", 1)
        if not key:
            raise HarvestError(f"metadata key is empty in {item!r}")
        if key in metadata:
            raise HarvestError(f"duplicate metadata key {key!r}")
        metadata[key] = value
    return metadata


def harvest(root_path: Path, key: str, metadata: Dict[str, str]) -> Dict[str, Any]:
    if ROOT is None:
        raise HarvestError("PyROOT is unavailable; run this inside the CMSSW runtime")

    root_file = ROOT.TFile.Open(str(root_path))
    if not root_file or root_file.IsZombie():
        raise HarvestError(f"cannot open readable ROOT file: {root_path}")
    try:
        fit_result = root_file.Get(key)
        if not fit_result:
            raise HarvestError(f"missing fit result key {key!r} in {root_path}")

        parameters_accessor = getattr(fit_result, "floatParsFinal", None)
        if not callable(parameters_accessor):
            raise HarvestError(f"object at key {key!r} is not a RooFitResult")
        parameters = parameters_accessor()
        if not parameters:
            raise HarvestError(f"fit result {key!r} has no floating parameters")
        records = [parameter_record(parameters.at(index)) for index in range(parameters.getSize())]
        records.sort(key=lambda record: record["name"])
        r_records = [record for record in records if record["name"] == "r"]
        if len(r_records) != 1:
            raise HarvestError(f"fit result {key!r} must contain exactly one floating 'r' parameter")

        return {
            "fit_key": key,
            "input": str(root_path.resolve()),
            "metadata": metadata,
            "fit": {
                "status": call_integer(fit_result, "status", "fit result"),
                "cov_qual": call_integer(fit_result, "covQual", "fit result"),
                "edm": call_finite(fit_result, "edm", "fit result"),
                "min_nll": call_finite(fit_result, "minNll", "fit result"),
            },
            "r": r_records[0],
            "floating_parameters": records,
        }
    finally:
        root_file.Close()


def write_json(record: Dict[str, Any], output: Optional[Path]) -> None:
    payload = json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if output is None:
        sys.stdout.write(payload)
        return

    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=str(output.parent), prefix=f".{output.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as temporary_file:
            temporary_file.write(payload)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_name, output)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root_path", type=Path, help="ROOT file containing a RooFitResult")
    parser.add_argument("--key", default="fit_s", help="RooFitResult key (for example fit_s or fit_mdf)")
    parser.add_argument("--output", type=Path, help="write JSON atomically to this path")
    parser.add_argument(
        "--metadata",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="optional provenance metadata; may be repeated",
    )
    args = parser.parse_args()

    try:
        record = harvest(args.root_path, args.key, parse_metadata(args.metadata))
        write_json(record, args.output)
    except HarvestError as error:
        print(f"HARVEST FAILED: {error}", file=sys.stderr)
        return 2
    except Exception as error:  # PyROOT can raise non-standard accessor errors.
        print(f"HARVEST FAILED: unexpected PyROOT error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
