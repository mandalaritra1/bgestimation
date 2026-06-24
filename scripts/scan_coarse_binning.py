#!/usr/bin/env python
"""Quantify how coarse the cen2024 binning must be to keep QCD = Data - TTbar >= 0.

Rebins the fine input histograms to several candidate analysis binnings and
reports, per scheme, the number of bins with negative QCD (Data - TTbar < 0)
and empty-data bins, for the central Pass and Fail regions. 2DAlphabet builds
the QCD template from the Fail region, so Fail is the binding constraint, but
Pass must also be non-negative for the postfit.

X (m_t) binnings must keep edges at 105 and 210 (Region1 = signal window).

Usage:
  python scripts/scan_coarse_binning.py \
      --base root://eosuser.cern.ch//eos/user/a/amandal/ttbarhad_root_files/2dAlphabetInputs
"""
import argparse
import array
import ROOT

ROOT.gROOT.SetBatch(True)

SIGSTART, SIGEND = 105.0, 210.0

# Candidate binning schemes. Each is (name, xbins, ybins).
X_CUR = [25, 60, 105, 130, 150, 170, 175, 180, 185, 190, 210, 475]
Y_CUR = [800, 1100, 1300, 1500, 1700, 1900, 2100, 2300, 2500, 2700, 2900,
         3100, 3300, 3500, 3700, 6500]

SCHEMES = [
    ("current (11x15)", X_CUR, Y_CUR),
    # Coarsen only m_tt (the sparse high-mass tail):
    ("Y-coarse (11x8)", X_CUR,
     [800, 1100, 1400, 1700, 2000, 2400, 3000, 4000, 6500]),
    ("Y-coarse (11x5)", X_CUR,
     [800, 1200, 1700, 2400, 3400, 6500]),
    # Coarsen m_t around the top-mass edge + m_tt:
    ("XY-coarse (7x8)",
     [25, 105, 130, 150, 175, 210, 300, 475],
     [800, 1100, 1400, 1700, 2000, 2400, 3000, 4000, 6500]),
    ("XY-coarse (5x5)",
     [25, 105, 150, 210, 300, 475],
     [800, 1200, 1700, 2400, 3400, 6500]),
    ("XY-coarse (4x4)",
     [25, 105, 160, 210, 475],
     [800, 1400, 2200, 3400, 6500]),
    ("XY-coarse (4x3)",
     [25, 105, 160, 210, 475],
     [800, 1500, 2500, 6500]),
]


def find_hist(tfile, region):
    for name in ("MttvsMt" + region, "MttvsMt" + region.replace("24", "2024")):
        h = tfile.Get(name)
        if h:
            return h
    return None


def rebin(h, xbins, ybins):
    nx, ny = len(xbins) - 1, len(ybins) - 1
    out = ROOT.TH2D(h.GetName() + "_r", "", nx, array.array("d", map(float, xbins)),
                    ny, array.array("d", map(float, ybins)))
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


def analyze(hd, ht):
    nx, ny = hd.GetNbinsX(), hd.GetNbinsY()
    neg = empty = neg_sig = 0
    worst = (0.0, None)
    for ix in range(1, nx + 1):
        xlo, xhi = hd.GetXaxis().GetBinLowEdge(ix), hd.GetXaxis().GetBinUpEdge(ix)
        in_sig = (xlo >= SIGSTART - 1e-6) and (xhi <= SIGEND + 1e-6)
        for iy in range(1, ny + 1):
            d = hd.GetBinContent(ix, iy)
            q = d - ht.GetBinContent(ix, iy)
            if d == 0:
                empty += 1
            if q < 0:
                neg += 1
                if in_sig:
                    neg_sig += 1
                if q < worst[0]:
                    worst = (q, (xlo, xhi, hd.GetYaxis().GetBinLowEdge(iy)))
    return neg, neg_sig, empty, nx * ny, worst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    args = ap.parse_args()

    raw = {}
    for region in ("Cen24Pass", "Cen24Fail"):
        d = ROOT.TFile.Open("%s/TTbarAllHad24_Data.root" % args.base)
        t = ROOT.TFile.Open("%s/TTbarAllHad24_TTbar.root" % args.base)
        hd, ht = find_hist(d, region), find_hist(t, region)
        hd.SetDirectory(0); ht.SetDirectory(0)
        raw[region] = (hd, ht)
        d.Close(); t.Close()

    for region in ("Cen24Fail", "Cen24Pass"):
        hd, ht = raw[region]
        print("\n======== %s ========" % region)
        print("  %-18s %8s %6s %7s %7s   %s"
              % ("scheme", "bins", "neg", "neg_sig", "empty", "worst QCD"))
        for name, xb, yb in SCHEMES:
            rd, rt = rebin(hd, xb, yb), rebin(ht, xb, yb)
            neg, neg_sig, empty, nbins, worst = analyze(rd, rt)
            wtxt = ""
            if worst[1]:
                wtxt = "%.2f @ m_t[%.0f,%.0f] m_tt>=%.0f" % (
                    worst[0], worst[1][0], worst[1][1], worst[1][2])
            flag = "   <== CLEAN" if neg == 0 else ""
            print("  %-18s %8d %6d %7d %7d   %s%s"
                  % (name, nbins, neg, neg_sig, empty, wtxt, flag))


if __name__ == "__main__":
    main()
