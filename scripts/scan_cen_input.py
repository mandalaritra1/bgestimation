#!/usr/bin/env python
"""Scan 2024 central input histograms for the cen24Pass anomaly.

Checks, per the DEBUG notes:
  1. negative / zero bins in Data, TTbar, signal (Pass and Fail)
  2. bins where Data - TTbar <= 0 (negative QCD expectation), the prime
     suspect for "Number of events is negative" in Cen2024Pass_Region1
     (top-mass window 105 < m_t < 210).

Usage:
  python scripts/scan_cen_input.py \
      --base root://eosuser.cern.ch//eos/user/a/amandal/ttbarhad_root_files/2dAlphabetInputs \
      --signal signalZPrime4000
"""
import argparse
import ROOT

ROOT.gROOT.SetBatch(True)

SIGSTART, SIGEND = 105.0, 210.0  # Region1 (signal/top-mass window) in m_t


def find_hist(tfile, region):
    """Return the 2D hist for a region, trying known name variants."""
    for name in ("MttvsMt" + region, "MttvsMt" + region.replace("24", "2024")):
        h = tfile.Get(name)
        if h:
            return h, name
    return None, None


def scan_hist(h, label):
    neg, zero = [], []
    nx, ny = h.GetNbinsX(), h.GetNbinsY()
    for ix in range(1, nx + 1):
        for iy in range(1, ny + 1):
            c = h.GetBinContent(ix, iy)
            if c < 0:
                neg.append((ix, iy, c))
            elif c == 0:
                zero.append((ix, iy))
    print("  [%s] %s  bins=%dx%d  integral=%.3f  negative=%d  empty=%d"
          % (label, h.GetName(), nx, ny, h.Integral(), len(neg), len(zero)))
    for ix, iy, c in neg[:20]:
        xlo = h.GetXaxis().GetBinLowEdge(ix)
        ylo = h.GetYaxis().GetBinLowEdge(iy)
        print("      NEG  ix=%d iy=%d  m_t>=%.0f  m_tt>=%.0f  content=%.4f"
              % (ix, iy, xlo, ylo, c))
    return neg


def scan_qcd(hdata, httbar, region):
    """Flag bins where Data - TTbar <= 0 (negative QCD), highlight Region1."""
    print("  [QCD = Data - TTbar] %s" % region)
    nx, ny = hdata.GetNbinsX(), hdata.GetNbinsY()
    bad, bad_sig = 0, 0
    for ix in range(1, nx + 1):
        xlo = hdata.GetXaxis().GetBinLowEdge(ix)
        xhi = hdata.GetXaxis().GetBinUpEdge(ix)
        in_sig = (xlo >= SIGSTART - 1e-6) and (xhi <= SIGEND + 1e-6)
        for iy in range(1, ny + 1):
            d = hdata.GetBinContent(ix, iy)
            t = httbar.GetBinContent(ix, iy)
            q = d - t
            if q <= 0:
                bad += 1
                tag = "  <-- SIG WINDOW (Region1)" if in_sig else ""
                if in_sig:
                    bad_sig += 1
                if bad <= 40 or in_sig:
                    ylo = hdata.GetYaxis().GetBinLowEdge(iy)
                    print("      Data-TTbar<=0  ix=%d iy=%d  m_t[%.0f,%.0f] m_tt>=%.0f"
                          "  data=%.3f ttbar=%.3f qcd=%.4f%s"
                          % (ix, iy, xlo, xhi, ylo, d, t, q, tag))
    print("    total Data-TTbar<=0 bins: %d  (of which in Region1/sig-window: %d)"
          % (bad, bad_sig))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="base input path (xrootd ok)")
    ap.add_argument("--signal", default="signalZPrime4000")
    args = ap.parse_args()

    files = {
        "Data": "%s/TTbarAllHad24_Data.root" % args.base,
        "TTbar": "%s/TTbarAllHad24_TTbar.root" % args.base,
        "Signal": "%s/TTbarAllHad24_%s.root" % (args.base, args.signal),
    }

    hists = {}
    for region in ("Cen24Pass", "Cen24Fail"):
        print("\n==================== %s ====================" % region)
        for proc, path in files.items():
            f = ROOT.TFile.Open(path)
            if not f or f.IsZombie():
                print("  CANNOT OPEN %s" % path)
                continue
            h, name = find_hist(f, region)
            if not h:
                print("  [%s] no MttvsMt%s histogram in %s" % (proc, region, path))
                f.Close()
                continue
            h.SetDirectory(0)
            hists[(region, proc)] = h
            scan_hist(h, proc)
            f.Close()
        d = hists.get((region, "Data"))
        t = hists.get((region, "TTbar"))
        if d and t:
            scan_qcd(d, t, region)


if __name__ == "__main__":
    main()
