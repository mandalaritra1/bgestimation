#!/usr/bin/env python
"""Find the ttbar scale that keeps QCD = Data - scale*TTbar >= 0.

Rebins the fine input histograms to the analysis binning (from the cen2024
config) and, for a range of ttbar scales, counts analysis bins with negative
QCD in the central Pass and Fail regions. 2DAlphabet builds the QCD template
from the Fail region, so Fail negativity is the binding constraint.

Usage:
  python scripts/scan_ttbar_scale.py \
      --base root://eosuser.cern.ch//eos/user/a/amandal/ttbarhad_root_files/2dAlphabetInputs
"""
import argparse
import json
import ROOT

ROOT.gROOT.SetBatch(True)

SIGSTART, SIGEND = 105.0, 210.0


def load_binning():
    cfg = json.load(open("jsons/config/ttbar_cen2024.json"))
    b = cfg["BINNING"]["default"]
    return [float(x) for x in b["X"]["BINS"]], [float(y) for y in b["Y"]["BINS"]]


def find_hist(tfile, region):
    for name in ("MttvsMt" + region, "MttvsMt" + region.replace("24", "2024")):
        h = tfile.Get(name)
        if h:
            return h
    return None


def rebin_to_analysis(h, xbins, ybins):
    """Sum fine-bin contents into the coarse analysis grid."""
    import array
    nx, ny = len(xbins) - 1, len(ybins) - 1
    out = ROOT.TH2D(h.GetName() + "_ana", "", nx,
                    array.array("d", xbins), ny, array.array("d", ybins))
    out.SetDirectory(0)
    for ix in range(1, h.GetNbinsX() + 1):
        xc = h.GetXaxis().GetBinCenter(ix)
        if xc < xbins[0] or xc > xbins[-1]:
            continue
        for iy in range(1, h.GetNbinsY() + 1):
            yc = h.GetYaxis().GetBinCenter(iy)
            if yc < ybins[0] or yc > ybins[-1]:
                continue
            ob = out.FindBin(xc, yc)
            out.SetBinContent(ob, out.GetBinContent(ob) + h.GetBinContent(ix, iy))
    return out


def neg_count(hd, ht, scale, region_label):
    nx, ny = hd.GetNbinsX(), hd.GetNbinsY()
    total, sigwin = 0, 0
    worst = (0.0, None)
    for ix in range(1, nx + 1):
        xlo = hd.GetXaxis().GetBinLowEdge(ix)
        xhi = hd.GetXaxis().GetBinUpEdge(ix)
        in_sig = (xlo >= SIGSTART - 1e-6) and (xhi <= SIGEND + 1e-6)
        for iy in range(1, ny + 1):
            q = hd.GetBinContent(ix, iy) - scale * ht.GetBinContent(ix, iy)
            if q < 0:
                total += 1
                if in_sig:
                    sigwin += 1
                if q < worst[0]:
                    worst = (q, (xlo, xhi, hd.GetYaxis().GetBinLowEdge(iy)))
    return total, sigwin, worst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    args = ap.parse_args()
    xbins, ybins = load_binning()
    print("Analysis binning: %d m_t x %d m_tt bins" % (len(xbins) - 1, len(ybins) - 1))

    region_hists = {}
    for region in ("Cen24Pass", "Cen24Fail"):
        d = ROOT.TFile.Open("%s/TTbarAllHad24_Data.root" % args.base)
        t = ROOT.TFile.Open("%s/TTbarAllHad24_TTbar.root" % args.base)
        hd, ht = find_hist(d, region), find_hist(t, region)
        region_hists[region] = (rebin_to_analysis(hd, xbins, ybins),
                                 rebin_to_analysis(ht, xbins, ybins))
        d.Close(); t.Close()

    scales = [1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2]
    for region in ("Cen24Fail", "Cen24Pass"):
        hd, ht = region_hists[region]
        print("\n=== %s (Data=%.0f, TTbar=%.0f, ratio=%.2f) ==="
              % (region, hd.Integral(), ht.Integral(), ht.Integral() / hd.Integral()))
        print("  scale | neg bins (total / sig-window) | worst QCD")
        for s in scales:
            total, sigwin, worst = neg_count(hd, ht, s, region)
            wtxt = ""
            if worst[1]:
                wtxt = "  worst=%.2f @ m_t[%.0f,%.0f] m_tt>=%.0f" % (
                    worst[0], worst[1][0], worst[1][1], worst[1][2])
            flag = "  <-- CLEAN" if total == 0 else ""
            print("  %4.1f  |   %3d / %3d %s%s" % (s, total, sigwin, wtxt, flag))


if __name__ == "__main__":
    main()
