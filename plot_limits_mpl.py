#!/usr/bin/env python3
"""Brazil-band limit plot with matplotlib/mplhep (CMS style).

Reads the per-mass combined AsymptoticLimits outputs (same as plot_limits.py)
via PyROOT, then draws with mplhep so the axis range, fills and CMS label are
fully under our control (no TGraph SetLimits quirks).

Usage (run in twoD-env on the remote):
  python plot_limits_mpl.py --year 2024 --signal ZPrime --width 1 --blind True \
      --output limits --xmin 1.2 --xmax 6
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

GREEN  = "#228b22"   # 68% expected band
YELLOW = "#ffcc00"   # 95% expected band

# 5 expected quantiles we expect from AsymptoticLimits
Q = {"m2": 0.025, "m1": 0.16, "med": 0.5, "p1": 0.84, "p2": 0.975}


def validate_expected_band(limit_values, mass_tev, min_gap_fraction):
    """Reject incomplete or numerically collapsed expected-limit bands."""
    keys = ("m2", "m1", "med", "p1", "p2")
    missing = [key for key in keys if key not in limit_values]
    if missing:
        raise RuntimeError(
            f"{mass_tev:g} TeV: missing expected quantiles {missing}"
        )
    values = np.asarray([limit_values[key] for key in keys], dtype=float)
    if not np.all(np.isfinite(values)) or np.any(values <= 0):
        raise RuntimeError(
            f"{mass_tev:g} TeV: expected quantiles are not finite and positive: "
            f"{values.tolist()}"
        )
    gaps = np.diff(values)
    if np.any(gaps <= 0):
        raise RuntimeError(
            f"{mass_tev:g} TeV: expected quantiles are not strictly ordered: "
            f"{values.tolist()}"
        )
    relative_gaps = gaps / values[2]
    if np.any(relative_gaps < min_gap_fraction):
        raise RuntimeError(
            f"{mass_tev:g} TeV: expected band is numerically collapsed; "
            f"adjacent gaps / median = {relative_gaps.tolist()}"
        )


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


def provenance_stamp(extra=None):
    """Small provenance line for the plot corner: date + bgestimation version +
    input provenance. Convention (2026-07-31): every working plot carries date,
    skimmer input tag and bgestimation version/commit. Input tag from
    $TTBAR_INPUT_TAG (e.g. "inputs: skimmer v1 / 2dAlphabetInputs_2425").
    Strip for publication-final figures only."""
    import subprocess, datetime
    try:
        bg = subprocess.run(["git", "describe", "--tags", "--always", "--dirty"],
                            capture_output=True, text=True,
                            cwd=os.path.dirname(os.path.abspath(__file__))).stdout.strip()
    except Exception:
        bg = "unknown"
    parts = [datetime.date.today().isoformat(), "bgestimation " + (bg or "unknown")]
    tag = os.environ.get("TTBAR_INPUT_TAG")
    if tag:
        parts.append(tag)
    if extra:
        parts.append(extra)
    return "  |  ".join(parts)


def stamp_figure(fig, extra=None):
    """No-op when stamping is disabled (--no-stamp or $TTBAR_NO_STAMP=1) --
    publication-final figures must go out unstamped."""
    if os.environ.get("TTBAR_NO_STAMP"):
        return
    fig.text(0.99, 0.002, provenance_stamp(extra), ha="right", va="bottom",
             fontsize=7, color="0.45", family="monospace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", default="2024")
    ap.add_argument("--signal", default="ZPrime", choices=["RSGluon", "ZPrime", "ZPrime_DM"])
    ap.add_argument("--width", default="1", choices=["1", "10", "30", "DM", ""])
    ap.add_argument("--blind", default="True")
    ap.add_argument("--output", default="limits")
    ap.add_argument("--xmin", type=float, default=1.0)
    ap.add_argument("--xmax", type=float, default=6.0)
    ap.add_argument("--lumi", type=float, default=None,
                    help="Integrated luminosity in fb^-1. Defaults to 220.54 for "
                         "--year 2425 and 109.95 otherwise.")
    ap.add_argument("--com", type=float, default=13.6)
    ap.add_argument("--limit-dir", default="output/cards_combined_24",
                    help="directory holding the per-mass <signame>_area/ combine outputs")
    ap.add_argument("--norm", default="expected", choices=["expected", "theory", "onepb"],
                    help="mu->sigma*B reference: 'expected'=r*as-run xsec (repo default; "
                         "use with templates scaled so r=1<->expected); 'theory'=r*theory "
                         "(use with templates scaled so r=1<->theory); 'onepb'=r*ref-pb.")
    ap.add_argument("--ref-pb", type=float, default=1.0,
                    help="Reference xsec in pb for --norm onepb (r=1<->ref-pb). "
                         "The v1 2024+2025 cards use 1.0 pb for every width.")
    ap.add_argument("--min-band-gap-fraction", type=float, default=0.01,
                    help="Fail if any adjacent expected-quantile gap is smaller than "
                         "this fraction of the median (default: 0.01).")
    ap.add_argument("--allow-nonstandard-normalization", action="store_true",
                    help="Allow a 2425 plot whose normalization is not the v1 "
                         "r=1 <-> 1 pb convention.")
    ap.add_argument("--overlay-theory-json", default=None,
                    help="Optional SECOND theory curve to overlay (e.g. topcolor "
                         "overlay_pure_topcolor.json). Read [<signal><width>]['theory']. "
                         "Bands are UNCHANGED (still r95 x expected); only an extra "
                         "theory line + its crossing are added.")
    ap.add_argument("--overlay-label", default="MadGraph topcolor (LO)",
                    help="Legend label for the --overlay-theory-json curve.")
    ap.add_argument("--theory-json", default=None,
                    help="Override the PRIMARY (blue) theory curve source (default "
                         "signal_xs.json). Read [<signal><width>]['theory']+['mass']; band "
                         "normalization still uses signal_xs.json 'expected'. Use e.g. "
                         "topcolor_xsec/overlay_pure_topcolor.json for a topcolor-only plot.")
    ap.add_argument("--no-stamp", action="store_true",
                    help="Suppress the provenance stamp (publication-final figures).")
    ap.add_argument("--theory-label", default=None,
                    help="Legend label for the primary theory curve (overrides the default).")
    args = ap.parse_args()
    if args.lumi is None:
        args.lumi = 220.54 if str(args.year) == "2425" else 109.95
    if (str(args.year) == "2425" and
            (args.norm != "onepb" or not np.isclose(args.ref_pb, 1.0)) and
            not args.allow_nonstandard_normalization):
        raise RuntimeError(
            "The v1 2024+2025 cards use r=1 <-> 1 pb. Pass --norm onepb "
            "--ref-pb 1.0, or explicitly opt into a nonstandard study with "
            "--allow-nonstandard-normalization."
        )
    blind = str(args.blind).lower() in ("true", "1", "yes")

    xs = json.load(open("jsons/signal_xs.json"))[args.signal + args.width]
    masses_all = xs["mass"]; theory_all = xs["theory"]; expected_all = xs["expected"]
    if args.theory_json:
        tj = json.load(open(args.theory_json))[args.signal + args.width]
        # align the override theory onto this plot's mass grid (log-interp); bands still
        # use signal_xs.json 'expected' (the as-run norm the fit used), unchanged.
        theory_all = list(np.exp(np.interp(
            np.array(masses_all), np.array(tj["mass"]), np.log(np.array(tj["theory"])))))

    dir24 = args.limit_dir
    tag = "" if args.width in ("1", "") else "_" + args.width

    # Scan masses = union of the signal_xs.json grid and whatever limit areas exist
    # in --limit-dir (the JSON grid predates the sub-TeV points, e.g. 400-900 GeV).
    # theory/expected at masses outside the JSON grid are log-extrapolated, matching
    # ttbar.py's theory_xsec() convention.
    import re as _re
    found = set()
    for d in glob.glob(os.path.join(dir24, "signal{}*{}_area".format(args.signal, tag))):
        mm = _re.match(r"signal%s(\d+)%s_area$" % (args.signal, tag), os.path.basename(d))
        if mm:
            found.add(int(mm.group(1)) / 1000.0)
    # Treat the displayed x range as the reporting domain, not just a viewport
    # crop. This prevents excluded hypotheses from contributing hidden band
    # interpolation or spurious low-mass crossing messages.
    scan = [
        mass for mass in sorted(set(masses_all) | found)
        if args.xmin <= mass <= args.xmax
    ]
    _ma = np.array(masses_all, dtype=float)

    def _logext(grid_vals, mass):
        gv = np.log(np.array(grid_vals, dtype=float))
        if mass <= _ma[0]:
            slope = (gv[1] - gv[0]) / (_ma[1] - _ma[0])
            return float(np.exp(gv[0] + slope * (mass - _ma[0])))
        if mass >= _ma[-1]:
            slope = (gv[-1] - gv[-2]) / (_ma[-1] - _ma[-2])
            return float(np.exp(gv[-1] + slope * (mass - _ma[-1])))
        return float(np.exp(np.interp(mass, _ma, gv)))

    m, med, lo68, hi68, lo95, hi95, obs, thy = [], [], [], [], [], [], [], []
    for mass in scan:
        th = _logext(theory_all, mass)
        exp = _logext(expected_all, mass)
        area = os.path.join(dir24, "signal{}{}{}_area".format(args.signal, int(mass * 1000), tag))
        lim = read_limits(area)
        if lim is None:
            print("skip {:.3g} TeV: no limit output".format(mass)); continue
        validate_expected_band(lim, mass, args.min_band_gap_fraction)
        # mu -> sigma*B via the reference xsec that r=1 corresponds to for these cards.
        norm = {"expected": exp, "theory": th * THEORY_KFACTOR, "onepb": args.ref_pb}[args.norm]
        m.append(mass)
        med.append(lim["med"] * norm)
        lo68.append(lim["m1"] * norm)
        hi68.append(lim["p1"] * norm)
        lo95.append(lim["m2"] * norm)
        hi95.append(lim["p2"] * norm)
        thy.append(th * THEORY_KFACTOR)
        if not blind and "obs" in lim:
            obs.append(lim["obs"] * norm)
    m = np.array(m)
    if len(m) == 0:
        raise RuntimeError(
            "no valid limit points in reporting range [{}, {}] TeV".format(
                args.xmin, args.xmax
            )
        )
    print("reporting masses [TeV]:", ", ".join("{:g}".format(x) for x in m))

    # theory curve on a fine grid (log-interp) so it's smooth across the gap
    fine = np.linspace(args.xmin, args.xmax, 400)
    thy_fine = np.array([_logext(theory_all, f) * THEORY_KFACTOR for f in fine])

    hep.style.use(hep.style.CMS)
    fig, ax = plt.subplots(layout="constrained")
    fig.get_layout_engine().set(rect=(0.0, 0.04, 1.0, 0.96))
    sig_tex = {"RSGluon": r"g_{KK}", "ZPrime": r"Z'", "ZPrime_DM": r"Z_{DM}"}[args.signal]

    ax.fill_between(m, lo95, hi95, color=YELLOW, label="95% expected", zorder=1)
    ax.fill_between(m, lo68, hi68, color=GREEN,  label="68% expected", zorder=2)
    ax.plot(m, med, "k--", lw=2, label="Median expected", zorder=4)
    if args.theory_label:
        blue_label = args.theory_label
    elif args.overlay_theory_json:
        blue_label = r"XSDB %s %s%% (LO)" % (sig_tex, args.width or "")
    else:
        blue_label = r"Theory %s %s%% width" % (sig_tex, args.width or "")
    ax.plot(fine, thy_fine, color="blue", lw=3, label=blue_label, zorder=3)
    overlay_theory_all = None
    if args.overlay_theory_json:
        ov = json.load(open(args.overlay_theory_json))[args.signal + args.width]
        ov_mass = np.array(ov["mass"]); ov_theory = np.array(ov["theory"])
        # align overlay grid to this plot's masses (log-interp), draw on the fine grid
        overlay_theory_all = np.exp(np.interp(masses_all, ov_mass, np.log(ov_theory)))
        ov_fine = np.exp(np.interp(fine, ov_mass, np.log(ov_theory)))
        ax.plot(fine, ov_fine, color="red", lw=3, label=args.overlay_label, zorder=3)
    if not blind and len(obs) == len(m):
        ax.plot(m, obs, "ko-", lw=2, label="Observed", zorder=5)

    ax.set_yscale("log")
    ax.set_xlim(args.xmin, args.xmax)
    visible_max = max(float(np.max(hi95)), float(np.max(thy_fine)))
    if obs:
        visible_max = max(visible_max, float(np.max(obs)))
    visible_min = min(float(np.min(lo95)), float(np.min(thy_fine)))
    if obs:
        visible_min = min(visible_min, float(np.min(obs)))
    # Keep the established 1e-4 floor unless a displayed curve genuinely falls
    # below it (the 1%-width theory prediction does so near 6 TeV).  In that case,
    # open exactly enough logarithmic headroom to avoid clipping the curve.
    lower_bound = min(1e-4, 10 ** np.floor(np.log10(0.8 * visible_min)))
    ax.set_ylim(lower_bound, 10 ** np.ceil(np.log10(3.0 * visible_max)))
    major_xticks = [args.xmin] + list(
        range(int(np.ceil(args.xmin)), int(np.floor(args.xmax)) + 1)
    )
    ax.set_xticks(sorted(set(major_xticks)))
    ax.set_xlabel(r"$m_{%s}$ [TeV]" % sig_tex)
    ax.set_ylabel(r"$\sigma \times B(%s \to t\bar{t})$ [pb]" % sig_tex)
    ax.legend(loc="upper right", title="95% CL upper limits", fontsize=18)
    hep.cms.label("Preliminary", data=True, lumi=args.lumi, com=args.com, loc=2, ax=ax)

    if not args.no_stamp:
        stamp_figure(fig)
    os.makedirs(args.output, exist_ok=True)
    base = os.path.join(args.output, "limits_{}{}_{}_mpl".format(args.signal, args.width, args.year))
    for ext in ("png", "pdf"):
        fig.savefig(base + "." + ext, bbox_inches="tight")
    plt.close(fig)
    with open(base + ".json", "w") as out:
        json.dump({
            "year": args.year,
            "signal": args.signal,
            "width_percent": args.width,
            "reporting_range_tev": [args.xmin, args.xmax],
            "mass_tev": m.tolist(),
            "expected_median_pb": list(map(float, med)),
            "expected_minus1sigma_pb": list(map(float, lo68)),
            "expected_plus1sigma_pb": list(map(float, hi68)),
            "expected_minus2sigma_pb": list(map(float, lo95)),
            "expected_plus2sigma_pb": list(map(float, hi95)),
            "theory_pb": list(map(float, thy)),
            "observed_pb": list(map(float, obs)) if obs else None,
            "limit_dir": args.limit_dir,
            "normalization": args.norm,
            "reference_pb": args.ref_pb,
            "provenance": provenance_stamp(),
        }, out, indent=2)
        out.write("\n")
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
            print("expected exclusion crossing ~ {:.2f} TeV  ({})".format(
                mx, args.theory_label or "XSDB"))
        if overlay_theory_all is not None:
            log_ov_at_m = np.interp(m, masses_all, np.log(overlay_theory_all))
            d2 = np.log(np.array(med)) - log_ov_at_m
            for i in np.where(np.diff(np.sign(d2)) != 0)[0]:
                x0, x1 = m[i], m[i + 1]; e0, e1 = d2[i], d2[i + 1]
                print("expected exclusion crossing ~ {:.2f} TeV  ({})".format(
                    x0 - e0 * (x1 - x0) / (e1 - e0), args.overlay_label))


if __name__ == "__main__":
    main()
