#!/usr/bin/env python3
"""Combine cen24 + fwd24 for one 1D method and run the combined blinded limit.

Runs the chosen 1D driver for cen24 and fwd24 (each builds a per-cat,
cat-namespaced datacard + workspace), then `combineCards` them into a single
cen+fwd likelihood and runs a blinded AsymptoticLimits — matching the 2DAlphabet
cen+fwd combination. The combined expected `r` is appended to
oned/out/<method>_comb.json.

    python oned/combine_cats.py --method bumphunt   --signal signalZPrime4000
    python oned/combine_cats.py --method alphabet1d --signal signalZPrime4000 --inputs <recomb_dir>

`--inputs` (optional) is the EOS dir of TTbarAllHad24_*.root passed through to
project_inputs (e.g. the recomb_ttag inputs); default is the baseline dir.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess

import ROOT

ROOT.gROOT.SetBatch(True)
QUANTILES = {0.025: "exp_m2", 0.16: "exp_m1", 0.5: "exp", 0.84: "exp_p1", 0.975: "exp_p2"}
CATS = ("cen24", "fwd24")


def _read_limit(area):
    cand = glob.glob(os.path.join(area, "higgsCombine*.AsymptoticLimits.*.root"))
    if not cand:
        return None
    f = ROOT.TFile.Open(cand[0])
    t = f.Get("limit")
    if not hasattr(t, "GetEntries") or t.GetEntries() == 0:
        return None
    out = {}
    for i in range(t.GetEntries()):
        t.GetEntry(i)
        k = QUANTILES.get(round(t.quantileExpected, 3))
        if k:
            out[k] = float(t.limit)
    f.Close()
    return out or None


def _cards(method, signal):
    """Per-cat datacard paths to feed combineCards."""
    cards = []
    for cat in CATS:
        base = os.path.join("oned", "out", method, cat, signal)
        if method == "bumphunt":
            cards.append(os.path.join(base, "card.txt"))
        else:  # alphabet1d: two region cards per cat (no '_' in channel names)
            cards += [os.path.join(base, f"fail{cat}.txt"),
                      os.path.join(base, f"pass{cat}.txt")]
    return cards


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--method", required=True, choices=["bumphunt", "alphabet1d"])
    ap.add_argument("--signal", default="signalZPrime4000")
    ap.add_argument("--scenario", default="ZPrime_1")
    ap.add_argument("--input-dir", dest="input_dir", default=None,
                    help="EOS dir of TTbarAllHad24_*.root (e.g. the recomb inputs)")
    ap.add_argument("--rMax", type=float, default=None)
    args = ap.parse_args()
    rmax = args.rMax if args.rMax is not None else (50.0 if args.method == "bumphunt" else 20.0)

    # 1) build per-cat cards/workspaces (each driver also runs its own per-cat limit)
    for cat in CATS:
        cmd = ["python", f"oned/{args.method}.py", "--cat", cat,
               "--signal", args.signal, "--scenario", args.scenario]
        if args.input_dir:
            cmd += ["--input-dir", args.input_dir]
        rc = subprocess.run(cmd)
        if rc.returncode != 0:
            print(f"[combine_cats] per-cat {args.method} {cat} failed")
            return 1

    # absolute paths so combineCards writes absolute shape paths (we cd into comb/)
    cards = [os.path.abspath(c) for c in _cards(args.method, args.signal)]
    for c in cards:
        if not os.path.exists(c):
            print(f"[combine_cats] missing card {c}")
            return 1

    comb = os.path.join("oned", "out", args.method, "comb", args.signal)
    os.makedirs(comb, exist_ok=True)
    card_args = " ".join(cards)
    log = f"{comb}/build.log"
    # bump-hunt: fix both discrete pdf_index to the lowest order (what discrete
    # profiling selects on the signal-free Asimov) so the combined expected limit
    # is stable and properly ordered (two free discretes -> degenerate asymptotic).
    setp, freezep = "r=0", ""
    if args.method == "bumphunt":
        setp = "r=0," + ",".join(f"pdf_index_{c}=0" for c in CATS)
        freezep = "--freezeParameters " + ",".join(f"pdf_index_{c}" for c in CATS) + " "
    build = (
        f"combineCards.py {card_args} > {comb}/combined.txt 2> {log} && "
        f"cd {comb} && text2workspace.py combined.txt -o ws.root >> build.log 2>&1 && "
        f"rm -f higgsCombine*.root && "
        f"combine -M AsymptoticLimits -d ws.root --run blind "
        f"--rMin 0 --rMax {rmax} --setParameters {setp} {freezep}"
        f"--cminDefaultMinimizerStrategy 0 -v 0 >> build.log 2>&1"
    )
    subprocess.run(build, shell=True)

    res = _read_limit(comb)
    if res is None:
        print(f"[combine_cats] FAIL combined {args.method} {args.signal}; see {comb}/combine.log")
        return 1
    print(f"[combine_cats] {args.method} cen+fwd {args.signal}  "
          f"exp r = {res['exp']:.4g}  ({res['exp_m1']:.4g} / {res['exp_p1']:.4g})")

    summ_path = os.path.join("oned", "out", f"{args.method}_comb.json")
    summ = json.load(open(summ_path)) if os.path.exists(summ_path) else {}
    mass = "".join(ch for ch in args.signal if ch.isdigit())
    summ[mass] = dict(res, signal=args.signal)
    json.dump(summ, open(summ_path, "w"), indent=2, sort_keys=True)
    print(f"  -> {summ_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
