#!/usr/bin/env python3
"""Cross-verify the 1D methods against the 2DAlphabet limit.

Reads the per-method expected-limit summaries written by the drivers and the
2DAlphabet reference, and produces (a) a markdown comparison table and (b) an
overlay plot of the median expected limit vs mass for

    ①  bumphunt      (oned/out/bumphunt_<cat>.json)
    ②  alphabet1d    (oned/out/alphabet1d_<cat>.json)
    2D  2DAlphabet   (oned/out/twod_ref_<cat>.json)   -- reference, with bands

    python oned/compare.py --cat cen24

Outputs: oned/out/compare_<cat>.png and oned/out/compare_<cat>.md
"""
from __future__ import annotations

import argparse
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
try:
    import mplhep as hep
    plt.style.use(hep.style.CMS)
except Exception:
    pass

KEYS = ["exp_m2", "exp_m1", "exp", "exp_p1", "exp_p2"]


def _load(path):
    return json.load(open(path)) if os.path.exists(path) else {}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cat", default="cen24")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    bh = _load(os.path.join("oned", "out", f"bumphunt_{args.cat}.json"))
    al = _load(os.path.join("oned", "out", f"alphabet1d_{args.cat}.json"))
    td = _load(os.path.join("oned", "out", f"twod_ref_{args.cat}.json"))

    masses = sorted({int(m) for m in list(bh) + list(al) + list(td)})
    if not masses:
        print("[compare] no inputs found in oned/out/; run the drivers first.")
        return 1
    x = [m / 1000.0 for m in masses]

    # --- markdown table ----------------------------------------------------------
    lines = [f"# 1D cross-check vs 2DAlphabet -- {args.cat}", "",
             "Expected 95% CL upper limit on the signal strength r "
             "(r=1 <-> as-run xsec). Lower r = stronger exclusion.", "",
             "| Mass [TeV] | ① bumphunt | ② alphabet1d | 2DAlphabet | ①/2D | ②/2D |",
             "|---|---|---|---|---|---|"]
    for m in masses:
        mb = bh.get(str(m), {}); ma = al.get(str(m), {}); mt = td.get(str(m), {})

        def cell(d):
            if "exp" not in d:
                return "—"
            lo, hi = d.get("exp_m1"), d.get("exp_p1")
            if lo is not None and hi is not None:
                return f"{d['exp']:.3g} (+{hi-d['exp']:.2g}/−{d['exp']-lo:.2g})"
            return f"{d['exp']:.3g}"

        def ratio(d):
            if "exp" in d and "exp" in mt and mt["exp"]:
                return f"{d['exp']/mt['exp']:.2f}"
            return "—"
        lines.append(f"| {m/1000.0:.1f} | {cell(mb)} | {cell(ma)} | {cell(mt)} "
                     f"| {ratio(mb)} | {ratio(ma)} |")
    md = "\n".join(lines) + "\n"
    md_path = os.path.join("oned", "out", f"compare_{args.cat}.md")
    open(md_path, "w").write(md)
    print(md)

    # --- overlay plot ------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(9, 7))

    def series(d, key):
        return [d[str(m)][key] if (str(m) in d and key in d[str(m)]) else None
                for m in masses]

    # 2D reference with brazil bands
    if td:
        xm = [m / 1000.0 for m in masses if str(m) in td]
        med = [td[str(m)]["exp"] for m in masses if str(m) in td]
        if all(k in next(iter(td.values())) for k in KEYS):
            m2 = [td[str(m)]["exp_m2"] for m in masses if str(m) in td]
            p2 = [td[str(m)]["exp_p2"] for m in masses if str(m) in td]
            m1 = [td[str(m)]["exp_m1"] for m in masses if str(m) in td]
            p1 = [td[str(m)]["exp_p1"] for m in masses if str(m) in td]
            ax.fill_between(xm, m2, p2, color="#FFCC00", alpha=0.7, label="2D ±2σ")
            ax.fill_between(xm, m1, p1, color="#00CC00", alpha=0.7, label="2D ±1σ")
        ax.plot(xm, med, "k--", lw=2, label="2DAlphabet median")

    bx = [m / 1000.0 for m in masses if str(m) in bh]
    by = [bh[str(m)]["exp"] for m in masses if str(m) in bh]
    if bx:
        ax.plot(bx, by, "o-", color="#1f77b4", lw=2, ms=8, label="① bump-hunt")
    axx = [m / 1000.0 for m in masses if str(m) in al]
    ayy = [al[str(m)]["exp"] for m in masses if str(m) in al]
    if axx:
        ax.plot(axx, ayy, "s-", color="#d62728", lw=2, ms=8, label="② 1D alphabet")

    ax.set_yscale("log")
    ax.set_xlabel(r"$m_{Z'}$ [TeV]")
    ax.set_ylabel(r"95% CL exp. limit on $r$ ($r{=}1\leftrightarrow$ as-run $\sigma$)")
    ax.set_title(f"1D cross-check vs 2DAlphabet — {args.cat}", fontsize=15, loc="left")
    ax.legend(fontsize=12, ncol=2)
    ax.grid(alpha=0.3, which="both")
    out = args.out or os.path.join("oned", "out", f"compare_{args.cat}.png")
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    print(f"[compare] wrote {md_path} and {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
