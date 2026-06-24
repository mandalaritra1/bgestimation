#!/usr/bin/env python3
"""Harvest 2DAlphabet AsymptoticLimits files into oned/out/twod_ref_<tag>.json.

The σ×B plot (plot_sigmaB.py) needs the 2DAlphabet expected `r` quantiles per
mass as the reference bands. This reads a set of combine AsymptoticLimits ROOT
files (one per mass) and writes them in the same JSON schema the 1D drivers use.

    # files named like <dir>/zp<mass>.root, or give an explicit glob with {m}
    python oned/harvest_twod.py --tag comb --dir ~/recomb_ttag_2d --pattern 'zp{m}.root'
    python oned/harvest_twod.py --tag cen24 \\
        --glob 'output/ttbarfits_cen2024_2x2_signalZPrime{m}/*_area/higgsCombine*AsymptoticLimits*.root'
"""
from __future__ import annotations

import argparse
import glob
import json
import os

import ROOT

ROOT.gROOT.SetBatch(True)
QMAP = {0.025: "exp_m2", 0.16: "exp_m1", 0.5: "exp", 0.84: "exp_p1", 0.975: "exp_p2"}
DEFAULT_MASSES = [1000, 1200, 1400, 1600, 1800, 2000, 2500, 3000, 3500, 4000, 4500, 5000, 6000]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--dir", default=None, help="dir of per-mass files (with --pattern)")
    ap.add_argument("--pattern", default="zp{m}.root", help="filename pattern, {m} = mass")
    ap.add_argument("--glob", default=None, help="explicit glob with {m} placeholder")
    ap.add_argument("--masses", default=None, help="comma list (default 1000..6000 grid)")
    args = ap.parse_args()

    masses = [int(x) for x in args.masses.split(",")] if args.masses else DEFAULT_MASSES
    out = {}
    for m in masses:
        if args.glob:
            cand = glob.glob(args.glob.format(m=m))
        else:
            cand = glob.glob(os.path.join(os.path.expanduser(args.dir),
                                          args.pattern.format(m=m)))
        if not cand:
            continue
        f = ROOT.TFile.Open(sorted(cand)[0])
        t = f.Get("limit")
        d = {}
        for i in range(t.GetEntries()):
            t.GetEntry(i)
            k = QMAP.get(round(t.quantileExpected, 4))
            if k:
                d[k] = float(t.limit)
        f.Close()
        if d:
            out[str(m)] = d

    path = os.path.join("oned", "out", f"twod_ref_{args.tag}.json")
    json.dump(out, open(path, "w"), indent=2, sort_keys=True)
    print(f"[harvest_twod] {path}  ({len(out)} masses: {sorted(out, key=int)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
