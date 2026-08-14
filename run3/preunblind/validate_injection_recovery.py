#!/usr/bin/env python3
"""Fail closed on blinded Asimov-injection recovery and start invariance.

This validator consumes the matrix produced by ``build_injection_matrix.py``
and the three JSON records harvested by ``injection_job.sh`` for every matrix
row.  It never opens a workspace, card, or observed-data result.

The numerical defaults are deliberately explicit implementation defaults, not
analysis-approved closure criteria.  A physics review must choose/approve the
thresholds before this report is used as a pre-unblinding acceptance gate.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable


EXPECTED_STARTS = (
    ("zero", "start_zero"),
    ("injected", "start_injected"),
    ("high", "start_high"),
)


class ValidationError(RuntimeError):
    """Raised when an injection recovery record is incomplete or unacceptable."""


def finite_float(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValidationError(f"{label} must be numeric, not boolean")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValidationError(f"{label} is not numeric: {value!r}") from error
    if not math.isfinite(result):
        raise ValidationError(f"{label} is not finite: {result!r}")
    return result


def integer(value: Any, label: str) -> int:
    number = finite_float(value, label)
    if not number.is_integer():
        raise ValidationError(f"{label} is not integer-valued: {number!r}")
    return int(number)


def mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be a JSON object")
    return value


def close(left: float, right: float, label: str) -> None:
    if not math.isclose(left, right, rel_tol=1.0e-9, abs_tol=1.0e-12):
        raise ValidationError(f"{label} mismatch: {left:.12g} != {right:.12g}")


def row_identity(row: dict[str, Any]) -> tuple[int, int, str]:
    width = integer(row.get("width_percent"), "matrix width_percent")
    mass = integer(row.get("mass_GeV"), "matrix mass_GeV")
    label = row.get("injection_label")
    if not isinstance(label, str) or not label:
        raise ValidationError("matrix injection_label must be a nonempty string")
    return width, mass, label


def load_matrix(path: Path, expected_rows: int) -> list[dict[str, Any]]:
    try:
        document = json.loads(path.read_text())
    except FileNotFoundError as error:
        raise ValidationError(f"missing injection matrix: {path}") from error
    except json.JSONDecodeError as error:
        raise ValidationError(f"invalid injection matrix JSON {path}: {error}") from error
    if not isinstance(document, list):
        raise ValidationError("injection matrix must be a JSON list")
    if len(document) != expected_rows:
        raise ValidationError(
            f"expected exactly {expected_rows} injection rows, found {len(document)}"
        )

    seen: set[tuple[int, int, str]] = set()
    rows: list[dict[str, Any]] = []
    for index, raw_row in enumerate(document):
        row = mapping(raw_row, f"matrix row {index}")
        identity = row_identity(row)
        if identity in seen:
            raise ValidationError(f"duplicate injection matrix row: {identity}")
        seen.add(identity)

        rmax = finite_float(row.get("rMax"), f"matrix row {identity} rMax")
        injected = finite_float(row.get("injected_r"), f"matrix row {identity} injected_r")
        median_r95 = finite_float(
            row.get("median_expected_r95"),
            f"matrix row {identity} median_expected_r95",
        )
        if rmax <= 0.0:
            raise ValidationError(f"matrix row {identity} has non-positive rMax={rmax}")
        if injected < 0.0 or injected >= rmax:
            raise ValidationError(
                f"matrix row {identity} has injected_r outside [0, rMax): {injected}"
            )
        for _, start_key in EXPECTED_STARTS:
            start = finite_float(row.get(start_key), f"matrix row {identity} {start_key}")
            if start < 0.0 or start > rmax:
                raise ValidationError(
                    f"matrix row {identity} has {start_key} outside [0, rMax]: {start}"
                )
        expected_high = min(0.5 * rmax, 3.0 * median_r95)
        close(
            finite_float(row.get("start_high"), f"matrix row {identity} start_high"),
            expected_high,
            f"matrix row {identity} scale-aware high start",
        )
        if row.get("start_high_definition") != "min(0.5*rMax,3*median_expected_r95)":
            raise ValidationError(
                f"matrix row {identity} has an unreviewed high-start definition"
            )
        rows.append(row)
    return rows


def load_record(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text())
    except FileNotFoundError as error:
        raise ValidationError(f"missing harvested fit JSON: {path}") from error
    except json.JSONDecodeError as error:
        raise ValidationError(f"invalid harvested fit JSON {path}: {error}") from error
    return mapping(payload, f"harvested fit JSON {path}")


def validate_record(
    record: dict[str, Any],
    path: Path,
    row: dict[str, Any],
    start_label: str,
    start_key: str,
    min_cov_qual: int,
    max_edm: float,
) -> tuple[float, float, float, dict[str, Any]]:
    identity = row_identity(row)
    metadata = mapping(record.get("metadata"), f"{path} metadata")
    expected_metadata = {
        "width_percent": integer(row["width_percent"], "matrix width_percent"),
        "mass_GeV": integer(row["mass_GeV"], "matrix mass_GeV"),
        "rMax": finite_float(row["rMax"], "matrix rMax"),
        "injection_label": identity[2],
        "injected_r": finite_float(row["injected_r"], "matrix injected_r"),
        "start_label": start_label,
        "start_r": finite_float(row[start_key], f"matrix {start_key}"),
    }
    for key, expected in expected_metadata.items():
        if key not in metadata:
            raise ValidationError(f"{path} metadata missing {key!r}")
        actual = metadata[key]
        if isinstance(expected, str):
            if actual != expected:
                raise ValidationError(f"{path} metadata {key}={actual!r}, expected {expected!r}")
        elif isinstance(expected, int):
            if integer(actual, f"{path} metadata {key}") != expected:
                raise ValidationError(f"{path} metadata {key} does not match matrix")
        else:
            close(finite_float(actual, f"{path} metadata {key}"), expected, f"{path} metadata {key}")

    fit = mapping(record.get("fit"), f"{path} fit")
    status = integer(fit.get("status"), f"{path} fit status")
    cov_qual = integer(fit.get("cov_qual"), f"{path} fit cov_qual")
    edm = finite_float(fit.get("edm"), f"{path} fit edm")
    if status != 0 or cov_qual < min_cov_qual or edm > max_edm:
        raise ValidationError(
            f"{path} failed fit quality: status={status} covQual={cov_qual} EDM={edm:.6g}"
        )

    r_record = mapping(record.get("r"), f"{path} r")
    if r_record.get("name") != "r":
        raise ValidationError(f"{path} r record is not the POI 'r'")
    if r_record.get("constant") is not False:
        raise ValidationError(f"{path} does not prove that r floated in the recovery fit")
    r_min = finite_float(r_record.get("min"), f"{path} r min")
    r_max = finite_float(r_record.get("max"), f"{path} r max")
    close(r_min, 0.0, f"{path} r min")
    close(r_max, finite_float(row["rMax"], "matrix rMax"), f"{path} r max")
    value = finite_float(r_record.get("value"), f"{path} r value")
    error = finite_float(r_record.get("error"), f"{path} r error")
    if error <= 0.0:
        raise ValidationError(f"{path} r error must be positive, got {error}")
    # At r=0 the physically meaningful uncertainty is upward.  Prefer the
    # asymmetric upper error emitted by the harvester, falling back to Hesse's
    # symmetric error when Combine did not provide an asymmetric estimate.
    raw_upper_error = r_record.get("error_high")
    upper_error = error if raw_upper_error is None else finite_float(
        raw_upper_error, f"{path} r error_high"
    )
    if upper_error <= 0.0:
        raise ValidationError(
            f"{path} r upper error must be positive, got {upper_error}"
        )
    boundary = mapping(r_record.get("boundary"), f"{path} r boundary")
    if boundary.get("accessible") is not True:
        raise ValidationError(f"{path} has no accessible r-boundary diagnostics")
    for key in ("outside_bounds", "at_min", "at_max", "near_min", "near_max"):
        if not isinstance(boundary.get(key), bool):
            raise ValidationError(f"{path} r boundary {key} is not boolean")
    if boundary["outside_bounds"] or boundary["near_max"]:
        raise ValidationError(f"{path} fitted r is outside or near its upper bound")
    if finite_float(row["injected_r"], "matrix injected_r") > 0.0 and boundary["near_min"]:
        raise ValidationError(f"{path} nonzero injection fitted r near its lower bound")
    return value, error, upper_error, {
        "status": status, "cov_qual": cov_qual, "edm": edm,
        "r_min": r_min, "r_max": r_max, "r_boundary": boundary,
    }


def evaluate_row(
    row: dict[str, Any],
    injections_root: Path,
    min_cov_qual: int,
    max_edm: float,
    max_abs_recovery_pull: float,
    max_background_positive_pull: float,
    max_start_pair_pull: float,
    max_start_rmax_fraction: float,
    nonnegative_tolerance: float,
) -> dict[str, Any]:
    width, mass, label = row_identity(row)
    rmax = finite_float(row["rMax"], "matrix rMax")
    injected = finite_float(row["injected_r"], "matrix injected_r")
    base = injections_root / f"w{width}" / f"m{mass}" / label
    results: dict[str, dict[str, Any]] = {}

    for start_label, start_key in EXPECTED_STARTS:
        path = base / f"fit_{start_label}.json"
        record = load_record(path)
        value, error, upper_error, quality = validate_record(
            record, path, row, start_label, start_key, min_cov_qual, max_edm
        )
        if value < -nonnegative_tolerance:
            raise ValidationError(f"{path} has unphysical negative r={value:.12g}")
        residual = value - injected
        result: dict[str, Any] = {
            "path": str(path),
            "start_r": finite_float(row[start_key], f"matrix {start_key}"),
            "r_hat": value,
            "r_hat_error": error,
            "residual": residual,
            "fit": quality,
        }
        if injected == 0.0:
            positive_pull = value / upper_error
            result["recovery_test"] = "one_sided_background_positive_pull"
            result["positive_pull"] = positive_pull
            result["one_sided_upper_error"] = upper_error
            if positive_pull > max_background_positive_pull:
                raise ValidationError(
                    f"{path} background injection has positive pull {positive_pull:.6g}, "
                    f"above {max_background_positive_pull:.6g}"
                )
        else:
            pull = residual / error
            result["recovery_test"] = "two_sided_recovery_pull"
            result["recovery_pull"] = pull
            if abs(pull) > max_abs_recovery_pull:
                raise ValidationError(
                    f"{path} recovery pull {pull:.6g}, above absolute threshold "
                    f"{max_abs_recovery_pull:.6g}"
                )
        results[start_label] = result

    pairs = []
    for left_label, right_label in itertools.combinations((item[0] for item in EXPECTED_STARTS), 2):
        left = results[left_label]
        right = results[right_label]
        difference = left["r_hat"] - right["r_hat"]
        combined_error = math.hypot(left["r_hat_error"], right["r_hat_error"])
        pair_pull = abs(difference) / combined_error
        absolute_limit = max_start_rmax_fraction * rmax
        pair = {
            "starts": [left_label, right_label],
            "difference": difference,
            "combined_error": combined_error,
            "pair_pull": pair_pull,
            "absolute_limit": absolute_limit,
        }
        if pair_pull > max_start_pair_pull or abs(difference) > absolute_limit:
            raise ValidationError(
                f"w{width} M{mass} {label} start pair {left_label}/{right_label} "
                f"fails invariance: |delta|={abs(difference):.6g}, pull={pair_pull:.6g}"
            )
        pairs.append(pair)

    return {
        "width_percent": width,
        "mass_GeV": mass,
        "injection_label": label,
        "rMax": rmax,
        "injected_r": injected,
        "fits": results,
        "start_invariance_pairs": pairs,
    }


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix-json", type=Path, required=True)
    parser.add_argument(
        "--injections-root",
        type=Path,
        required=True,
        help="campaign/injections/asimov directory containing w*/m*/label/fit_*.json",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-rows", type=int, default=48)
    parser.add_argument("--min-cov-qual", type=int, default=3)
    parser.add_argument("--max-edm", type=float, default=0.01)
    parser.add_argument(
        "--max-abs-recovery-pull", type=float, default=3.0,
        help="default only; approve for the analysis before use as an acceptance threshold",
    )
    parser.add_argument(
        "--max-background-positive-pull", type=float, default=3.0,
        help="one-sided rInject=0 default only; requires physics approval",
    )
    parser.add_argument(
        "--max-start-pair-pull", type=float, default=3.0,
        help="default only; requires physics approval",
    )
    parser.add_argument(
        "--max-start-rmax-fraction", type=float, default=0.05,
        help="default only; requires physics approval",
    )
    parser.add_argument("--nonnegative-tolerance", type=float, default=1.0e-9)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.expected_rows <= 0 or args.min_cov_qual < 0:
        raise ValidationError("expected-rows must be positive and min-cov-qual non-negative")
    for name in (
        "max_edm",
        "max_abs_recovery_pull",
        "max_background_positive_pull",
        "max_start_pair_pull",
        "max_start_rmax_fraction",
        "nonnegative_tolerance",
    ):
        value = finite_float(getattr(args, name), name)
        if value < 0.0:
            raise ValidationError(f"{name} must be non-negative")

    rows = load_matrix(args.matrix_json, args.expected_rows)
    reports = [
        evaluate_row(
            row,
            args.injections_root,
            args.min_cov_qual,
            args.max_edm,
            args.max_abs_recovery_pull,
            args.max_background_positive_pull,
            args.max_start_pair_pull,
            args.max_start_rmax_fraction,
            args.nonnegative_tolerance,
        )
        for row in rows
    ]
    payload = {
        "schema": "ttbarhadronic.asimov_injection_recovery.v1",
        "accepted": True,
        "matrix_json": str(args.matrix_json.resolve()),
        "injections_root": str(args.injections_root.resolve()),
        "n_rows": len(reports),
        "thresholds": {
            "expected_rows": args.expected_rows,
            "min_cov_qual": args.min_cov_qual,
            "max_edm": args.max_edm,
            "max_abs_recovery_pull": args.max_abs_recovery_pull,
            "max_background_positive_pull": args.max_background_positive_pull,
            "max_start_pair_pull": args.max_start_pair_pull,
            "max_start_rmax_fraction": args.max_start_rmax_fraction,
            "nonnegative_tolerance": args.nonnegative_tolerance,
            "approval_note": "Defaults are implementation defaults and require physics approval.",
        },
        "rows": reports,
    }
    atomic_write_json(args.output, payload)
    print(f"INJECTION_RECOVERY_VALID rows={len(reports)} output={args.output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValidationError as error:
        print(f"INJECTION_RECOVERY_INVALID: {error}", file=os.sys.stderr)
        raise SystemExit(2)
