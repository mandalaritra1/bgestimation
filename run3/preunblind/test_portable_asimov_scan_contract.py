#!/usr/bin/env python3
"""Static command-boundary tests for the synthetic-Asimov scan canary."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import re


HERE = Path(__file__).resolve().parent


def main() -> int:
    worker = (HERE / "asimov_scan_portable_job.sh").read_text()
    builder = (HERE / "build_portable_asimov_scan_payload.sh").read_text()
    validator = (HERE / "validate_portable_asimov_scan.py").read_text()
    harvester = (HERE / "harvest_portable_asimov_scan.py").read_text()
    submit = (HERE / "asimov_scan_portable_canary.sub").read_text()

    assert "/uscms" not in worker and "/uscms_data" not in worker
    injected = re.search(r'^RINJECT="([0-9.]+)"$', worker, re.MULTILINE)
    scan_maximum = re.search(r'^SCAN_RMAX="([0-9.]+)"', worker, re.MULTILINE)
    assert injected and scan_maximum
    assert Decimal(scan_maximum.group(1)) == Decimal(5) * Decimal(injected.group(1))
    assert worker.count("combine -M GenerateOnly") == 1
    assert worker.count("combine -M MultiDimFit") == 1
    assert "-t -1 -s \"${TOY_SEED}\" --saveToys --toysFrequentist --bypassFrequentistFit" in worker
    assert "--expectSignal \"${RINJECT}\"" in worker
    assert "--algo grid --points \"${GRID_POINTS}\" --alignEdges 1" in worker
    assert "--rMin 0 --rMax \"${SCAN_RMAX}\"" in worker
    assert "--toysFile \"${TOY}\"" in worker
    assert "--rMax \"${PRODUCTION_RMAX}\"" not in worker
    assert worker.count('--setParameters "r=${RINJECT},${M_OFF}"') == 2
    assert worker.count('--freezeParameters "${M_FRZ}"') == 2
    assert '--freezeParameters "r,' not in worker
    assert "trap finalize_result EXIT" in worker and "artifact_hashes.sha256" in worker
    assert "text2workspace" not in worker and "combineTool.py" not in worker
    assert not re.search(r"mask_(?:cen|fwd)_[A-Za-z0-9_]*Pass_Region1\s*=\s*1", worker)
    assert "observed" not in worker.lower() and "data_obs" not in worker.lower()

    assert builder.count("higgsCombine_maskedBonly.MultiDimFit.mH0.root") == 1
    assert "card.txt" not in builder and "base.root" not in builder
    assert "production_rMax=${PRODUCTION_RMAX}" in builder
    assert "diagnostic_scan_rMax=${SCAN_RMAX}" in builder
    assert "refusing to overwrite payload" in builder
    assert "validate_portable_asimov_scan.py" in builder

    assert "expected {grid_points + 1} limit entries" in validator
    assert "scan contains negative deltaNLL" in validator
    assert "production rMax=1" in validator
    assert "expected 18 RPF variables" in validator
    assert "ROOT artifact set mismatch" in harvester
    assert "forbidden non-synthetic path" in harvester
    assert "queue 1" in submit
    assert "workspace_runtime_overlay_20260811_v1.tgz" in submit
    assert "asimov_scan_payload_w1_m2000.tgz" in submit
    assert "use_x509userproxy = false" in submit
    print("ASIMOV_SCAN_PORTABLE_CONTRACT_TEST_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
