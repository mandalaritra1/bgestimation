#!/usr/bin/env python3
"""Synthetic archive tests for the fail-closed Asimov-scan harvester."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile


HERE = Path(__file__).resolve().parent


def load_harvester():
    path = HERE / "harvest_portable_asimov_scan.py"
    spec = importlib.util.spec_from_file_location("harvest_portable_asimov_scan", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def add_bytes(archive: tarfile.TarFile, name: str, payload: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    archive.addfile(info, io.BytesIO(payload))


def main() -> int:
    harvester = load_harvester()
    prefix = harvester.PREFIX
    validation = {
        "schema_version": 1, "method": "MultiDimFit_grid", "dataset_scope": "synthetic_asimov_only",
        "production_rMax": 1.0, "diagnostic_scan_rMax": 0.0847167987375,
        "grid_points": 41, "limit_tree_entries": 42, "scan_point_count": 41,
        "scan_sha256": "a" * 64, "deltaNLL_min": 0.0, "deltaNLL_max": 3.0,
    }
    snapshot = {
        "schema_version": 1, "snapshot_name": "MultiDimFit", "snapshot_sha256": "b" * 64,
        "production_r_range": [0.0, 1.0],
        "required_masks": [
            "mask_cen_Cen24Pass_Region1", "mask_cen_Cen25Pass_Region1",
            "mask_fwd_Fwd24Pass_Region1", "mask_fwd_Fwd25Pass_Region1",
        ],
        "rpf_count": 18, "positive_rpf_par0_count": 4,
    }
    area = {
        harvester.TOY: b"root toy", harvester.SCAN: b"root scan",
        "snapshot_validation.json": json.dumps(snapshot).encode(),
        "asimov_scan_validation.json": json.dumps(validation).encode(),
    }
    status = dict(harvester.EXPECTED_STATUS)
    status.update({"snapshot_sha256": "b" * 64, "payload_sha256": "c" * 64, "runtime_sha256": "d" * 64})
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source = root / "result.tgz"
        hashes = "".join(
            f"{hashlib.sha256(payload).hexdigest()}  area/{name}\n" for name, payload in area.items()
        )
        with tarfile.open(source, "w:gz") as archive:
            for name, payload in area.items():
                add_bytes(archive, f"{prefix}/area/{name}", payload)
            add_bytes(archive, f"{prefix}/status.txt", "".join(f"{key}={value}\n" for key, value in status.items()).encode())
            add_bytes(archive, f"{prefix}/artifact_hashes.sha256", hashes.encode())
        validated = harvester.validate_archive(source)
        assert validated["scan_validation"]["scan_point_count"] == 41
    print("ASIMOV_SCAN_HARVEST_TEST_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
