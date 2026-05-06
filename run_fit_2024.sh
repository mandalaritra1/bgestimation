#!/usr/bin/env bash
set -euo pipefail

input_dir="/eos/user/a/amandal/ttbarhad_root_files/2dAlphabetInputs"

run_fit() {
    local cat="$1"
    local fit_dir="output/ttbarfits_${cat}_1x1/ttbar-RSGluon4000_area"

    python ttbar.py --cat "${cat}" --senario RSGluon --input "${input_dir}" --study fit --signal RSGluon4000 --skip-plots

    test -s "${fit_dir}/fitDiagnosticsTest.root"
    test -s "${fit_dir}/higgsCombineTest.FitDiagnostics.mH120.root"
    if grep -q "Fit failed" "${fit_dir}/FitDiagnostics.log"; then
        echo "FitDiagnostics failed for ${cat}. See ${fit_dir}/FitDiagnostics.log" >&2
        exit 1
    fi
    echo "FitDiagnostics succeeded for ${cat}: ${fit_dir}"
}

run_fit cen2024
run_fit fwd2024
