#!/usr/bin/env bash
set -euo pipefail

input_dir="/uscms_data/d1/amandal2/2dalphabet/CMSSW_11_3_4/src/2DAlphabet/rootfiles"

python ttbar.py --cat cen2024 --senario RSGluon --input "${input_dir}" --study fit --signal RSGluon4000
python ttbar.py --cat fwd2024 --senario RSGluon --input "${input_dir}" --study fit --signal RSGluon4000
