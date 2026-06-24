#!/usr/bin/env python3
"""Build a presentation-style PDF from the pairwise F-test plots."""

import argparse
import csv
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
RESULTS_DIR = ROOT / "ftest_results"
OUTPUT_PDF = RESULTS_DIR / "FTest_pairwise_results_2024.pdf"

PAGE_SIZE = (1600, 900)
BACKGROUND = "#f7f8fa"
NAVY = "#17365d"
BLUE = "#2f75b5"
DARK = "#20252b"
MUTED = "#626b75"
LIGHT_BLUE = "#dbeaf7"
WHITE = "#ffffff"


def font(size, bold=False):
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Helvetica.ttc",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


TITLE_FONT = font(48, bold=True)
SECTION_FONT = font(34, bold=True)
SUBTITLE_FONT = font(24)
BODY_FONT = font(20)
SMALL_FONT = font(16)
CAPTION_FONT = font(19, bold=True)


def blank_page():
    return Image.new("RGB", PAGE_SIZE, BACKGROUND)


def add_header(draw, title, section=None):
    draw.rectangle((0, 0, PAGE_SIZE[0], 82), fill=NAVY)
    draw.text((58, 21), title, font=SECTION_FONT, fill=WHITE)
    if section:
        bbox = draw.textbbox((0, 0), section, font=BODY_FONT)
        draw.text(
            (PAGE_SIZE[0] - 58 - (bbox[2] - bbox[0]), 29),
            section,
            font=BODY_FONT,
            fill=LIGHT_BLUE,
        )


def add_footer(draw, page_number):
    draw.line((58, 850, 1542, 850), fill="#ccd2d8", width=2)
    draw.text((58, 862), "CMS Work in Progress", font=SMALL_FONT, fill=MUTED)
    page_text = str(page_number)
    bbox = draw.textbbox((0, 0), page_text, font=SMALL_FONT)
    draw.text((1542 - bbox[2], 862), page_text, font=SMALL_FONT, fill=MUTED)


def load_rows(region):
    csv_path = RESULTS_DIR / f"ftest_results_{region}2024.csv"
    with csv_path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["f_value"] = float(row["f_value"])
        row["p_value"] = float(row["p_value"])
    return rows


def plot_path(row):
    return RESULTS_DIR / (
        f"FTest_{row['tf1']}_{row['tf2']}_{row['year']}_{row['region']}.png"
    )


def cover_page():
    page = blank_page()
    draw = ImageDraw.Draw(page)
    draw.rectangle((0, 0, 34, PAGE_SIZE[1]), fill=BLUE)
    draw.text((110, 180), "Pairwise F-test Results", font=TITLE_FONT, fill=NAVY)
    draw.text(
        (112, 255),
        "2024 transfer-function polynomial scan",
        font=SECTION_FONT,
        fill=DARK,
    )
    draw.rectangle((112, 340, 820, 345), fill=BLUE)
    draw.text(
        (112, 390),
        "Central and forward categories",
        font=SUBTITLE_FONT,
        fill=MUTED,
    )
    draw.text(
        (112, 438),
        "Candidates: 0x0, 0x1, 0x2, 1x0, 1x1, 1x2, 2x1, 2x2",
        font=BODY_FONT,
        fill=DARK,
    )
    draw.text((112, 735), "CMS Work in Progress", font=SUBTITLE_FONT, fill=NAVY)
    draw.text((112, 782), "13.6 TeV", font=BODY_FONT, fill=MUTED)
    return page


def guide_page(page_number):
    page = blank_page()
    draw = ImageDraw.Draw(page)
    add_header(draw, "How to read these comparisons", "2024 F-test scan")
    items = [
        (
            "Comparison",
            "Each panel compares a simpler polynomial order with a more complex one.",
        ),
        (
            "Observed F",
            "The blue arrow marks the F statistic calculated from the two goodness-of-fit results.",
        ),
        (
            "p-value",
            "A small p-value indicates that the additional parameters improve the fit beyond the simpler model.",
        ),
        (
            "Important",
            "These are polynomial-order comparisons within the same transfer-function construction, not tests of unrelated functional families.",
        ),
    ]
    y = 155
    for label, text in items:
        draw.rounded_rectangle((90, y, 1510, y + 125), radius=18, fill=WHITE, outline="#d6dce2", width=2)
        draw.text((125, y + 25), label, font=CAPTION_FONT, fill=BLUE)
        draw.text((330, y + 25), text, font=BODY_FONT, fill=DARK)
        y += 150
    draw.text(
        (90, 775),
        "Physics interpretation and the final polynomial choice should also consider fit stability and diagnostics.",
        font=SMALL_FONT,
        fill=MUTED,
    )
    add_footer(draw, page_number)
    return page


def section_page(region_name, rows, page_number):
    page = blank_page()
    draw = ImageDraw.Draw(page)
    draw.rectangle((0, 0, PAGE_SIZE[0], PAGE_SIZE[1]), fill=NAVY)
    draw.rectangle((0, 0, 28, PAGE_SIZE[1]), fill=BLUE)
    draw.text((115, 275), region_name, font=TITLE_FONT, fill=WHITE)
    draw.text(
        (118, 355),
        f"{len(rows)} pairwise comparisons",
        font=SECTION_FONT,
        fill=LIGHT_BLUE,
    )
    significant = sum(row["p_value"] < 0.05 for row in rows)
    draw.text(
        (118, 425),
        f"{significant} comparisons have p < 0.05",
        font=SUBTITLE_FONT,
        fill=WHITE,
    )
    draw.text(
        (118, 735),
        "Counts summarize pairwise tests only; they do not define the final model choice.",
        font=SMALL_FONT,
        fill=LIGHT_BLUE,
    )
    draw.text((1480, 835), str(page_number), font=SMALL_FONT, fill=LIGHT_BLUE)
    return page


def paste_plot(page, row, box):
    draw = ImageDraw.Draw(page)
    x0, y0, x1, y1 = box
    source = Image.open(plot_path(row)).convert("RGB")
    plot_height = y1 - y0 - 66
    plot_width = x1 - x0
    source.thumbnail((plot_width, plot_height), Image.Resampling.LANCZOS)
    px = x0 + (plot_width - source.width) // 2
    py = y0 + 52 + (plot_height - source.height) // 2
    draw.rounded_rectangle((x0, y0, x1, y1), radius=14, fill=WHITE, outline="#d3d9df", width=2)
    page.paste(source, (px, py))

    p_value = row["p_value"]
    p_label = f"{p_value:.3g}" if p_value > 0 else "< numerical precision"
    caption = (
        f"{row['tf1']} vs {row['tf2']}   |   "
        f"F = {row['f_value']:.3g}   |   p = {p_label}"
    )
    draw.text((x0 + 22, y0 + 16), caption, font=CAPTION_FONT, fill=DARK)


def comparison_page(region_name, rows, page_number):
    page = blank_page()
    draw = ImageDraw.Draw(page)
    add_header(draw, "Pairwise F-test comparisons", region_name)
    paste_plot(page, rows[0], (55, 110, 790, 825))
    if len(rows) > 1:
        paste_plot(page, rows[1], (810, 110, 1545, 825))
    add_footer(draw, page_number)
    return page


def parse_args():
    parser = argparse.ArgumentParser(description="Build a presentation PDF from pairwise F-test PNGs.")
    parser.add_argument("--results-dir", default=str(RESULTS_DIR), help="Directory containing F-test CSVs and PNGs.")
    parser.add_argument("--output", default=None, help="Output PDF path. Defaults inside --results-dir.")
    return parser.parse_args()


def main():
    global RESULTS_DIR, OUTPUT_PDF
    args = parse_args()
    RESULTS_DIR = Path(args.results_dir)
    OUTPUT_PDF = Path(args.output) if args.output else RESULTS_DIR / "FTest_pairwise_results_2024.pdf"

    pages = [cover_page(), guide_page(2)]
    page_number = 3

    for region, region_name in (("cen", "Central category"), ("fwd", "Forward category")):
        rows = load_rows(region)
        pages.append(section_page(region_name, rows, page_number))
        page_number += 1
        for index in range(0, len(rows), 2):
            pages.append(comparison_page(region_name, rows[index:index + 2], page_number))
            page_number += 1

    pages[0].save(
        OUTPUT_PDF,
        "PDF",
        resolution=150.0,
        save_all=True,
        append_images=pages[1:],
        title="Pairwise F-test Results: 2024 Transfer-function Polynomial Scan",
        author="CMS Work in Progress",
    )
    print(f"Wrote {OUTPUT_PDF} ({len(pages)} pages)")


if __name__ == "__main__":
    main()
