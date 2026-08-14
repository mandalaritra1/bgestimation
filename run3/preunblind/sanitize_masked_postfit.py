#!/usr/bin/env python3
"""Copy only blinded-safe postfit channels from a FitDiagnostics ROOT file."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any


CHANNEL_GROUPS = ("cen_Cen24", "cen_Cen25", "fwd_Fwd24", "fwd_Fwd25")
ALLOWED_CHANNELS = tuple(
    f"{group}{tag}_Region{region}"
    for group in CHANNEL_GROUPS
    for tag, regions in (("Fail", (0, 1, 2)), ("Pass", (0, 2)))
    for region in regions
)
DENIED_CHANNELS = tuple(f"{group}Pass_Region1" for group in CHANNEL_GROUPS)
# With ``FitDiagnostics --skipSBFit`` on the validated snapshot, the fitted
# background model is saved in ``shapes_fit_b``.  ``shapes_prefit`` contains
# only the data graph in this workflow and is not a model projection.
SHAPE_SETS = ("shapes_fit_b",)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def import_root():
    try:
        import ROOT
    except ImportError as error:
        raise ValueError("PyROOT is required to sanitize FitDiagnostics shapes") from error
    ROOT.gROOT.SetBatch(True)
    return ROOT


def finite(value: float, label: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"non-finite {label}")
    return result


def object_payload(obj: Any) -> dict[str, object]:
    if obj.InheritsFrom("TH1"):
        bins = int(obj.GetNbinsX())
        return {
            "kind": "TH1",
            "edges": [finite(obj.GetXaxis().GetBinLowEdge(i), "bin edge") for i in range(1, bins + 2)],
            "values": [finite(obj.GetBinContent(i), "bin content") for i in range(1, bins + 1)],
            "errors": [finite(obj.GetBinError(i), "bin error") for i in range(1, bins + 1)],
        }
    if obj.InheritsFrom("TGraph"):
        points = int(obj.GetN())
        payload: dict[str, object] = {
            "kind": "TGraph",
            "x": [finite(obj.GetPointX(i), "graph x") for i in range(points)],
            "y": [finite(obj.GetPointY(i), "graph y") for i in range(points)],
        }
        if obj.InheritsFrom("TGraphAsymmErrors"):
            payload.update({
                "xerr_low": [finite(obj.GetErrorXlow(i), "graph x error") for i in range(points)],
                "xerr_high": [finite(obj.GetErrorXhigh(i), "graph x error") for i in range(points)],
                "yerr_low": [finite(obj.GetErrorYlow(i), "graph y error") for i in range(points)],
                "yerr_high": [finite(obj.GetErrorYhigh(i), "graph y error") for i in range(points)],
            })
        return payload
    raise ValueError(f"unsupported postfit object class: {obj.ClassName()}")


def directory_names(directory: Any) -> set[str]:
    return {key.GetName() for key in directory.GetListOfKeys() if key.GetClassName() == "TDirectoryFile"}


def sanitize(source: Path, output_root: Path, output_json: Path) -> dict[str, object]:
    for output in (output_root, output_json):
        if output.exists():
            raise ValueError(f"refusing to overwrite output: {output}")
    ROOT = import_root()
    source_file = ROOT.TFile.Open(str(source))
    if not source_file or source_file.IsZombie():
        raise ValueError(f"cannot open FitDiagnostics ROOT: {source}")
    temporary_root = output_root.with_name(f".{output_root.name}.tmp")
    temporary_json = output_json.with_name(f".{output_json.name}.tmp")
    destination = None
    try:
        destination = ROOT.TFile.Open(str(temporary_root), "RECREATE")
        if not destination or destination.IsZombie():
            raise ValueError(f"cannot create safe ROOT output: {temporary_root}")
        shape_records: dict[str, object] = {}
        for shape_set in SHAPE_SETS:
            source_shapes = source_file.Get(shape_set)
            if not source_shapes:
                raise ValueError(f"FitDiagnostics ROOT lacks {shape_set}")
            channels = directory_names(source_shapes)
            expected = set(ALLOWED_CHANNELS) | set(DENIED_CHANNELS)
            if channels != expected:
                raise ValueError(
                    f"{shape_set} channel set mismatch; missing={sorted(expected - channels)} "
                    f"extra={sorted(channels - expected)}"
                )
            destination.mkdir(shape_set)
            shape_records[shape_set] = {}
            for channel in ALLOWED_CHANNELS:
                source_channel = source_shapes.Get(channel)
                if not source_channel:
                    raise ValueError(f"missing allowed channel {shape_set}/{channel}")
                object_names = [key.GetName() for key in source_channel.GetListOfKeys()]
                # FitDiagnostics always creates ``total`` for a saved channel.
                # ``total_background`` is conditional on Combine's process
                # classification, so it is not a portable schema invariant.
                required_objects = {"total", "data"}
                if not required_objects.issubset(object_names):
                    raise ValueError(
                        f"{shape_set}/{channel} lacks required objects: "
                        f"{sorted(required_objects - set(object_names))}; "
                        f"available={sorted(object_names)}"
                    )
                destination.cd(shape_set)
                current = destination.GetDirectory(shape_set)
                current.mkdir(channel)
                destination.cd(f"{shape_set}/{channel}")
                channel_record: dict[str, object] = {}
                for name in object_names:
                    obj = source_channel.Get(name)
                    if not obj:
                        raise ValueError(f"cannot read {shape_set}/{channel}/{name}")
                    # ``--saveWithUncertainties`` also writes ``total_covar``
                    # as TH2.  Keep the portable projection contract explicitly
                    # one-dimensional; fit-parameter correlations are packaged
                    # separately by the masked-fit diagnostics workflow.
                    if obj.InheritsFrom("TH2"):
                        continue
                    clone = obj.Clone(name)
                    clone.Write()
                    channel_record[name] = object_payload(obj)
                shape_records[shape_set][channel] = channel_record
        destination.Write()
        destination.Close()
        destination = None
        result = {
            "schema_version": 1,
            "dataset_scope": "masked_observed_sidebands_only",
            "fit_hypothesis": "background_only_r_fixed_zero",
            "mask_policy": "all_four_pass_region1_on_and_frozen",
            "allowed_channels": list(ALLOWED_CHANNELS),
            "denied_channels": list(DENIED_CHANNELS),
            "source_fitdiagnostics_sha256": sha256_file(source),
            "shape_sets": shape_records,
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
        "MASKED_POSTFIT_SANITIZE_OK": True,
        "allowed_channels": len(result["allowed_channels"]),
        "denied_channels": len(result["denied_channels"]),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        print(f"MASKED_POSTFIT_SANITIZE_FAILED: {error}", file=sys.stderr)
        raise SystemExit(2)
