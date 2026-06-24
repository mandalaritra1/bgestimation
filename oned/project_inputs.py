#!/usr/bin/env python3
"""Project the 2DAlphabet (m_SD, m_tt) TH2 inputs onto the 1D m_tt axis.

Shared foundation for the 1D cross-check methods in `oned/`. Reads the same
`TTbarAllHad24_*.root` inputs 2DAlphabet uses, takes the `ProjectionY` (m_tt) of
the Pass/Fail regions (optionally inside an m_SD window), and writes 1D templates
for data / ttbar / signal to a single ROOT file.

Run from the bgestimation repo root with the CMSSW+Combine+twoD-env active:

    python oned/project_inputs.py --cat cen24 --signal signalZPrime4000

Output: oned/out/oned_inputs_<cat>.root with keys
    data_obs_Pass, data_obs_Fail, ttbar_Pass, ttbar_Fail, signal_Pass, signal_Fail
"""
from __future__ import annotations

import argparse
import os

import ROOT

ROOT.gROOT.SetBatch(True)

# default EOS location (fuse mount on lxplus; xrootd also works from LPC)
DEFAULT_INPUT = "/eos/user/a/amandal/ttbarhad_root_files/2dAlphabetInputs"

# process -> input file token (file name is TTbarAllHad<token>.root)
FILE_TOKEN = {
    "data_obs": "24_Data",
    "ttbar": "24_TTbar",
    # signal token is supplied via --signal, e.g. 24_signalZPrime4000
}


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--cat", default="cen24", choices=["cen24", "fwd24"],
                   help="category / region prefix (default: cen24)")
    p.add_argument("--signal", default="signalZPrime4000",
                   help="signal name, matches TTbarAllHad24_<signal>.root (default: signalZPrime4000)")
    p.add_argument("--input", default=DEFAULT_INPUT, help="input directory (EOS)")
    p.add_argument("--msd-min", type=float, default=None,
                   help="lower jet m_SD edge for the projection window (GeV); default: full range")
    p.add_argument("--msd-max", type=float, default=None,
                   help="upper jet m_SD edge for the projection window (GeV); default: full range")
    p.add_argument("--out", default=None, help="output ROOT file (default: oned/out/oned_inputs_<cat>.root)")
    return p.parse_args()


def _region_cap(cat: str) -> str:
    """cen24 -> Cen24, fwd24 -> Fwd24 (matches the MttvsMt<Region> hist names)."""
    return cat[:1].upper() + cat[1:]


def _project_y(h2: ROOT.TH2, name: str, msd_min, msd_max) -> ROOT.TH1:
    """ProjectionY (m_tt) over an optional m_SD (X) window."""
    ax = h2.GetXaxis()
    b1 = ax.FindBin(msd_min + 1e-6) if msd_min is not None else 1
    b2 = ax.FindBin(msd_max - 1e-6) if msd_max is not None else ax.GetNbins()
    proj = h2.ProjectionY(name, b1, b2, "e")
    proj.SetDirectory(0)
    proj.SetTitle(name)
    return proj


def main() -> int:
    args = _parse_args()
    region = _region_cap(args.cat)  # Cen24 / Fwd24
    tokens = dict(FILE_TOKEN, signal="24_" + args.signal)

    out_path = args.out or os.path.join("oned", "out", f"oned_inputs_{args.cat}.root")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    win = ""
    if args.msd_min is not None or args.msd_max is not None:
        win = f"  (m_SD window [{args.msd_min}, {args.msd_max}])"
    print(f"[project_inputs] cat={args.cat} signal={args.signal}{win}")

    fout = ROOT.TFile.Open(out_path, "RECREATE")
    integrals = {}
    for proc, token in tokens.items():
        fpath = os.path.join(args.input, f"TTbarAllHad{token}.root")
        fin = ROOT.TFile.Open(fpath)
        if not fin or fin.IsZombie():
            print(f"  !! cannot open {fpath}")
            return 1
        for reg in ("Pass", "Fail"):
            hname = f"MttvsMt{region}{reg}"
            h2 = fin.Get(hname)
            if not h2:
                print(f"  !! {hname} missing in {os.path.basename(fpath)}")
                fin.Close()
                return 1
            key = f"{proc}_{reg}"
            proj = _project_y(h2, key, args.msd_min, args.msd_max)
            integrals[key] = proj.Integral()
            fout.cd()
            proj.Write(key)
        fin.Close()

    fout.Close()
    print(f"  wrote {out_path}")
    for k in ("data_obs_Pass", "data_obs_Fail", "ttbar_Pass", "ttbar_Fail",
              "signal_Pass", "signal_Fail"):
        print(f"    {k:16s} integral = {integrals.get(k, float('nan')):10.2f}")
    # quick sanity: data - ttbar in Pass is the QCD-like remainder the 1D fit must describe
    qcdish = integrals.get("data_obs_Pass", 0) - integrals.get("ttbar_Pass", 0)
    print(f"    (data-ttbar)_Pass  ~= {qcdish:10.2f}   <- 1D background scale")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
