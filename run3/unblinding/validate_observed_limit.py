#!/usr/bin/env python3
"""Fail closed on a Gate-2 AsymptoticLimits tree: 5 ordered expected
quantiles PLUS exactly one observed entry, all finite/positive, with rMax
headroom on both observed and q97.5 (plan: exceeding 0.9*rMax means raise
that point's rMax one 1-2-5 step and rerun — numerical headroom only)."""

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

    entries = [(float(row.quantileExpected), float(row.limit)) for row in tree]
    observed = [value for q, value in entries if q < 0]
    expected = sorted((q, value) for q, value in entries if q >= 0)
    if len(observed) != 1:
        print(f"INVALID LIMIT: expected exactly one observed entry, found {len(observed)}",
              file=sys.stderr)
        return 4
    if len(expected) != 5:
        print(f"INVALID LIMIT: expected 5 expected entries, found {len(expected)}",
              file=sys.stderr)
        return 5
    target_quantiles = (0.025, 0.16, 0.5, 0.84, 0.975)
    if any(abs(q - t) > 0.01 for (q, _), t in zip(expected, target_quantiles)):
        print(f"INVALID LIMIT: unexpected quantiles {expected}", file=sys.stderr)
        return 6

    values = [value for _, value in expected]
    obs = observed[0]
    if any(not math.isfinite(v) or v <= 0 for v in values + [obs]):
        print(f"INVALID LIMIT: non-positive/non-finite values {values} obs={obs}",
              file=sys.stderr)
        return 7
    if any(right <= left for left, right in zip(values, values[1:])):
        print(f"INVALID LIMIT: expected band not strictly ordered {values}", file=sys.stderr)
        return 8
    median = values[2]
    gaps = [(right - left) / median for left, right in zip(values, values[1:])]
    if any(g < args.min_gap_fraction for g in gaps):
        print(f"INVALID LIMIT: collapsed expected band, gaps/median={gaps}", file=sys.stderr)
        return 9
    ceiling = args.max_rmax_fraction * args.rmax
    if values[-1] >= ceiling or obs >= ceiling:
        print(f"INVALID LIMIT: q97.5={values[-1]:.9g} or observed={obs:.9g} lacks "
              f"headroom below {ceiling:.9g} (raise rMax one 1-2-5 step, rerun point)",
              file=sys.stderr)
        return 10
    print(f"OBSERVED LIMIT OK: obs={obs:.9g} expected={values} obs_over_median={obs/median:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
