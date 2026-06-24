#!/usr/bin/env python3
"""Method ② — 1D alphabet (rhalphalib) cross-check of the 2DAlphabet estimate.

Collapses the (m_SD, m_tt) inputs onto m_tt (via ``project_inputs.py``) and builds
a 1D transfer-factor model

    Pass(m_tt) = TF(m_tt) * Fail_QCD(m_tt)

with a *data-driven* per-bin QCD in the Fail region (one free nuisance per bin,
initialised to data-ttbar) and a Bernstein-polynomial transfer factor TF(m_tt).
``ttbar`` (MC) and the resonance ``signal`` (MC) enter both regions as fixed
template samples. The model is rendered to a Combine datacard with ``rhalphalib``
and a blinded ``AsymptoticLimits`` is run.

This is the *less* independent of the two 1D cross-checks: it shares the
2DAlphabet pass/fail transfer-factor idea, just with the m_SD dimension
integrated out. Comparing its limit to the full 2DAlphabet result isolates how
much sensitivity the m_SD axis buys.

    python oned/alphabet1d.py --cat cen24 --signal signalZPrime4000 [--tf-order 2]

Outputs (oned/out/alphabet1d/<cat>/<signal>/):
    fail.txt, pass.txt, combined.txt, ws.root  — rendered datacard + workspace
    higgsCombine*.AsymptoticLimits.*.root      — combine limit
and a per-cat summary row appended to oned/out/alphabet1d_<cat>.json.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess

import numpy as np
import ROOT
import rhalphalib as rl

ROOT.gROOT.SetBatch(True)

QUANTILES = {  # combine quantileExpected -> summary key
    0.025: "exp_m2", 0.16: "exp_m1", 0.5: "exp", 0.84: "exp_p1", 0.975: "exp_p2",
}


def _bins(h, b1, b2):
    """Return (values, sumw2) for bins [b1, b2] of a TH1."""
    vals = np.array([h.GetBinContent(b) for b in range(b1, b2 + 1)], dtype=float)
    sw2 = np.array([h.GetBinError(b) ** 2 for b in range(b1, b2 + 1)], dtype=float)
    return vals, sw2


def _read_limit(area):
    """Read the expected-limit quantiles from the AsymptoticLimits output."""
    import glob
    cand = glob.glob(os.path.join(area, "higgsCombine*.AsymptoticLimits.*.root"))
    if not cand:
        return None
    f = ROOT.TFile.Open(cand[0])
    t = f.Get("limit")
    out = {}
    for i in range(t.GetEntries()):
        t.GetEntry(i)
        q = round(t.quantileExpected, 3)
        key = QUANTILES.get(q)
        if key:
            out[key] = float(t.limit)
    f.Close()
    return out or None


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cat", default="cen24", choices=["cen24", "fwd24"])
    ap.add_argument("--signal", default="signalZPrime4000")
    ap.add_argument("--inputs", default=None,
                    help="oned_inputs root (default oned/out/oned_inputs_<cat>.root)")
    ap.add_argument("--tf-order", type=int, default=2,
                    help="Bernstein order of the m_tt transfer factor (default 2)")
    ap.add_argument("--mtt-min", type=float, default=800.0)
    ap.add_argument("--mtt-max", type=float, default=6500.0,
                    help="upper m_tt fit edge (GeV); matches the 2DAlphabet window")
    ap.add_argument("--rMax", type=float, default=20.0)
    ap.add_argument("--outdir", default=None)
    args = ap.parse_args()

    inputs = args.inputs or os.path.join("oned", "out", f"oned_inputs_{args.cat}.root")
    # (Re)project for THIS signal so the templates always match --signal.
    subprocess.run(["python", "oned/project_inputs.py", "--cat", args.cat,
                    "--signal", args.signal, "--out", inputs], check=True)

    f = ROOT.TFile.Open(inputs)
    ax = f.Get("data_obs_Pass").GetXaxis()
    b1 = ax.FindBin(args.mtt_min + 1e-6)
    b2 = ax.FindBin(args.mtt_max - 1e-6)
    edges = np.array([ax.GetBinLowEdge(b) for b in range(b1, b2 + 1)]
                     + [ax.GetBinUpEdge(b2)])
    nb = len(edges) - 1
    obs = rl.Observable("mtt", edges)
    centers = edges[:-1] + 0.5 * np.diff(edges)
    scaled = (centers - edges[0]) / (edges[-1] - edges[0])  # m_tt mapped to [0,1]

    T = {}
    for proc in ("data_obs", "ttbar", "signal"):
        for reg in ("Pass", "Fail"):
            T[(proc, reg)] = _bins(f.Get(f"{proc}_{reg}"), b1, b2)
    f.Close()

    model = rl.Model("oned_alpha")
    chans = {}
    fail_qcd = None
    # Constrained nuisances. Besides being physical (ttbar normalisation + lumi),
    # Combine v10's AsymptoticLimits::runLimitExpected crashes on a model whose
    # nuisances are *all* free flatParams (here the per-bin QCD + TF), so the
    # model needs at least one genuinely constrained nuisance.
    lumi = rl.NuisanceParameter("lumi_2024", "lnN")
    ttnorm = rl.NuisanceParameter("ttbar_norm_2024", "lnN")
    # --- Fail first (defines the data-driven per-bin QCD the Pass region scales) --
    for reg in ("Fail", "Pass"):
        ch = rl.Channel(reg.lower())
        model.addChannel(ch)
        chans[reg] = ch
        ch.setObservation((T[("data_obs", reg)][0], edges, "mtt"))
        tt = T[("ttbar", reg)]
        tt_s = rl.TemplateSample(f"{reg.lower()}_ttbar", rl.Sample.BACKGROUND,
                                 (np.maximum(tt[0], 0.0), edges, "mtt"),
                                 force_positive=True)
        tt_s.setParamEffect(ttnorm, 1.20)
        tt_s.setParamEffect(lumi, 1.014)
        ch.addSample(tt_s)
        sg = T[("signal", reg)]
        sg_s = rl.TemplateSample(f"{reg.lower()}_signal", rl.Sample.SIGNAL,
                                 (np.maximum(sg[0], 0.0), edges, "mtt"),
                                 force_positive=True)
        sg_s.setParamEffect(lumi, 1.014)
        ch.addSample(sg_s)
        if reg == "Fail":
            initq = np.maximum(T[("data_obs", "Fail")][0]
                               - np.maximum(T[("ttbar", "Fail")][0], 0.0), 0.1)
            qpar = np.array([rl.IndependentParameter(f"qcd_{args.cat}_bin{i}", 0.0)
                             for i in range(nb)])
            sigmascale = 10.0
            qscaled = initq * (1.0 + sigmascale / np.maximum(1.0, np.sqrt(initq))) ** qpar
            fail_qcd = rl.ParametericSample(f"fail_qcd", rl.Sample.BACKGROUND, obs, qscaled)
            ch.addSample(fail_qcd)
        else:  # Pass QCD = TF(m_tt) * Fail QCD
            num = max((T[("data_obs", "Pass")][0] - T[("ttbar", "Pass")][0]).sum(), 1e-3)
            den = max((T[("data_obs", "Fail")][0] - T[("ttbar", "Fail")][0]).sum(), 1e-3)
            qcdeff = num / den
            tf = rl.BernsteinPoly(f"tf_{args.cat}", (args.tf_order,), ["mtt"],
                                  limits=(0, 50))
            tf_params = qcdeff * tf(scaled)
            pass_qcd = rl.TransferFactorSample("pass_qcd", rl.Sample.BACKGROUND,
                                               tf_params, fail_qcd)
            ch.addSample(pass_qcd)

    outdir = args.outdir or os.path.join("oned", "out", "alphabet1d", args.cat, args.signal)
    shutil.rmtree(outdir, ignore_errors=True)
    os.makedirs(outdir, exist_ok=True)
    model.renderCombine(outdir)

    # combineCards -> text2workspace -> blinded AsymptoticLimits.
    # The ttbar_norm/lumi lnN nuisances above are what keep this from crashing in
    # RooFit::Constrain: Combine v10's expected-limit path needs at least one
    # genuinely constrained nuisance (the QCD/TF params are all free flatParams).
    build = (
        f"cd {outdir} && "
        f"combineCards.py fail=fail.txt pass=pass.txt > combined.txt && "
        f"text2workspace.py combined.txt -o ws.root && "
        f"rm -f higgsCombine*.root && "
        f"combine -M AsymptoticLimits -d ws.root --run blind "
        f"--rMin 0 --rMax {args.rMax} --setParameters r=0 "
        f"--cminDefaultMinimizerStrategy 0 -v 0 > combine.log 2>&1"
    )
    rc = subprocess.run(build, shell=True)
    res = _read_limit(outdir)
    if res is None:
        print(f"[alphabet1d] FAIL {args.cat} {args.signal} (rc={rc.returncode}); see {outdir}/combine.log")
        return 1

    print(f"[alphabet1d] {args.cat} {args.signal}  tf{args.tf_order}  "
          f"exp r = {res['exp']:.4g}  ({res['exp_m1']:.4g} / {res['exp_p1']:.4g})")

    summ_path = os.path.join("oned", "out", f"alphabet1d_{args.cat}.json")
    summ = {}
    if os.path.exists(summ_path):
        summ = json.load(open(summ_path))
    mass = "".join(c for c in args.signal if c.isdigit())
    summ[mass] = dict(res, tf_order=args.tf_order, signal=args.signal)
    json.dump(summ, open(summ_path, "w"), indent=2, sort_keys=True)
    print(f"  -> {summ_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
