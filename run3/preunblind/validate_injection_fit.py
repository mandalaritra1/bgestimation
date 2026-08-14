#!/usr/bin/env python3
"""Gate for boundary-adjacent injection/closure toy fits.

Deliberately different from validate_fit_result.py (the masked-snapshot gate):
these s+b fits sit at or near the physical r=0 boundary, where Minuit routinely
reports status 1 (covariance forced positive-definite) or covQual 2 without the
minimum itself being in doubt. The per-fit gate is therefore status in {0,1},
covQual >= 2, EDM <= 0.01 — and the decisive physics gates (cross-start r-hat
and NLL agreement, injected-vs-recovered linearity with PROFILE errors) are
applied at harvest across all starts, which this looser per-fit gate exists to
keep alive. Never use this gate for the masked background-only snapshot.
"""
import argparse
import sys

import ROOT


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--key", default="fit_mdf")
    parser.add_argument("--min-cov-qual", type=int, default=2)
    parser.add_argument("--max-edm", type=float, default=0.01)
    parser.add_argument("--allowed-status", default="0,1")
    args = parser.parse_args()

    allowed = {int(s) for s in args.allowed_status.split(",")}
    f = ROOT.TFile.Open(args.path)
    if not f or f.IsZombie():
        print(f"INVALID FIT: cannot open {args.path}")
        return 1
    fit_result = f.Get(args.key)
    if not fit_result:
        print(f"INVALID FIT: no {args.key} in {args.path}")
        return 1
    status = int(fit_result.status())
    cov_qual = int(fit_result.covQual())
    edm = float(fit_result.edm())
    print(f"INJECTION FIT CHECK: status={status} covQual={cov_qual} EDM={edm:.6g} "
          f"(allowed_status={sorted(allowed)} min_covQual={args.min_cov_qual} "
          f"max_edm={args.max_edm})")
    if status not in allowed or cov_qual < args.min_cov_qual or edm > args.max_edm:
        print("INVALID FIT: outside the injection-fit acceptance")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
