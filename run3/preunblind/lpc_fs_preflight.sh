#!/bin/bash
set -euo pipefail

echo "host=$(hostname -f)"
echo "pwd=${PWD}"
for path in \
    /uscms \
    /uscms_data \
    /uscms_data/d3/amandal2/bg_ttbar/CMSSW_14_1_0_pre4/src/bgestimation \
    /cvmfs/cms.cern.ch/cmsset_default.sh
do
    if [[ -r "${path}" ]]; then
        echo "READABLE ${path}"
    else
        echo "UNREADABLE ${path}"
    fi
done

