#!/usr/bin/env python3
"""Static command-boundary test for the reviewed 10x20 masked-GoF descriptor."""

from __future__ import annotations

from pathlib import Path
import re


HERE = Path(__file__).resolve().parent


def main() -> int:
    submit = (HERE / "gof_portable_ensemble_200.sub").read_text()
    worker = (HERE / "gof_portable_job.sh").read_text()
    seeds = [int(value) for value in re.findall(r"^314\d+$", submit, re.MULTILINE)]
    assert seeds == list(range(314160, 314170))
    assert len(set(seeds)) == 10
    assert "arguments = gof_portable_job.sh 1 2000 1 $(seed) 20" in submit
    assert "queue seed from" in submit
    assert "transfer_output_remaps" in submit and "w1_m2000_seed$(seed)_n20.tgz" in submit
    assert "use_x509userproxy = false" in submit
    assert "when_to_transfer_output = ON_EXIT" in submit
    assert worker.count("combine -M GoodnessOfFit") == 2
    assert "--toysFrequentist -t \"${TOY_COUNT}\" -s \"${TOY_SEED}\"" in worker
    assert "M_OFF" not in worker
    print("PORTABLE_GOF_ENSEMBLE_CONTRACT_TEST_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
