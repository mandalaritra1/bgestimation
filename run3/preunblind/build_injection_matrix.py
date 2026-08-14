#!/usr/bin/env python3
"""Build the blinded Asimov injection matrix from validated expected limits."""

import argparse
import json
import math
from pathlib import Path

import ROOT


TARGET_QUANTILES = (0.025, 0.16, 0.5, 0.84, 0.975)
SCALES = (
    ("bkg", 0.0),
    ("half", 0.5),
    ("one", 1.0),
    ("two", 2.0),
)


def signal_name(width: int, mass: int) -> str:
    suffix = "" if width == 1 else f"_{width}"
    return f"signalZPrime{mass}{suffix}"


def read_expected(path: Path) -> list[tuple[float, float]]:
    root_file = ROOT.TFile.Open(str(path))
    if not root_file or root_file.IsZombie():
        raise RuntimeError(f"cannot open expected-limit file: {path}")
    tree = root_file.Get("limit")
    if not tree:
        raise RuntimeError(f"missing limit tree: {path}")
    entries = sorted(
        (float(row.quantileExpected), float(row.limit))
        for row in tree
    )
    if len(entries) != 5 or any(q < 0 for q, _ in entries):
        raise RuntimeError(
            f"blinded limit must contain exactly five expected rows: {path}: {entries}"
        )
    if any(abs(q - target) > 0.01 for (q, _), target in zip(entries, TARGET_QUANTILES)):
        raise RuntimeError(f"unexpected quantiles in {path}: {entries}")
    values = [value for _, value in entries]
    if any(not math.isfinite(value) or value <= 0 for value in values):
        raise RuntimeError(f"non-finite or non-positive limits in {path}: {values}")
    if any(right <= left for left, right in zip(values, values[1:])):
        raise RuntimeError(f"unordered expected limits in {path}: {values}")
    return entries


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--points", type=Path, required=True)
    parser.add_argument("--tsv-output", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    args = parser.parse_args()
    for output in (args.tsv_output, args.json_output):
        if output.exists():
            raise RuntimeError(f"refusing to overwrite injection matrix output: {output}")

    rows = []
    for raw_line in args.points.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        width_text, mass_text, rmax_text = line.split()
        width = int(width_text)
        mass = int(mass_text)
        rmax = float(rmax_text)
        signal = signal_name(width, mass)
        limit_path = (
            args.campaign
            / "workspaces"
            / "combined"
            / f"w{width}"
            / f"{signal}_area"
            / "higgsCombine_expected.AsymptoticLimits.mH0.root"
        )
        quantiles = read_expected(limit_path)
        median_r95 = quantiles[2][1]
        halfmax_start = 0.5 * rmax
        if quantiles[-1][1] >= 0.9 * rmax:
            raise RuntimeError(
                f"expected-limit headroom failed for w{width} M{mass}: "
                f"q97={quantiles[-1]} rMax={rmax}"
            )

        for label, scale in SCALES:
            injected = scale * median_r95
            if injected >= 0.9 * rmax:
                raise RuntimeError(
                    f"injection lacks rMax headroom for w{width} M{mass} "
                    f"{label}: injected={injected} rMax={rmax}"
                )
            rows.append(
                {
                    "width_percent": width,
                    "mass_GeV": mass,
                    "signal": signal,
                    "rMax": rmax,
                    "expected_quantiles": {
                        str(q): value for q, value in quantiles
                    },
                    "median_expected_r95": median_r95,
                    "injection_label": label,
                    "injection_scale_r95": scale,
                    "injected_r": injected,
                    "start_zero": 0.0,
                    "start_injected": injected,
                    "start_halfmax": halfmax_start,
                    "start_halfmax_definition": "0.5*rMax",
                    "limit_root": str(limit_path),
                }
            )

    if len(rows) != 48:
        raise RuntimeError(f"expected 48 injection rows, built {len(rows)}")

    args.tsv_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    with args.tsv_output.open("x") as handle:
        handle.write("".join(
            f"{row['width_percent']} {row['mass_GeV']} {row['rMax']:.12g} "
            f"{row['injection_label']} {row['injected_r']:.12g} "
            f"{row['start_zero']:.12g} {row['start_injected']:.12g} "
            f"{row['start_halfmax']:.12g}\n"
            for row in rows
        ))
    with args.json_output.open("x") as handle:
        handle.write(json.dumps(rows, indent=2, sort_keys=True) + "\n")
    print(f"INJECTION_MATRIX_OK rows={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
