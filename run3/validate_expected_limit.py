#!/usr/bin/env python3
"""Fail closed on a blinded AsymptoticLimits expected-only ROOT tree."""

import argparse
import math
import sys

import ROOT


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--rmax", type=float, required=True)
    parser.add_argument("--max-rmax-fraction", type=float, default=0.9)
    parser.add_argument("--min-gap-fraction", type=float, default=0.01)
    args = parser.parse_args()

    root_file = ROOT.TFile.Open(args.path)
    if not root_file or root_file.IsZombie():
        print(f"INVALID LIMIT: cannot open {args.path}", file=sys.stderr)
        return 2
    tree = root_file.Get("limit")
    if not tree:
        print(f"INVALID LIMIT: missing limit tree in {args.path}", file=sys.stderr)
        return 3

    entries = [
        (float(row.quantileExpected), float(row.limit))
        for row in tree
    ]
    observed_entries = [entry for entry in entries if entry[0] < 0]
    if observed_entries:
        print(
            "INVALID LIMIT: observed entries are forbidden in this blinded "
            f"campaign: {observed_entries}",
            file=sys.stderr,
        )
        return 4

    entries.sort()
    target_quantiles = (0.025, 0.16, 0.5, 0.84, 0.975)
    if len(entries) != 5:
        print(
            "INVALID LIMIT: expected the entire tree to contain exactly 5 "
            f"expected entries, found {len(entries)}",
            file=sys.stderr,
        )
        return 5
    if any(abs(q - target) > 0.01 for (q, _), target in zip(entries, target_quantiles)):
        print(f"INVALID LIMIT: unexpected quantiles {entries}", file=sys.stderr)
        return 6

    values = [value for _, value in entries]
    if any(not math.isfinite(value) or value <= 0 for value in values):
        print(f"INVALID LIMIT: non-positive or non-finite values {values}", file=sys.stderr)
        return 7
    if any(right <= left for left, right in zip(values, values[1:])):
        print(f"INVALID LIMIT: expected band is not strictly ordered {values}", file=sys.stderr)
        return 8
    median = values[2]
    relative_gaps = [
        (right - left) / median
        for left, right in zip(values, values[1:])
    ]
    if any(gap < args.min_gap_fraction for gap in relative_gaps):
        print(
            f"INVALID LIMIT: collapsed expected band, gaps/median={relative_gaps}",
            file=sys.stderr,
        )
        return 9
    if values[-1] >= args.max_rmax_fraction * args.rmax:
        print(
            f"INVALID LIMIT: p97.5={values[-1]:.9g} lacks headroom below "
            f"{args.max_rmax_fraction:g}*rMax="
            f"{args.max_rmax_fraction * args.rmax:.9g}",
            file=sys.stderr,
        )
        return 10

    print(
        "LIMIT CHECK: "
        + " ".join(f"q{q:g}={value:.10g}" for q, value in entries)
        + f" p97/rMax={values[-1] / args.rmax:.6g}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
