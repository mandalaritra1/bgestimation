#!/usr/bin/env python3
"""Method ① — parametric bump-hunt cross-check of the 2DAlphabet estimate.

The *most independent* of the two 1D cross-checks: it never uses the Fail region
or the ttbar MC. The full smooth background of the Pass-region m_tt spectrum
(QCD + ttbar together) is described by an analytic dijet function; the resonance
is a bump on top. Function-choice (bias) uncertainty is handled by discrete
profiling over a family of dijet orders (RooMultiPdf), with an F-test / LRT to
report the favoured order.

    python oned/bumphunt.py --cat cen24 --signal signalZPrime4000

Background families (x = m_tt / sqrt(s), sqrt(s) = 13.6 TeV):
    2-par:  (1-x)^p1 / x^p2
    3-par:  (1-x)^p1 / x^(p2 + p3 ln x)
    4-par:  (1-x)^p1 / x^(p2 + p3 ln x + p4 ln^2 x)

Outputs (oned/out/bumphunt/<cat>/<signal>/):
    ws.root, card.txt, ws_combine.root      — workspace + datacard
    higgsCombine*.AsymptoticLimits.*.root   — blinded limit
    bkgfit_<cat>.png                        — background fit to data (once/cat)
and a per-cat summary row appended to oned/out/bumphunt_<cat>.json.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess

import ROOT

ROOT.gROOT.SetBatch(True)
ROOT.RooMsgService.instance().setGlobalKillBelow(ROOT.RooFit.WARNING)

SQRTS = 13600.0
QUANTILES = {0.025: "exp_m2", 0.16: "exp_m1", 0.5: "exp", 0.84: "exp_p1", 0.975: "exp_p2"}

# dijet families: name -> (RooGenericPdf formula in @0=mtt, list of (par, init, lo, hi))
FAMILIES = {
    2: ("TMath::Power(1-@0/{s},@1)/TMath::Power(@0/{s},@2)",
        [("p1", 1.0, -50, 50), ("p2", 7.0, 0, 50)]),
    3: ("TMath::Power(1-@0/{s},@1)/TMath::Power(@0/{s},@2+@3*TMath::Log(@0/{s}))",
        [("p1", 1.0, -50, 50), ("p2", 7.0, 0, 50), ("p3", 0.0, -20, 20)]),
    4: ("TMath::Power(1-@0/{s},@1)/TMath::Power(@0/{s},@2+@3*TMath::Log(@0/{s})+@4*TMath::Log(@0/{s})*TMath::Log(@0/{s}))",
        [("p1", 1.0, -50, 50), ("p2", 7.0, 0, 50), ("p3", 0.0, -20, 20), ("p4", 0.0, -20, 20)]),
}


def windowed(h, lo, hi):
    """Clone the bins of `h` inside [lo, hi] into a fresh TH1D."""
    ax = h.GetXaxis()
    b1, b2 = ax.FindBin(lo + 1e-6), ax.FindBin(hi - 1e-6)
    n = b2 - b1 + 1
    hw = ROOT.TH1D(h.GetName() + "_win", "", n, ax.GetBinLowEdge(b1), ax.GetBinUpEdge(b2))
    for i, b in enumerate(range(b1, b2 + 1), 1):
        hw.SetBinContent(i, h.GetBinContent(b))
        hw.SetBinError(i, h.GetBinError(b))
    hw.SetDirectory(0)
    return hw


def build_family(order, mtt):
    """RooGenericPdf for a dijet family of given order.

    The analytic shape goes straight into the RooMultiPdf (as in the CMS Hgg /
    dijet bump-hunts). We deliberately do NOT wrap it in RooParametricShapeBinPdf:
    that class's constructor is broken against the ROOT 6.30 in CMSSW_14
    (RooListProxy default-ctor runtime error). With 100 GeV bins the per-bin
    center-evaluation bias is sub-percent, fine for a cross-check."""
    formula, pars = FAMILIES[order]
    rpars = []
    for name, init, lo, hi in pars:
        rpars.append(ROOT.RooRealVar(f"dijet{order}_{name}", name, init, lo, hi))
    arglist = ROOT.RooArgList(mtt)
    for v in rpars:
        arglist.add(v)
    gen = ROOT.RooGenericPdf(f"dijet{order}", formula.format(s=SQRTS), arglist)
    return gen, rpars


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cat", default="cen24", choices=["cen24", "fwd24"])
    ap.add_argument("--signal", default="signalZPrime4000")
    ap.add_argument("--scenario", default="ZPrime_1")
    ap.add_argument("--inputs", default=None)
    ap.add_argument("--mtt-min", type=float, default=1500.0,
                    help="lower fit edge (GeV); start above the spectrum turn-on")
    ap.add_argument("--mtt-max", type=float, default=6500.0)
    ap.add_argument("--orders", default="2,3,4",
                    help="dijet orders in the RooMultiPdf envelope (default 2,3,4)")
    ap.add_argument("--rMax", type=float, default=50.0)
    ap.add_argument("--outdir", default=None)
    args = ap.parse_args()

    orders = [int(o) for o in args.orders.split(",")]
    inputs = args.inputs or os.path.join("oned", "out", f"oned_inputs_{args.cat}.root")
    subprocess.run(["python", "oned/project_inputs.py", "--cat", args.cat,
                    "--signal", args.signal, "--scenario", args.scenario,
                    "--out", inputs], check=True)

    f = ROOT.TFile.Open(inputs)
    hdata = windowed(f.Get("data_obs_Pass"), args.mtt_min, args.mtt_max)
    hsig = windowed(f.Get("signal_Pass"), args.mtt_min, args.mtt_max)
    f.Close()
    ndata = hdata.Integral()
    sig_rate = hsig.Integral()
    nbins = hdata.GetNbinsX()

    mtt = ROOT.RooRealVar("mtt", "m_{t#bar{t}}", args.mtt_min, args.mtt_max, "GeV")
    mtt.setBins(nbins)
    data = ROOT.RooDataHist("data_obs", "", ROOT.RooArgList(mtt), hdata)

    # --- fit each family, F-test / LRT ------------------------------------------
    fits, nlls = {}, {}
    for o in orders:
        gen, rpars = build_family(o, mtt)
        res = gen.fitTo(data, ROOT.RooFit.Save(True), ROOT.RooFit.PrintLevel(-1),
                        ROOT.RooFit.Minimizer("Minuit2", "migrad"),
                        ROOT.RooFit.Strategy(1), ROOT.RooFit.SumW2Error(False))
        fits[o] = (gen, rpars, res)
        nlls[o] = res.minNll()

    ftest = {}
    for lo, hi in zip(orders[:-1], orders[1:]):
        dnll = 2.0 * (nlls[lo] - nlls[hi])
        dof = len(FAMILIES[hi][1]) - len(FAMILIES[lo][1])
        pval = ROOT.TMath.Prob(max(dnll, 0.0), dof) if dof > 0 else 1.0
        ftest[f"{lo}->{hi}"] = {"2dNLL": dnll, "dof": dof, "pval": pval}
    # favoured order = lowest order whose step up is NOT significant (p>0.05)
    favoured = orders[-1]
    for lo, hi in zip(orders[:-1], orders[1:]):
        if ftest[f"{lo}->{hi}"]["pval"] > 0.05:
            favoured = lo
            break

    # --- background fit plot (favoured order) -----------------------------------
    outdir = args.outdir or os.path.join("oned", "out", "bumphunt", args.cat, args.signal)
    shutil.rmtree(outdir, ignore_errors=True)
    os.makedirs(outdir, exist_ok=True)
    pdf_fav = fits[favoured][0]
    frame = mtt.frame(ROOT.RooFit.Title(f"{args.cat} Pass m_{{tt}} -- dijet-{favoured} fit"))
    data.plotOn(frame, ROOT.RooFit.Name("data"))
    pdf_fav.plotOn(frame, ROOT.RooFit.Name("fit"), ROOT.RooFit.LineColor(ROOT.kAzure + 1))
    chi2 = frame.chiSquare("fit", "data", len(FAMILIES[favoured][1]))
    c = ROOT.TCanvas("c", "", 720, 600)
    c.SetLogy()
    frame.SetMinimum(0.2)
    frame.Draw()
    lat = ROOT.TLatex()
    lat.SetNDC(); lat.SetTextSize(0.035)
    lat.DrawLatex(0.55, 0.84, f"dijet-{favoured},  #chi^{{2}}/ndf = {chi2:.2f}")
    plot_path = os.path.join(outdir, f"bkgfit_{args.cat}_{args.signal}.png")
    c.SaveAs(plot_path)

    # --- assemble the RooMultiPdf workspace -------------------------------------
    pdf_index = ROOT.RooCategory("pdf_index", "dijet order index")
    pdfs = ROOT.RooArgList()
    keep = []  # keep python refs alive
    for i, o in enumerate(orders):
        pdf_index.defineType(f"dijet{o}", i)
        pdfs.add(fits[o][0])
        keep.append(fits[o])
    multipdf = ROOT.RooMultiPdf("roomultipdf", "", pdf_index, pdfs)
    norm = ROOT.RooRealVar("roomultipdf_norm", "", ndata, 0.0, 3.0 * max(ndata, 1.0))

    sig_dh = ROOT.RooDataHist("signal_dh", "", ROOT.RooArgList(mtt), hsig)
    sig_pdf = ROOT.RooHistPdf("signal_pdf", "", ROOT.RooArgSet(mtt), sig_dh)

    w = ROOT.RooWorkspace("w", "w")
    imp = getattr(w, "import")
    imp(data)
    imp(multipdf)   # pulls pdf_index in with it
    imp(norm)
    imp(sig_pdf)
    w.writeToFile(os.path.join(outdir, "ws.root"))

    # --- datacard ----------------------------------------------------------------
    card = os.path.join(outdir, "card.txt")
    with open(card, "w") as fh:
        fh.write("imax 1\njmax 1\nkmax *\n")
        fh.write("-" * 60 + "\n")
        fh.write("shapes data_obs   Pass ws.root w:data_obs\n")
        fh.write("shapes background Pass ws.root w:roomultipdf\n")
        fh.write("shapes signal     Pass ws.root w:signal_pdf\n")
        fh.write("-" * 60 + "\n")
        fh.write("bin          Pass\n")
        fh.write("observation  -1\n")
        fh.write("-" * 60 + "\n")
        fh.write("bin      Pass      Pass\n")
        fh.write("process  signal    background\n")
        fh.write("process  0         1\n")
        fh.write(f"rate     {sig_rate:.6f}   1\n")
        fh.write("-" * 60 + "\n")
        fh.write("lumi_2024 lnN  1.014  -\n")
        fh.write("pdf_index discrete\n")

    build = (
        f"cd {outdir} && "
        f"text2workspace.py card.txt -o ws_combine.root && "
        f"rm -f higgsCombine*.root && "
        f"combine -M AsymptoticLimits -d ws_combine.root --run blind "
        f"--rMin 0 --rMax {args.rMax} --setParameters r=0 "
        f"--cminDefaultMinimizerStrategy 0 -v 0 > combine.log 2>&1"
    )
    subprocess.run(build, shell=True)

    # --- read limit + write summary ---------------------------------------------
    res = None
    cand = glob.glob(os.path.join(outdir, "higgsCombine*.AsymptoticLimits.*.root"))
    if cand:
        ff = ROOT.TFile.Open(cand[0])
        t = ff.Get("limit")
        if hasattr(t, "GetEntries") and t.GetEntries() > 0:
            res = {}
            for i in range(t.GetEntries()):
                t.GetEntry(i)
                k = QUANTILES.get(round(t.quantileExpected, 3))
                if k:
                    res[k] = float(t.limit)
        ff.Close()
    if not res:
        print(f"[bumphunt] FAIL {args.cat} {args.signal}; see {outdir}/combine.log")
        return 1

    print(f"[bumphunt] {args.cat} {args.signal}  fav=dijet{favoured} "
          f"(chi2/ndf={chi2:.2f})  exp r = {res['exp']:.4g} "
          f"({res['exp_m1']:.4g} / {res['exp_p1']:.4g})")
    for k, v in ftest.items():
        print(f"    F-test {k}: 2dNLL={v['2dNLL']:.2f} dof={v['dof']} p={v['pval']:.3f}")

    summ_path = os.path.join("oned", "out", f"bumphunt_{args.cat}.json")
    summ = json.load(open(summ_path)) if os.path.exists(summ_path) else {}
    mass = "".join(ch for ch in args.signal if ch.isdigit())
    summ[mass] = dict(res, favoured=favoured, chi2ndf=chi2, ftest=ftest, signal=args.signal)
    json.dump(summ, open(summ_path, "w"), indent=2, sort_keys=True)
    print(f"  -> {summ_path}  (plot: {plot_path})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
