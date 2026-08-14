#!/usr/bin/env python3
"""Export only blinded-safe channels from PostFit2DShapesFromWorkspace output."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any


GROUPS = ("cen_Cen24", "cen_Cen25", "fwd_Fwd24", "fwd_Fwd25")
EXPECTED_CHANNELS = tuple(
    f"{group}{tag}_Region{region}"
    for group in GROUPS
    for tag in ("Fail", "Pass")
    for region in (0, 1, 2)
)
DENIED_CHANNELS = tuple(f"{group}Pass_Region1" for group in GROUPS)
ALLOWED_CHANNELS = tuple(channel for channel in EXPECTED_CHANNELS if channel not in DENIED_CHANNELS)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def finite(value: float, label: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"non-finite {label}")
    return result


def edges(axis: Any, bins: int) -> list[float]:
    return [finite(axis.GetBinLowEdge(index), "axis edge") for index in range(1, bins + 2)]


def histogram_payload(histogram: Any) -> dict[str, object]:
    if histogram.InheritsFrom("TH2"):
        nx, ny = int(histogram.GetNbinsX()), int(histogram.GetNbinsY())
        return {
            "kind": "TH2",
            "x_edges": edges(histogram.GetXaxis(), nx),
            "y_edges": edges(histogram.GetYaxis(), ny),
            "values": [
                [finite(histogram.GetBinContent(ix, iy), "TH2 bin") for iy in range(1, ny + 1)]
                for ix in range(1, nx + 1)
            ],
            "errors": [
                [finite(histogram.GetBinError(ix, iy), "TH2 error") for iy in range(1, ny + 1)]
                for ix in range(1, nx + 1)
            ],
        }
    if histogram.InheritsFrom("TH1"):
        bins = int(histogram.GetNbinsX())
        return {
            "kind": "TH1",
            "edges": edges(histogram.GetXaxis(), bins),
            "values": [finite(histogram.GetBinContent(index), "TH1 bin") for index in range(1, bins + 1)],
            "errors": [finite(histogram.GetBinError(index), "TH1 error") for index in range(1, bins + 1)],
        }
    raise ValueError(f"unsupported postfit object class: {histogram.ClassName()}")


def directory_names(root_file: Any) -> set[str]:
    return {key.GetName() for key in root_file.GetListOfKeys() if key.GetClassName() == "TDirectoryFile"}


def sanitize(source: Path, output_root: Path, output_json: Path) -> dict[str, object]:
    for output in (output_root, output_json):
        if output.exists():
            raise ValueError(f"refusing to overwrite output: {output}")
    try:
        import ROOT
    except ImportError as error:
        raise ValueError("PyROOT is required to sanitize 2D postfit shapes") from error
    ROOT.gROOT.SetBatch(True)
    source_file = ROOT.TFile.Open(str(source))
    if not source_file or source_file.IsZombie():
        raise ValueError(f"cannot open 2D postfit ROOT: {source}")
    temporary_root = output_root.with_name(f".{output_root.name}.tmp")
    temporary_json = output_json.with_name(f".{output_json.name}.tmp")
    destination = None
    try:
        expected_directories = {f"{channel}_postfit" for channel in EXPECTED_CHANNELS}
        present_directories = directory_names(source_file)
        if present_directories != expected_directories:
            raise ValueError(
                "postfit directory set mismatch; "
                f"missing={sorted(expected_directories-present_directories)} "
                f"extra={sorted(present_directories-expected_directories)}"
            )
        destination = ROOT.TFile.Open(str(temporary_root), "RECREATE")
        if not destination or destination.IsZombie():
            raise ValueError(f"cannot create safe 2D postfit ROOT: {temporary_root}")
        channels: dict[str, object] = {}
        for channel in ALLOWED_CHANNELS:
            directory_name = f"{channel}_postfit"
            source_directory = source_file.Get(directory_name)
            names = {key.GetName() for key in source_directory.GetListOfKeys()}
            required = {"TotalBkg", "data_obs"}
            if not required.issubset(names):
                raise ValueError(
                    f"{directory_name} lacks required objects {sorted(required-names)}; "
                    f"available={sorted(names)}"
                )
            destination.mkdir(directory_name)
            destination.cd(directory_name)
            channel_record: dict[str, object] = {}
            for name in sorted(required):
                histogram = source_directory.Get(name)
                payload = histogram_payload(histogram)
                clone = histogram.Clone(name)
                clone.SetDirectory(destination.GetDirectory(directory_name))
                clone.Write()
                channel_record[name] = payload
            if channel_record["TotalBkg"]["kind"] != channel_record["data_obs"]["kind"]:
                raise ValueError(f"model/data dimensionality mismatch in {directory_name}")
            channels[channel] = channel_record
        destination.Write()
        destination.Close()
        destination = None
        result = {
            "schema_version": 1,
            "dataset_scope": "masked_observed_sidebands_only",
            "fit_hypothesis": "background_only_r_fixed_zero",
            "mask_policy": "all_four_pass_region1_on_and_frozen",
            "source_tool": "PostFit2DShapesFromWorkspace",
            "source_postfit2d_sha256": sha256_file(source),
            "allowed_channels": list(ALLOWED_CHANNELS),
            "denied_channels": list(DENIED_CHANNELS),
            "channels": channels,
        }
        temporary_json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        temporary_root.replace(output_root)
        temporary_json.replace(output_json)
        return result
    finally:
        if destination:
            destination.Close()
        source_file.Close()
        temporary_root.unlink(missing_ok=True)
        temporary_json.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    args = parser.parse_args()
    result = sanitize(args.source, args.output_root, args.output_json)
    print(json.dumps({
        "MASKED_POSTFIT_2D_SANITIZE_OK": True,
        "allowed_channels": len(result["allowed_channels"]),
        "denied_channels": len(result["denied_channels"]),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, TypeError) as error:
        print(f"MASKED_POSTFIT_2D_SANITIZE_FAILED: {error}", file=sys.stderr)
        raise SystemExit(2)
