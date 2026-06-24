#!/usr/bin/env bash
set -uo pipefail

BASE_INPUT="${BASE_INPUT:-test_inputs/empty_data_floor_cen24_v3}"
OUTPUT_DIR="${OUTPUT_DIR:-output_floor_scan}"
SIGNAL="${SIGNAL:-ZPrime4000}"
SCENARIO="${SCENARIO:-ZPrime_1}"
CAT="${CAT:-cen2024_rebin}"
TF_LIST=("${@:-0x0 0x1 1x0 1x1 1x2 2x1 2x2}")

if [[ $# -eq 0 ]]; then
  TF_LIST=(0x0 0x1 1x0 1x1 1x2 2x1 2x2)
fi

mkdir -p "${OUTPUT_DIR}"
SUMMARY="${OUTPUT_DIR}/tf_scan_status.tsv"
printf "tf\texit_code\tfit_failed\tbest_fit_r\tpostfit_s\tlog\n" > "${SUMMARY}"

for tf in "${TF_LIST[@]}"; do
  log="output_ftest_${CAT}_floor_${tf}.log"
  area="${OUTPUT_DIR}/ttbarfits_${CAT}_ftest${tf}/ttbar-signal${SIGNAL}_area"

  echo "===== TF ${tf} START $(date) ====="
  python -u ttbar.py \
    --cat "${CAT}" \
    --senario "${SCENARIO}" \
    --input "${BASE_INPUT}" \
    --output "${OUTPUT_DIR}" \
    --signal "${SIGNAL}" \
    --study ftest \
    --tf "${tf}" 2>&1 | tee "${log}"
  status=${PIPESTATUS[0]}

  fit_failed=$(grep -c "Fit failed" "${log}" 2>/dev/null || true)
  best_fit=$(grep "Best fit r:" "${log}" 2>/dev/null | tail -1 | sed 's/^[[:space:]]*//')
  [[ -n "${best_fit}" ]] || best_fit="NA"
  if [[ -f "${area}/postfitshapes_s.root" ]]; then
    postfit_s="yes"
  else
    postfit_s="no"
  fi

  printf "%s\t%s\t%s\t%s\t%s\t%s\n" \
    "${tf}" "${status}" "${fit_failed}" "${best_fit}" "${postfit_s}" "${log}" \
    | tee -a "${SUMMARY}"
  echo "===== TF ${tf} EXIT ${status} $(date) ====="
done

echo "Summary: ${SUMMARY}"
