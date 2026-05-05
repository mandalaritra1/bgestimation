#!/usr/bin/env bash
set -euo pipefail

input_dir="/eos/user/a/amandal/ttbarhad_root_files/2dAlphabetInputs"

python ttbar.py --cat cen2024 --senario RSGluon --input "${input_dir}" --study fit --signal RSGluon4000
python ttbar.py --cat fwd2024 --senario RSGluon --input "${input_dir}" --study fit --signal RSGluon4000
