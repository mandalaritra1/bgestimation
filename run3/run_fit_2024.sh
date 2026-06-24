#!/usr/bin/env bash
set -euo pipefail

# LPC access to CERNBox EOS.
BASE_INPUT="${BASE_INPUT:-root://eosuser.cern.ch//eos/user/a/amandal/ttbarhad_root_files/2dAlphabetInputs}"
SCENARIO="${SCENARIO:-ZPrime_1}"
SIGNAL="${SIGNAL:-ZPrime4000}"

run_fit() {
  local cat="$1"
  local log="$2"

  python -u ttbar.py --cat "${cat}" --senario "${SCENARIO}" --input "${BASE_INPUT}" --signal "${SIGNAL}" 2>&1 \
    | tee "${log}" \
    | sed "s/^/[${cat}] /"
}

run_fit cen2024 "output_2024_${SIGNAL}_cen.log" &
cen_pid=$!

run_fit fwd2024 "output_2024_${SIGNAL}_fwd.log" &
fwd_pid=$!

wait "${cen_pid}" "${fwd_pid}"
