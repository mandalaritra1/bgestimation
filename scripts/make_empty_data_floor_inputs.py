#!/usr/bin/env python
"""Build test 2DAlphabet inputs with TTbar adjusted using Data masks.

This is a diagnostic helper for sparse 2024 templates. It copies the requested
Data, signal, and TTbar ROOT files from an input directory to a local output
directory. Data and signal are copied unchanged. In TTbar files, bins can be
set to zero where nominal Data is empty, or clamped down to nominal Data when
TTbar exceeds Data in the same region/bin.

Physics note: this deliberately modifies the TTbar template using observed
Data. It should be used as a fit-stability diagnostic only, not as a silent
replacement for nominal template production.
"""
import argparse
import os

import ROOT

ROOT.gROOT.SetBatch(True)


DEFAULT_SYSTEMATICS = (
    "pileup24",
    "pdf24",
    "jes24",
    "jer24",
    "q2_24",
    "ttag_pt1_24",
)


def input_path(base, filename):
    return base.rstrip("/") + "/" + filename


def hist_region_name(hist_name, regions):
    for region in regions:
        if hist_name.startswith("MttvsMt" + region):
            return region
    return None


def load_data_masks(base, year, regions):
    data_file = ROOT.TFile.Open(input_path(base, "TTbarAllHad%s_Data.root" % year))
    if not data_file or data_file.IsZombie():
        raise RuntimeError("Could not open Data input from %s" % base)

    masks = {}
    for region in regions:
        hist = data_file.Get("MttvsMt" + region)
        if not hist:
            data_file.Close()
            raise RuntimeError("Missing data histogram MttvsMt%s" % region)
        hist.SetDirectory(0)
        masks[region] = hist
    data_file.Close()
    return masks


def adjust_ttbar_bins(hist, data_hist, mode):
    changed = 0
    removed = 0.0
    for ix in range(1, hist.GetNbinsX() + 1):
        for iy in range(1, hist.GetNbinsY() + 1):
            data_content = data_hist.GetBinContent(ix, iy)
            content = hist.GetBinContent(ix, iy)
            error = hist.GetBinError(ix, iy)

            if mode == "empty-zero":
                if data_content != 0:
                    continue
                new_content = 0.0
                new_error = 0.0
            elif mode == "clamp-to-data":
                if content <= data_content:
                    continue
                new_content = data_content
                new_error = min(error, data_hist.GetBinError(ix, iy))
            else:
                raise RuntimeError("Unknown TTbar adjustment mode: %s" % mode)

            if content == new_content and error == new_error:
                continue
            removed += content - new_content
            changed += 1
            hist.SetBinContent(ix, iy, new_content)
            hist.SetBinError(ix, iy, new_error)
    return changed, removed


def copy_object(obj, masks, regions, ttbar_mode, totals):
    clone = obj.Clone()
    clone.SetDirectory(0)
    if ttbar_mode and clone.InheritsFrom("TH2"):
        region = hist_region_name(clone.GetName(), regions)
        if region:
            changed, removed = adjust_ttbar_bins(clone, masks[region], ttbar_mode)
            totals[region]["changed"] += changed
            totals[region]["removed"] += removed
    clone.Write()


def copy_directory(src_dir, dst_dir, masks, regions, ttbar_mode, totals):
    dst_dir.cd()
    for key in src_dir.GetListOfKeys():
        obj = key.ReadObj()
        if obj.InheritsFrom("TDirectory"):
            subdir = dst_dir.mkdir(obj.GetName())
            copy_directory(obj, subdir, masks, regions, ttbar_mode, totals)
        else:
            copy_object(obj, masks, regions, ttbar_mode, totals)
        dst_dir.cd()


def copy_root_file(src_path, dst_path, masks, regions, ttbar_mode=None):
    src = ROOT.TFile.Open(src_path)
    if not src or src.IsZombie():
        raise RuntimeError("Could not open input file %s" % src_path)

    dst = ROOT.TFile.Open(dst_path, "RECREATE")
    if not dst or dst.IsZombie():
        src.Close()
        raise RuntimeError("Could not create output file %s" % dst_path)

    totals = {region: {"changed": 0, "removed": 0.0} for region in regions}
    copy_directory(src, dst, masks, regions, ttbar_mode, totals)
    dst.Close()
    src.Close()
    return totals


def required_filenames(year, signal, systematics):
    files = [
        "TTbarAllHad%s_Data.root" % year,
        "TTbarAllHad%s_TTbar.root" % year,
        "TTbarAllHad%s_%s.root" % (year, signal),
    ]
    for process in ("TTbar", signal):
        for syst in systematics:
            files.append("TTbarAllHad%s_%s_%s_up.root" % (year, process, syst))
            files.append("TTbarAllHad%s_%s_%s_down.root" % (year, process, syst))
    return files


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True, help="Input directory; xrootd paths are ok")
    parser.add_argument("--out", required=True, help="Local output directory for test inputs")
    parser.add_argument("--year", default="24")
    parser.add_argument("--signal", default="signalZPrime4000")
    parser.add_argument(
        "--regions",
        nargs="+",
        default=["Cen24Pass", "Cen24Fail"],
        help="Regions whose TTbar bins should be floored using matching Data masks",
    )
    parser.add_argument(
        "--systematics",
        nargs="+",
        default=list(DEFAULT_SYSTEMATICS),
        help="Optional systematic filename tokens to copy for TTbar and signal",
    )
    parser.add_argument(
        "--include-systematic-files",
        action="store_true",
        help="Also copy separate *_syst_up/down ROOT files. This is off by default because the current inputs store systematic histograms in the nominal files.",
    )
    parser.add_argument(
        "--ttbar-mode",
        choices=["empty-zero", "clamp-to-data"],
        default="empty-zero",
        help="Diagnostic TTbar adjustment to apply in the requested regions.",
    )
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)
    masks = load_data_masks(args.base, args.year, args.regions)

    summary = {}
    systematics = args.systematics if args.include_systematic_files else []
    for filename in required_filenames(args.year, args.signal, systematics):
        source = input_path(args.base, filename)
        target = os.path.join(args.out, filename)
        ttbar_mode = args.ttbar_mode if filename.startswith("TTbarAllHad%s_TTbar" % args.year) else None
        summary[filename] = copy_root_file(source, target, masks, args.regions, ttbar_mode)
        print("wrote %s%s" % (target, "  [TTbar %s]" % ttbar_mode if ttbar_mode else ""))

    print("\nTTbar bins changed using nominal Data masks:")
    for filename, totals in summary.items():
        if not filename.startswith("TTbarAllHad%s_TTbar" % args.year):
            continue
        for region in args.regions:
            info = totals[region]
            if info["changed"]:
                print("  %-45s %-10s bins=%5d removed=% .6g" %
                      (filename, region, info["changed"], info["removed"]))


if __name__ == "__main__":
    main()
