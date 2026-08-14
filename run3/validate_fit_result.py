#!/usr/bin/env python3
"""Fail closed when a saved Combine fit result is not trustworthy."""

import argparse
import math
import sys

import ROOT


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--key", default="fit_mdf")
    parser.add_argument("--min-cov-qual", type=int, default=3)
    parser.add_argument("--max-edm", type=float, default=0.01)
    args = parser.parse_args()

    root_file = ROOT.TFile.Open(args.path)
    if not root_file or root_file.IsZombie():
        print(f"INVALID FIT: cannot open {args.path}", file=sys.stderr)
        return 2

    fit_result = root_file.Get(args.key)
    if not fit_result:
        print(f"INVALID FIT: missing {args.key} in {args.path}", file=sys.stderr)
        return 3

    status = int(fit_result.status())
    covariance_quality = int(fit_result.covQual())
    edm = float(fit_result.edm())
    print(
        f"FIT CHECK: status={status} covQual={covariance_quality} EDM={edm:.6g}"
    )
    if (
        status != 0
        or covariance_quality < args.min_cov_qual
        or not math.isfinite(edm)
        or edm > args.max_edm
    ):
        print(
            "INVALID FIT: refusing to build expected limits from a failed "
            "or poorly conditioned masked-background snapshot",
            file=sys.stderr,
        )
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
