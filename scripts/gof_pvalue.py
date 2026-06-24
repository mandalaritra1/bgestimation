#!/usr/bin/env python
"""Compute the saturated-GoF p-value from Combine output ROOT files in an area.

p-value = fraction of toys with test statistic >= the observed (data) value.

Usage:
  python scripts/gof_pvalue.py <signal_area_dir>
"""
import glob
import os
import sys
import ROOT


def stats_from(path):
    f = ROOT.TFile.Open(path)
    t = f.Get("limit")
    vals = []
    for i in range(t.GetEntries()):
        t.GetEntry(i)
        vals.append(t.limit)
    f.Close()
    return vals


def main():
    area = sys.argv[1]
    files = sorted(glob.glob(os.path.join(area, "*GoodnessOfFit*.root")))
    if not files:
        print("No GoodnessOfFit files in %s" % area)
        return
    # The data run has exactly 1 entry; toy runs have many.
    data_val, toys = None, []
    for path in files:
        vals = stats_from(path)
        if len(vals) == 1 and data_val is None:
            data_val = vals[0]
        else:
            toys.extend(vals)
    if data_val is None and toys:
        # fall back: smallest single-entry file
        data_val = toys.pop(0)
    n = len(toys)
    worse = sum(1 for v in toys if v >= data_val)
    pval = worse / float(n) if n else float("nan")
    print("area: %s" % area)
    print("  data stat = %.3f   ntoys = %d   toys>=data = %d   p-value = %.3f"
          % (data_val, n, worse, pval))
    if toys:
        toys_sorted = sorted(toys)
        mean = sum(toys) / float(n)
        print("  toys: min=%.1f  max=%.1f  mean=%.1f  median=%.1f"
              % (toys_sorted[0], toys_sorted[-1], mean, toys_sorted[n // 2]))


if __name__ == "__main__":
    main()
