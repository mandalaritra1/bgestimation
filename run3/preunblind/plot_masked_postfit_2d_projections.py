#!/usr/bin/env python3
"""Project sanitized 2D masked-data postfit shapes onto m(ttbar)."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mplhep as hep
import numpy as np


hep.style.use(hep.style.CMS)

CHANNEL = re.compile(
    r"^(?P<topology>cen|fwd)_(?P<label>Cen|Fwd)(?P<year>24|25)"
    r"(?P<tag>Pass|Fail)_Region(?P<region>[012])$"
)
EXPECTED_CHANNELS = {
    f"{topology}_{label}{year}{tag}_Region{region}"
    for topology, label in (("cen", "Cen"), ("fwd", "Fwd"))
    for year in ("24", "25")
    for tag, regions in (("Fail", (0, 1, 2)), ("Pass", (0, 2)))
    for region in regions
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def finite_array(values: object, label: str, dimensions: int) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if array.ndim != dimensions or array.size == 0 or not np.all(np.isfinite(array)):
        raise ValueError(f"invalid {label}")
    return array


def project_y(payload: object, label: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    if not isinstance(payload, dict) or payload.get("kind") != "TH2":
        raise ValueError(f"{label} is not a TH2 payload")
    x_edges = finite_array(payload.get("x_edges"), f"{label} x edges", 1)
    y_edges = finite_array(payload.get("y_edges"), f"{label} y edges", 1)
    values = finite_array(payload.get("values"), f"{label} values", 2)
    errors = finite_array(payload.get("errors"), f"{label} errors", 2)
    if values.shape != errors.shape or values.shape != (len(x_edges) - 1, len(y_edges) - 1):
        raise ValueError(f"inconsistent {label} binning")
    if np.any(values < 0) or np.any(errors < 0) or np.any(np.diff(x_edges) <= 0) or np.any(np.diff(y_edges) <= 0):
        raise ValueError(f"negative or non-monotonic {label}")
    return y_edges, np.sum(values, axis=0), np.sqrt(np.sum(errors**2, axis=0)), values.shape[0]


def step_band(ax, edges: np.ndarray, center: np.ndarray, error: np.ndarray, **kwargs: object) -> None:
    low = np.maximum(center - error, 0.0)
    high = center + error
    ax.fill_between(edges, np.r_[low, low[-1]], np.r_[high, high[-1]], step="post", **kwargs)


def render_channel(
    source: dict[str, object],
    channel: str,
    output: Path,
    *,
    luminosity: float,
    width: int,
    mass_gev: int,
    provenance: str,
) -> dict[str, object]:
    channels = source["channels"]
    if not isinstance(channels, dict):
        raise ValueError("invalid channel payload")
    objects = channels[channel]
    model_edges, model, model_error, jetmass_bins = project_y(objects["TotalBkg"], f"{channel} TotalBkg")
    data_edges, data, data_error, data_jetmass_bins = project_y(objects["data_obs"], f"{channel} data_obs")
    if data_jetmass_bins != jetmass_bins or not np.array_equal(data_edges, model_edges):
        raise ValueError(f"model/data binning mismatch in {channel}")

    scale = 0.001 if max(model_edges) > 100.0 else 1.0
    edges = model_edges * scale
    centers = 0.5 * (edges[:-1] + edges[1:])
    half_widths = 0.5 * np.diff(edges)
    fig, (ax, ratio_ax) = plt.subplots(
        2,
        1,
        sharex=True,
        figsize=(11.5, 10.5),
        gridspec_kw={"height_ratios": (3.0, 1.0), "hspace": 0.05},
        layout="constrained",
    )
    ax.stairs(model, edges, color="#5790fc", linewidth=2.4, label="Post-fit background")
    step_band(ax, edges, model, model_error, color="#5790fc", alpha=0.30, label="Post-fit unc.")
    ax.errorbar(
        centers,
        data,
        xerr=half_widths,
        yerr=data_error,
        color="black",
        marker="o",
        linestyle="none",
        markersize=4.5,
        linewidth=1.3,
        label="Masked-data control bins",
        zorder=5,
    )
    positive = np.concatenate((model[model > 0], data[data > 0]))
    if positive.size == 0:
        raise ValueError(f"no positive values in {channel}")
    ax.set_yscale("log")
    ax.set_ylim(max(float(np.min(positive)) / 5.0, 1e-4), float(np.max(positive)) * 25.0)
    ax.set_ylabel("Events / bin")
    ax.legend(loc="upper right", fontsize=17, framealpha=0.92)
    hep.cms.label(
        "Preliminary",
        data=True,
        loc=2,
        ax=ax,
        rlabel=rf"{luminosity:.2f} fb$^{{-1}}$ (13.6 TeV)",
    )
    match = CHANNEL.fullmatch(channel)
    if not match:
        raise ValueError(f"unexpected channel label: {channel}")
    annotation = (
        f"{match.group('label')} {match.group('year')} {match.group('tag')}, Region {match.group('region')}\n"
        f"Z' width {width}%, m = {mass_gev / 1000:g} TeV; masked B-only"
    )
    cms_x = next((text.get_position()[0] for text in ax.texts if text.get_text() == "CMS"), 0.03)
    ax.text(cms_x, 0.74, annotation, transform=ax.transAxes, ha="left", va="top", fontsize=17)

    valid = model > 0
    ratio = np.full_like(data, np.nan)
    ratio_error = np.full_like(data, np.nan)
    relative_model = np.zeros_like(model)
    ratio[valid] = data[valid] / model[valid]
    ratio_error[valid] = data_error[valid] / model[valid]
    relative_model[valid] = model_error[valid] / model[valid]
    ratio_ax.fill_between(
        edges,
        np.r_[np.maximum(1.0 - relative_model, 0.0), max(1.0 - relative_model[-1], 0.0)],
        np.r_[1.0 + relative_model, 1.0 + relative_model[-1]],
        step="post",
        color="#5790fc",
        alpha=0.30,
    )
    finite = np.isfinite(ratio) & np.isfinite(ratio_error)
    ratio_ax.errorbar(
        centers[finite],
        ratio[finite],
        xerr=half_widths[finite],
        yerr=ratio_error[finite],
        color="black",
        marker="o",
        linestyle="none",
        markersize=4.0,
        linewidth=1.2,
    )
    ratio_ax.axhline(1.0, color="0.25", linewidth=1.2)
    ratio_upper = 2.0 if not np.any(finite) else max(2.0, 1.15 * float(np.max(ratio[finite] + ratio_error[finite])))
    ratio_ax.set_ylim(0.0, ratio_upper)
    ratio_ax.set_ylabel("Data / postfit")
    ratio_ax.set_xlabel(r"$m_{t\bar{t}}$ [TeV]" if scale != 1.0 else r"$m_{t\bar{t}}$")
    ratio_ax.grid(alpha=0.25)
    ax.grid(alpha=0.22)
    fig.get_layout_engine().set(rect=(0.0, 0.035, 1.0, 0.96))
    fig.text(0.99, 0.004, provenance, ha="right", va="bottom", fontsize=7, color="0.45", family="monospace")
    for suffix in ("png", "pdf"):
        fig.savefig(output.with_suffix(f".{suffix}"), dpi=170)
    plt.close(fig)
    return {
        "channel": channel,
        "png": str(output.with_suffix(".png")),
        "pdf": str(output.with_suffix(".pdf")),
        "mtt_bins": len(model),
        "jetmass_bins_projected": jetmass_bins,
        "postfit_integral": float(np.sum(model)),
        "data_integral": float(np.sum(data)),
        "verdict": "rendered_pending_visual_inspection",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--width", type=int, required=True, choices=(1, 10, 30))
    parser.add_argument("--mass", type=int, required=True)
    parser.add_argument("--luminosity", type=float, default=220.54)
    parser.add_argument("--provenance", required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError(f"refusing to overwrite output directory: {args.output_dir}")
    source = json.loads(args.source.read_text())
    if source.get("dataset_scope") != "masked_observed_sidebands_only":
        raise ValueError("source is not masked observed sideband data")
    if source.get("source_tool") != "PostFit2DShapesFromWorkspace":
        raise ValueError("source tool mismatch")
    if set(source.get("allowed_channels", [])) != EXPECTED_CHANNELS:
        raise ValueError("source allowed-channel set mismatch")
    if len(source.get("denied_channels", [])) != 4:
        raise ValueError("source denied-channel count mismatch")
    channels = source.get("channels")
    if not isinstance(channels, dict) or set(channels) != EXPECTED_CHANNELS:
        raise ValueError("source channel set mismatch")
    if any(set(objects) != {"TotalBkg", "data_obs"} for objects in channels.values()):
        raise ValueError("source object set mismatch")
    args.output_dir.mkdir(parents=True)
    records = [
        render_channel(
            source,
            channel,
            args.output_dir / f"masked_postfit_2d_{channel}",
            luminosity=args.luminosity,
            width=args.width,
            mass_gev=args.mass,
            provenance=args.provenance,
        )
        for channel in sorted(EXPECTED_CHANNELS)
    ]
    manifest = {
        "schema_version": 1,
        "source": str(args.source),
        "source_sha256": sha256_file(args.source),
        "dataset_scope": "masked_observed_sidebands_only",
        "projection": "sum_over_jetmass_bins_onto_mtt",
        "width_percent": args.width,
        "mass_GeV": args.mass,
        "luminosity_fb": args.luminosity,
        "plot_count": len(records),
        "visual_inspection": "pending",
        "plots": records,
    }
    manifest_path = args.output_dir / "masked_postfit_2d_plot_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"MASKED_POSTFIT_2D_PLOTS_OK": True, "plots": len(records), "manifest": str(manifest_path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"MASKED_POSTFIT_2D_PLOTS_FAILED: {error}")
        raise SystemExit(2)
