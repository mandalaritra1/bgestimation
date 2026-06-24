#!/usr/bin/env python3
"""Prefit vs postfit 2D distributions (m_tt vs m_t) as flat colz heatmaps, for the
'Fitted Parameter values' slide. Reads the 2D TH2s that 2DAlphabet's StdPlots
already built (saved as lego in plots_fit_b/base_figs); we just redraw them colz.

  python plot_prefit_postfit_2d.py                       # QCD, Pass, cen+fwd
  python plot_prefit_postfit_2d.py --proc TotalBkg       # total background
  python plot_prefit_postfit_2d.py --region Fail
"""
import os, argparse
import ROOT
ROOT.gROOT.SetBatch(True)
ROOT.TH1.AddDirectory(False)
ROOT.gStyle.SetOptStat(0)
ROOT.gStyle.SetNumberContours(255)
_keep = []

ap = argparse.ArgumentParser()
ap.add_argument("--sig", default="signalZPrime3000")
ap.add_argument("--tf", default="2x1")
ap.add_argument("--proc", default="QCD", help="QCD | TotalBkg | data_obs | 24_TTbar")
ap.add_argument("--region", default="Pass", choices=["Pass", "Fail"])
ap.add_argument("--output", default="prefit_postfit_2d")
ap.add_argument("--lumi", default="109.95 fb^{-1} (13.6 TeV)")
args = ap.parse_args()
os.makedirs(args.output, exist_ok=True)

cats = [("cen2024", "Cen24", "central"), ("fwd2024", "Fwd24", "forward")]

for catdir, reg, label in cats:
    path = "output/ttbarfits_{}_{}_{}/ttbar-{}_area/plots_fit_b/all_plots.root".format(
        catdir, args.tf, args.sig, args.sig)
    if not os.path.exists(path):
        print("missing", path); continue
    f = ROOT.TFile.Open(path)
    for stage in ("prefit", "postfit"):
        hname = "{}_{}{}_{}_2D".format(args.proc, reg, args.region, stage)
        h = f.Get(hname)
        if not h:
            print("missing hist", hname, "in", path); continue
        h = h.Clone(hname + "_c"); _keep.append(h)

        c = ROOT.TCanvas("c_%s_%s" % (catdir, stage), "", 800, 700); _keep.append(c)
        c.SetRightMargin(0.16); c.SetLeftMargin(0.13); c.SetBottomMargin(0.12)
        c.SetLogz(True)
        h.SetTitle("")
        h.GetXaxis().SetTitle("m_{t} [GeV]")
        h.GetYaxis().SetTitle("m_{t#bar{t}} [GeV]")
        h.GetZaxis().SetTitle("Events")
        h.GetYaxis().SetTitleOffset(1.3)
        h.SetMinimum(1.0)
        h.Draw("COLZ")

        lat = ROOT.TLatex(); lat.SetNDC(); lat.SetTextFont(42)
        lat.SetTextSize(0.045); lat.DrawLatex(0.13, 0.92, "#bf{CMS} #it{Internal}")
        lat.SetTextSize(0.038); lat.SetTextAlign(31); lat.DrawLatex(0.84, 0.92, args.lumi)
        lat.SetTextAlign(11); lat.SetTextSize(0.038)
        lat.DrawLatex(0.16, 0.85, "%s %s, %s" % (args.proc, args.region, label))
        lat.DrawLatex(0.16, 0.81, stage)

        out = os.path.join(args.output, "%s_%s_%s_%s" % (args.proc, args.region, stage, catdir))
        for ext in ("png", "pdf"):
            c.SaveAs(out + "." + ext)
        print("saved", out + ".png")
    f.Close()
