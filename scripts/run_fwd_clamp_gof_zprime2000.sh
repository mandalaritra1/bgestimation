#!/usr/bin/env bash
set -uo pipefail

BASE_INPUT="root://eosuser.cern.ch//eos/user/a/amandal/ttbarhad_root_files/2dAlphabetInputs"
CLAMP_INPUT="test_inputs/ttbar_clamp_to_data_fwd24"
FIT_OUTPUT="output_clamp_fwd_zprime2000_r0to6"
SIGNAL="ZPrime2000"
MASS="2000"
NTOYS="${NTOYS:-200}"
NJOBS="${NJOBS:-20}"

mkdir -p test_inputs

echo "[1/4] Build forward clamp-to-data inputs"
python -u scripts/make_empty_data_floor_inputs.py \
  --base "${BASE_INPUT}" \
  --out "${CLAMP_INPUT}" \
  --year 24 \
  --signal "signal${SIGNAL}" \
  --regions Fwd24Pass Fwd24Fail \
  --ttbar-mode clamp-to-data \
  2>&1 | tee make_ttbar_clamp_to_data_fwd24.log

for tf in 2x1 2x2; do
  echo "[2/4] Fit fwd2024 TF ${tf} with clamp-to-data inputs"
  python -u ttbar.py \
    --cat fwd2024 \
    --senario ZPrime_1 \
    --input "${CLAMP_INPUT}" \
    --output "${FIT_OUTPUT}" \
    --signal "${SIGNAL}" \
    --study ftest \
    --tf "${tf}" \
    --rInit 0 \
    --rMin 0 \
    --rMax 6 \
    2>&1 | tee "output_ftest_fwd2024_${tf}_clampToData_${SIGNAL}_r0to6.log"

  area="${FIT_OUTPUT}/ttbarfits_fwd2024_ftest${tf}/ttbar-signal${SIGNAL}_area"
  echo "[3/4] Masked GoF fwd2024 TF ${tf}: ${area}"
  bash scripts/gof_masked.sh "${area}" "${MASS}" "${NTOYS}" "${NJOBS}" \
    2>&1 | tee "gof_masked_fwd2024_${SIGNAL}_${tf}_clampToData.log"
done

echo "[4/4] Summary"
for tf in 2x1 2x2; do
  area="${FIT_OUTPUT}/ttbarfits_fwd2024_ftest${tf}/ttbar-signal${SIGNAL}_area"
  echo "--- ${tf} ---"
  grep -E 'Best fit r|Fit failed|postfitshapes_s.root' "output_ftest_fwd2024_${tf}_clampToData_${SIGNAL}_r0to6.log" || true
  grep -E 'p-value|data stat|toys>=data' "gof_masked_fwd2024_${SIGNAL}_${tf}_clampToData.log" || true
  ls -lh "${area}"/gof_plot_masked_${MASS}.png "${area}"/gofmask.json 2>/dev/null || true
done
