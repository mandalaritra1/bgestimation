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
import json
import os
import re

import numpy as np
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

# Signal-normalisation constants, mirroring ttbar.py so the 1D `r` is on the same
# footing as the 2DAlphabet fit. The ZPrime raw templates are normalised to a
# generic 10 pb; per-mass we rescale so r=1 <-> the as-run ('expected') xsec.
RAW_SIGNAL_XSEC_PB = 10.0
SENARIO_XS_KEY = {"ZPrime_1": "ZPrime1", "ZPrime_10": "ZPrime10",
                  "ZPrime_30": "ZPrime30", "RSGluon": "RSGluon"}


def signal_scale(signal: str, scenario: str, xs_json: str = "jsons/signal_xs.json") -> float:
    """SCALE applied to the raw signal template so r=1 <-> as-run xsec (ZPrime_1).

    Reproduces ttbar.py's per-mass theory scaling: SCALE = expected_xsec / 10 pb,
    with log-linear interpolation in mass. Returns 1.0 if it cannot be computed
    (the caller then uses the raw 10 pb template)."""
    key = SENARIO_XS_KEY.get(scenario)
    m = re.search(r"(\d{3,4})(?:_\d+)?\s*$", signal)
    if key is None or m is None or not os.path.exists(xs_json):
        return 1.0
    entry = json.load(open(xs_json)).get(key)
    if not entry:
        return 1.0
    mass_tev = int(m.group(1)) / 1000.0
    masses, xs = entry["mass"], entry["expected"]
    for mm, tt in zip(masses, xs):
        if abs(mm - mass_tev) < 1e-6:
            xsec = tt
            break
    else:
        xsec = float(np.exp(np.interp(mass_tev, masses, np.log(xs))))
    return xsec / RAW_SIGNAL_XSEC_PB


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--cat", default="cen24", choices=["cen24", "fwd24"],
                   help="category / region prefix (default: cen24)")
    p.add_argument("--signal", default="signalZPrime4000",
                   help="signal name, matches TTbarAllHad24_<signal>.root (default: signalZPrime4000)")
    p.add_argument("--scenario", default="ZPrime_1",
                   choices=list(SENARIO_XS_KEY),
                   help="signal scenario for the per-mass r=1<->xsec scale (default: ZPrime_1)")
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

    sscale = signal_scale(args.signal, args.scenario)

    win = ""
    if args.msd_min is not None or args.msd_max is not None:
        win = f"  (m_SD window [{args.msd_min}, {args.msd_max}])"
    print(f"[project_inputs] cat={args.cat} signal={args.signal} "
          f"scenario={args.scenario} signal_SCALE={sscale:.6g}{win}")

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
            if proc == "signal" and sscale != 1.0:
                proj.Scale(sscale)  # r=1 <-> as-run xsec, matching the 2D fit
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
