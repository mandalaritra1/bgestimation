#!/usr/bin/env python3
"""Fail-region QCD 2D distribution (m_tt vs m_t) as a flat colz heatmap,
in the style of the Run2 paper Fig. 9.  QCD_Fail = data_obs_Fail - TTbar_Fail
(nominal), read from a fit area's organized_hists.root.

  python plot_qcd_fail_2d.py            # default cen+fwd 2024, 3 TeV area
"""
import os, argparse
import ROOT
ROOT.gROOT.SetBatch(True)
ROOT.TH1.AddDirectory(False)   # hists are memory-resident, not file-owned (avoids
                               # double-free segfaults when the TFile is closed)
ROOT.gStyle.SetOptStat(0)
ROOT.gStyle.SetNumberContours(255)
_keep = []                     # keep python refs alive across the loop

ap = argparse.ArgumentParser()
ap.add_argument("--sig", default="signalZPrime3000")
ap.add_argument("--tf", default="2x1")
ap.add_argument("--output", default="qcd_fail_2d")
ap.add_argument("--lumi", default="109.95 fb^{-1} (13.6 TeV)")
args = ap.parse_args()
os.makedirs(args.output, exist_ok=True)

cats = [("cen2024", "Cen24", "central"), ("fwd2024", "Fwd24", "forward")]

for catdir, reg, label in cats:
    path = "output/ttbarfits_{}_{}_{}/organized_hists.root".format(catdir, args.tf, args.sig)
    if not os.path.exists(path):
        print("missing", path); continue
    f = ROOT.TFile.Open(path)
    data = f.Get("data_obs_{}Fail_FULL".format(reg))
    tt   = f.Get("24_TTbar_{}Fail_FULL".format(reg))
    if not data or not tt:
        print("missing hists in", path); f.Close(); continue
    qcd = data.Clone("QCD_{}Fail".format(reg))
    qcd.Add(tt, -1.0)
    f.Close()

    c = ROOT.TCanvas("c_" + reg, "c_" + reg, 800, 700)
    _keep += [qcd, c]
    c.SetRightMargin(0.16); c.SetLeftMargin(0.13); c.SetBottomMargin(0.12)
    c.SetLogz(True)
    qcd.SetTitle("")
    qcd.GetXaxis().SetTitle("m_{t} [GeV]")
    qcd.GetYaxis().SetTitle("m_{t#bar{t}} [GeV]")
    qcd.GetZaxis().SetTitle("Events")
    qcd.GetYaxis().SetTitleOffset(1.3)
    qcd.SetMinimum(1.0)
    qcd.Draw("COLZ")

    lat = ROOT.TLatex(); lat.SetNDC(); lat.SetTextFont(42)
    lat.SetTextSize(0.045); lat.DrawLatex(0.13, 0.92, "#bf{CMS} #it{Internal}")
    lat.SetTextSize(0.038); lat.SetTextAlign(31)
    lat.DrawLatex(0.84, 0.92, args.lumi)
    lat.SetTextAlign(11); lat.SetTextSize(0.04)
    lat.DrawLatex(0.16, 0.84, "QCD Fail, {}".format(label))

    out = os.path.join(args.output, "qcd_fail_2d_{}".format(catdir))
    for ext in ("png", "pdf"):
        c.SaveAs(out + "." + ext)
    print("saved", out + ".png")
