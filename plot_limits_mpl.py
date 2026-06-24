#!/usr/bin/env python3
"""Brazil-band limit plot with matplotlib/mplhep (CMS style).

Reads the per-mass combined AsymptoticLimits outputs (same as plot_limits.py)
via PyROOT, then draws with mplhep so the axis range, fills and CMS label are
fully under our control (no TGraph SetLimits quirks).

Usage (run in twoD-env on the remote):
  python plot_limits_mpl.py --year 2024 --signal ZPrime --width 1 --blind True \
      --output limits --xmin 1 --xmax 6
"""
import os, glob, json, argparse
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mplhep as hep
try:
    import ROOT
    ROOT.gROOT.SetBatch(True)
except ImportError:
    ROOT = None
    import uproot  # fallback reader when pyROOT is unavailable (e.g. local laptop)

# k-factor on the theory curve. The official ZPrime 13.6 TeV samples quote NO
# k-factor (the cross sections in signal_xs.json are now the raw 13.6 TeV values),
# so this is 1.0. (Was 1.3 inherited from the legacy Run-2 plot_limits.py.)
THEORY_KFACTOR = 1.0

# Reference cross section that r=1 corresponds to, in pb. We follow the Run-2 repo
# convention: signals are NOT rescaled to theory in ttbar.py; the config carries a
# fixed SIGNAL SCALE=0.1 and the 2024 templates are normalized to a generic 10 pb,
# so r=1 <-> 0.1*10 = 1 pb for every mass. sigma*B = mu * SIGREF_PB. (The old code
# multiplied mu by the per-mass `expected` array while the FIT used r=1<->theory --
# an inconsistency that mis-placed the exclusion crossing.)
SIGREF_PB = 1.0

GREEN  = "#607641"   # 68% band (matches ROOT version)
YELLOW = "#F5BB54"   # 95% band

# 5 expected quantiles we expect from AsymptoticLimits
Q = {"m2": 0.025, "m1": 0.16, "med": 0.5, "p1": 0.84, "p2": 0.975}


def _parse_limit_arrays(quantiles, mus):
    out = {}
    for q, mu in zip(quantiles, mus):
        q = round(float(q), 4); mu = float(mu)
        if abs(q - (-1)) < 1e-6:
            out["obs"] = mu
        elif abs(q - 0.025) < 1e-3: out["m2"] = mu
        elif abs(q - 0.16)  < 1e-2: out["m1"] = mu
        elif abs(q - 0.5)   < 1e-3: out["med"] = mu
        elif abs(q - 0.84)  < 1e-2: out["p1"] = mu
        elif abs(q - 0.975) < 1e-3: out["p2"] = mu
    return out if "med" in out else None


def _read_one(f):
    """Read (quantiles, mus) from one AsymptoticLimits root, or None if empty/invalid."""
    try:
        if ROOT is not None:
            tf = ROOT.TFile.Open(f)
            t = tf.Get("limit")
            if not t:
                tf.Close(); return None
            qs = [float(ev.quantileExpected) for ev in t]
            tf.Close()
            tf = ROOT.TFile.Open(f); t = tf.Get("limit")
            mus = [float(ev.limit) for ev in t]
            tf.Close()
            return _parse_limit_arrays(qs, mus)
        else:
            t = uproot.open(f)["limit"]
            return _parse_limit_arrays(t["quantileExpected"].array(library="np"),
                                       t["limit"].array(library="np"))
    except Exception:
        return None


def read_limits(area):
    """Return dict of quantile->mu (and 'obs') from an AsymptoticLimits root, or None.

    Prefers the mH0 snapshot outputs (the current blinded pipeline runs with -m 0),
    falls back to legacy mH120 files, and skips empty/invalid stubs by trying the
    next candidate instead of giving up on the first one.
    """
    g = sorted(glob.glob(os.path.join(area, "higgsCombine*.AsymptoticLimits*.root")))
    # Order: mH0 snapshot files first, then any remaining (legacy mH120, etc.).
    cands = [c for c in g if "mH0" in os.path.basename(c)] + \
            [c for c in g if "mH0" not in os.path.basename(c)]
    for f in cands:
        res = _read_one(f)
        if res is not None:
            return res
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", default="2024")
    ap.add_argument("--signal", default="ZPrime", choices=["RSGluon", "ZPrime", "ZPrime_DM"])
    ap.add_argument("--width", default="1", choices=["1", "10", "30", "DM", ""])
    ap.add_argument("--blind", default="True")
    ap.add_argument("--output", default="limits")
    ap.add_argument("--xmin", type=float, default=1.0)
    ap.add_argument("--xmax", type=float, default=6.0)
    ap.add_argument("--lumi", type=float, default=109.95)
    ap.add_argument("--com", type=float, default=13.6)
    ap.add_argument("--limit-dir", default="output/cards_combined_24",
                    help="directory holding the per-mass <signame>_area/ combine outputs")
    ap.add_argument("--norm", default="expected", choices=["expected", "theory", "onepb"],
                    help="mu->sigma*B reference: 'expected'=r*as-run xsec (repo default; "
                         "use with templates scaled so r=1<->expected); 'theory'=r*theory "
                         "(use with templates scaled so r=1<->theory); 'onepb'=r*ref-pb.")
    ap.add_argument("--ref-pb", type=float, default=1.0,
                    help="Reference xsec in pb for --norm onepb (r=1<->ref-pb). Use 0.001 "
                         "for the 10/30 templates scaled so r=1<->1 fb.")
    args = ap.parse_args()
    blind = str(args.blind).lower() in ("true", "1", "yes")

    xs = json.load(open("jsons/signal_xs.json"))[args.signal + args.width]
    masses_all = xs["mass"]; theory_all = xs["theory"]; expected_all = xs["expected"]

    dir24 = args.limit_dir
    tag = "" if args.width in ("1", "") else "_" + args.width

    m, med, lo68, hi68, lo95, hi95, obs, thy = [], [], [], [], [], [], [], []
    for mass, th, exp in zip(masses_all, theory_all, expected_all):
        area = os.path.join(dir24, "signal{}{}{}_area".format(args.signal, int(mass * 1000), tag))
        lim = read_limits(area)
        if lim is None:
            print("skip {:.3g} TeV: no limit output".format(mass)); continue
        # mu -> sigma*B via the reference xsec that r=1 corresponds to for these cards.
        norm = {"expected": exp, "theory": th * THEORY_KFACTOR, "onepb": args.ref_pb}[args.norm]
        m.append(mass)
        med.append(lim["med"] * norm)
        lo68.append(lim.get("m1", lim["med"]) * norm)
        hi68.append(lim.get("p1", lim["med"]) * norm)
        lo95.append(lim.get("m2", lim["med"]) * norm)
        hi95.append(lim.get("p2", lim["med"]) * norm)
        thy.append(th * THEORY_KFACTOR)
        if not blind and "obs" in lim:
            obs.append(lim["obs"] * norm)
    m = np.array(m)

    # theory curve on a fine grid (log-interp) so it's smooth across the gap
    fine = np.linspace(args.xmin, args.xmax, 400)
    thy_fine = np.exp(np.interp(fine, masses_all, np.log(np.array(theory_all) * THEORY_KFACTOR)))

    plt.style.use(hep.style.CMS)
    fig, ax = plt.subplots()
    sig_tex = {"RSGluon": r"g_{KK}", "ZPrime": r"Z'", "ZPrime_DM": r"Z_{DM}"}[args.signal]

    ax.fill_between(m, lo95, hi95, color=YELLOW, label="95% expected", zorder=1)
    ax.fill_between(m, lo68, hi68, color=GREEN,  label="68% expected", zorder=2)
    ax.plot(m, med, "k--", lw=2, label="Median expected", zorder=4)
    ax.plot(fine, thy_fine, color="blue", lw=3,
            label=r"Theory %s %s%% width" % (sig_tex, args.width or ""), zorder=3)
    if not blind and len(obs) == len(m):
        ax.plot(m, obs, "ko-", lw=2, label="Observed", zorder=5)

    ax.set_yscale("log")
    ax.set_xlim(args.xmin, args.xmax)
    ax.set_ylim(1e-4, 1e4)
    ax.set_xlabel(r"$m_{%s}$ [TeV]" % sig_tex)
    ax.set_ylabel(r"$\sigma \times B(%s \to t\bar{t})$ [pb]" % sig_tex)
    ax.legend(loc="upper right", title="95% CL upper limits", fontsize=18)
    hep.cms.label("Preliminary", data=True, lumi=args.lumi, com=args.com, ax=ax)

    os.makedirs(args.output, exist_ok=True)
    base = os.path.join(args.output, "limits_{}{}_{}_mpl".format(args.signal, args.width, args.year))
    for ext in ("png", "pdf"):
        fig.savefig(base + "." + ext, bbox_inches="tight")
    print("saved", base + ".png / .pdf")

    # expected mass-limit crossing (median sigma vs theory)
    if len(m) > 1:
        # theory at each measured mass via log-space interpolation. np.interp on
        # log(theory) already returns log(theory_at_m), so do NOT take log() again
        # (the old double-log gave log of a negative number -> NaN crossings).
        log_theory_at_m = np.interp(m, masses_all, np.log(np.array(theory_all) * THEORY_KFACTOR))
        diff = np.log(np.array(med)) - log_theory_at_m
        sgn = np.sign(diff)
        cross = np.where(np.diff(sgn) != 0)[0]
        for i in cross:
            # linear interp in mass at the sign change
            x0, x1 = m[i], m[i + 1]; d0, d1 = diff[i], diff[i + 1]
            mx = x0 - d0 * (x1 - x0) / (d1 - d0)
            print("expected exclusion crossing ~ {:.2f} TeV".format(mx))


if __name__ == "__main__":
    main()
