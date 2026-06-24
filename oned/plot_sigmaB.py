#!/usr/bin/env python3
"""σ×B brazil-band plot of the 1D cross-check vs 2DAlphabet, with theory overlays.

Converts the blinded expected `r` limits (from the method JSONs written by the
drivers / harvested for the 2D) to **σ×B|95 = r95 · expected_xsec(m)** — the
physical limit, since `r=1 ⇔ as-run (expected) xsec` for all three methods — and
draws them CMS-"Preliminary" style:

  - 2DAlphabet median + 68% (green) + 95% (yellow) expected bands,
  - bump-hunt ① and 1D-alphabet ② medians overlaid,
  - theory lines: MadGraph topcolor (red) and XSDB Par (blue),

and reports the expected exclusion crossing of each method against each theory.

    python oned/plot_sigmaB.py --tag comb        # reads *_comb.json
    python oned/plot_sigmaB.py --tag cen24

Inputs (oned/out/): bumphunt_<tag>.json, alphabet1d_<tag>.json, twod_ref_<tag>.json
(any subset). Theory: jsons/signal_xs.json (ZPrime1.expected + .theory=XSDB Par)
and topcolor_xsec/overlay_pure_topcolor.json (ZPrime1.theory = MadGraph topcolor).
"""
from __future__ import annotations

import argparse
import json
import os

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
try:
    import mplhep as hep
    plt.style.use(hep.style.CMS)
    HAVE_HEP = True
except Exception:
    HAVE_HEP = False

YELLOW, GREEN = "#f5bb54", "#4f9d4f"


def _load(path):
    return json.load(open(path)) if os.path.exists(path) else {}


def _xsec_interp(mass_tev, masses, xs):
    """Log-linear interp of an xsec table at mass_tev (exact if a node matches)."""
    for m, x in zip(masses, xs):
        if abs(m - mass_tev) < 1e-6:
            return x
    return float(np.exp(np.interp(mass_tev, masses, np.log(xs))))


def _sigmaB(d, expected_tab, key):
    """[(mass_tev, sigmaB)] for quantile `key` from an r-limit JSON."""
    masses, xs = expected_tab
    out = []
    for ms in sorted(d, key=int):
        if key not in d[ms]:
            continue
        m = int(ms) / 1000.0
        out.append((m, d[ms][key] * _xsec_interp(m, masses, xs)))
    return out


def _crossings(xs_m, lim, th_m, th):
    """Masses where theory (interp to xs_m) crosses below σ×B|95 (log space)."""
    th_i = np.array([_xsec_interp(m, th_m, th) for m in xs_m])
    diff = np.log(th_i) - np.log(np.array(lim))
    s = np.sign(diff)
    out = []
    for i in np.where(np.diff(s) != 0)[0]:
        x0, x1, d0, d1 = xs_m[i], xs_m[i + 1], diff[i], diff[i + 1]
        out.append(x0 - d0 * (x1 - x0) / (d1 - d0))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tag", default="comb", help="JSON suffix (comb, cen24, fwd24)")
    ap.add_argument("--lumi", default="109.95", help="lumi text [fb^-1]")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    sigxs = json.load(open("jsons/signal_xs.json"))["ZPrime1"]
    expected_tab = (sigxs["mass"], sigxs["expected"])     # r=1 <-> these
    xsdb = (sigxs["mass"], sigxs["theory"])               # XSDB Par (blue)
    tc = json.load(open("jsons/topcolor_overlay_pure.json"))["ZPrime1"]
    topcolor = (tc["mass"], tc["theory"])                 # MadGraph topcolor (red)

    bh = _load(f"oned/out/bumphunt_{args.tag}.json")
    al = _load(f"oned/out/alphabet1d_{args.tag}.json")
    td = _load(f"oned/out/twod_ref_{args.tag}.json")

    fig, ax = plt.subplots(figsize=(8.5, 8))

    # 2D brazil bands
    if td:
        med = _sigmaB(td, expected_tab, "exp")
        xm = [m for m, _ in med]
        if med and all(k in next(iter(td.values())) for k in ("exp_m2", "exp_p2")):
            m2 = [v for _, v in _sigmaB(td, expected_tab, "exp_m2")]
            p2 = [v for _, v in _sigmaB(td, expected_tab, "exp_p2")]
            m1 = [v for _, v in _sigmaB(td, expected_tab, "exp_m1")]
            p1 = [v for _, v in _sigmaB(td, expected_tab, "exp_p1")]
            ax.fill_between(xm, m2, p2, color=YELLOW, label="95% expected")
            ax.fill_between(xm, m1, p1, color=GREEN, label="68% expected")
        ax.plot(xm, [v for _, v in med], "k--", lw=2,
                label=r"2DAlphabet median $\sigma\times B|_{95}$")

    if bh:
        s = _sigmaB(bh, expected_tab, "exp")
        ax.plot([m for m, _ in s], [v for _, v in s], "o-", color="#1f77b4",
                lw=2, ms=7, label="① bump-hunt")
    if al:
        s = _sigmaB(al, expected_tab, "exp")
        ax.plot([m for m, _ in s], [v for _, v in s], "s-", color="#d62728",
                lw=2, ms=7, label="② 1D alphabet")

    # theory lines (full grid up to 6 TeV)
    grid = [m for m in topcolor[0] if 1.0 <= m <= 6.0]
    ax.plot(grid, [_xsec_interp(m, *topcolor) for m in grid], "-", color="red",
            lw=2.2, marker=".", label="MadGraph topcolor 1%")
    ax.plot(grid, [_xsec_interp(m, *xsdb) for m in grid], "-", color="blue",
            lw=2.2, marker=".", label="XSDB Par 1%")

    ax.set_yscale("log")
    ax.set_xlim(1, 6)
    ax.set_ylim(1e-4, 1e4)
    ax.set_xlabel(r"$m_{Z'}$ [TeV]")
    ax.set_ylabel(r"$\sigma\times B(Z'\to t\bar t)$ [pb]")
    if HAVE_HEP:
        hep.cms.label("Preliminary", data=True, lumi=args.lumi, com="13.6", ax=ax)
    ax.text(0.05, 0.93, "1% width  (95% CL)", transform=ax.transAxes,
            fontsize=14, fontweight="bold")
    ax.legend(fontsize=10.5, loc="upper right", framealpha=0.9)
    out = args.out or f"oned/out/sigmaB_{args.tag}.png"
    fig.tight_layout()
    fig.savefig(out, dpi=130)

    # crossings report
    print(f"[plot_sigmaB] {out}")
    for name, d in (("① bump-hunt", bh), ("② 1D alphabet", al), ("2DAlphabet", td)):
        if not d:
            continue
        s = _sigmaB(d, expected_tab, "exp")
        xm = [m for m, _ in s]; lim = [v for _, v in s]
        cx_tc = _crossings(xm, lim, *topcolor)
        cx_xs = _crossings(xm, lim, *xsdb)
        fmt = lambda c: ", ".join(f"{v:.2f}" for v in c) if c else "none in range"
        print(f"  {name:16s}  excl. crossing  topcolor: [{fmt(cx_tc)}] TeV   "
              f"XSDB: [{fmt(cx_xs)}] TeV")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
