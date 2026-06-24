#!/usr/bin/env python3
"""Create table and postfit-projection presentation PDFs for the 2024 F-test scan."""

import argparse
import csv
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
RESULTS_DIR = ROOT / "ftest_results"
FTEST_DIR = ROOT / "ftest" / "2024"
TABLE_PDF = RESULTS_DIR / "FTest_summary_tables_2024.pdf"
PROJY_PDF = RESULTS_DIR / "FTest_postfit_projy_all_transfer_functions_2024.pdf"
SIGNAL = "ZPrime4000"

TRANSFER_FUNCTIONS = ["0x0", "0x1", "0x2", "1x0", "1x1", "1x2", "2x1", "2x2"]
REGIONS = (("cen", "Central category"), ("fwd", "Forward category"))

PAGE_SIZE = (1600, 900)
BACKGROUND = "#f5f7fa"
NAVY = "#17365d"
BLUE = "#2f75b5"
CYAN = "#4aa3c7"
DARK = "#20252b"
MUTED = "#626b75"
WHITE = "#ffffff"
PALE_BLUE = "#e9f2f9"
PALE_RED = "#fbe9e7"
RED = "#a93226"
GRID = "#cfd6dd"


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
TABLE_FONT = font(18)
TABLE_BOLD_FONT = font(18, bold=True)
SMALL_FONT = font(15)


def blank_page(color=BACKGROUND):
    return Image.new("RGB", PAGE_SIZE, color)


def add_header(draw, title, section=None):
    draw.rectangle((0, 0, PAGE_SIZE[0], 82), fill=NAVY)
    draw.text((58, 21), title, font=SECTION_FONT, fill=WHITE)
    if section:
        bbox = draw.textbbox((0, 0), section, font=BODY_FONT)
        draw.text(
            (1542 - (bbox[2] - bbox[0]), 29),
            section,
            font=BODY_FONT,
            fill="#dbeaf7",
        )


def add_footer(draw, page_number):
    draw.line((58, 850, 1542, 850), fill=GRID, width=2)
    draw.text((58, 862), "CMS Work in Progress", font=SMALL_FONT, fill=MUTED)
    text = str(page_number)
    bbox = draw.textbbox((0, 0), text, font=SMALL_FONT)
    draw.text((1542 - (bbox[2] - bbox[0]), 862), text, font=SMALL_FONT, fill=MUTED)


def load_rows(region):
    path = RESULTS_DIR / f"ftest_results_{region}2024.csv"
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["p1"] = int(row["p1"])
        row["p2"] = int(row["p2"])
        row["n_bins"] = int(row["n_bins"])
        row["f_value"] = float(row["f_value"])
        row["p_value"] = float(row["p_value"])
    return rows


def p_value_text(value):
    if value == 0:
        return "< numerical precision"
    if value < 0.001:
        return f"{value:.2e}"
    return f"{value:.4f}"


def cover_page(title, subtitle, note):
    page = blank_page()
    draw = ImageDraw.Draw(page)
    draw.rectangle((0, 0, 34, PAGE_SIZE[1]), fill=BLUE)
    draw.text((110, 180), title, font=TITLE_FONT, fill=NAVY)
    draw.text((112, 258), subtitle, font=SECTION_FONT, fill=DARK)
    draw.rectangle((112, 340, 880, 345), fill=CYAN)
    draw.text(
        (112, 395),
        "Central and forward categories",
        font=SUBTITLE_FONT,
        fill=MUTED,
    )
    draw.text(
        (112, 445),
        "Candidates: " + ", ".join(TRANSFER_FUNCTIONS),
        font=BODY_FONT,
        fill=DARK,
    )
    draw.rounded_rectangle((112, 570, 1450, 690), radius=16, fill=WHITE, outline=GRID, width=2)
    draw.text((145, 602), note, font=BODY_FONT, fill=DARK)
    draw.text((112, 780), "CMS Work in Progress", font=SUBTITLE_FONT, fill=NAVY)
    return page


def table_page(region_name, rows, page_number, part, total_parts):
    page = blank_page()
    draw = ImageDraw.Draw(page)
    add_header(draw, "F-test numerical summary", f"{region_name} | {part}/{total_parts}")

    columns = [
        ("Simple", 170),
        ("Complex", 180),
        ("p1", 100),
        ("p2", 100),
        ("Bins", 120),
        ("F statistic", 220),
        ("p-value", 260),
        ("Pairwise result", 330),
    ]
    x_start = 70
    y_start = 135
    row_height = 50

    x_positions = [x_start]
    for _, width in columns:
        x_positions.append(x_positions[-1] + width)

    draw.rounded_rectangle(
        (x_start, y_start, x_positions[-1], y_start + row_height),
        radius=8,
        fill=NAVY,
    )
    for index, (label, _) in enumerate(columns):
        x0, x1 = x_positions[index], x_positions[index + 1]
        bbox = draw.textbbox((0, 0), label, font=TABLE_BOLD_FONT)
        draw.text(
            (x0 + (x1 - x0 - (bbox[2] - bbox[0])) / 2, y_start + 14),
            label,
            font=TABLE_BOLD_FONT,
            fill=WHITE,
        )

    for row_index, row in enumerate(rows):
        y0 = y_start + row_height * (row_index + 1)
        significant = row["p_value"] < 0.05
        fill = PALE_RED if significant else (WHITE if row_index % 2 == 0 else PALE_BLUE)
        draw.rectangle((x_start, y0, x_positions[-1], y0 + row_height), fill=fill)

        values = [
            row["tf1"],
            row["tf2"],
            str(row["p1"]),
            str(row["p2"]),
            str(row["n_bins"]),
            f"{row['f_value']:.4g}",
            p_value_text(row["p_value"]),
            "p < 0.05" if significant else "not significant",
        ]
        for index, value in enumerate(values):
            x0, x1 = x_positions[index], x_positions[index + 1]
            text_font = TABLE_BOLD_FONT if significant and index in (6, 7) else TABLE_FONT
            text_color = RED if significant and index in (6, 7) else DARK
            bbox = draw.textbbox((0, 0), value, font=text_font)
            draw.text(
                (x0 + (x1 - x0 - (bbox[2] - bbox[0])) / 2, y0 + 14),
                value,
                font=text_font,
                fill=text_color,
            )

    table_bottom = y_start + row_height * (len(rows) + 1)
    for x in x_positions:
        draw.line((x, y_start, x, table_bottom), fill=GRID, width=1)
    for row_index in range(len(rows) + 2):
        y = y_start + row_index * row_height
        draw.line((x_start, y, x_positions[-1], y), fill=GRID, width=1)

    draw.text(
        (70, 805),
        "Red rows have p < 0.05. This is a pairwise statistical comparison, not by itself a final model-selection rule.",
        font=SMALL_FONT,
        fill=MUTED,
    )
    add_footer(draw, page_number)
    return page


def build_table_pdf():
    pages = [
        cover_page(
            "F-test Summary Tables",
            "2024 transfer-function polynomial scan",
            "Numerical values are reproduced directly from the central and forward F-test CSV summaries.",
        )
    ]
    page_number = 2
    rows_per_page = 12
    for region, region_name in REGIONS:
        rows = load_rows(region)
        chunks = [rows[index:index + rows_per_page] for index in range(0, len(rows), rows_per_page)]
        for part, chunk in enumerate(chunks, start=1):
            pages.append(table_page(region_name, chunk, page_number, part, len(chunks)))
            page_number += 1

    pages[0].save(
        TABLE_PDF,
        "PDF",
        resolution=150.0,
        save_all=True,
        append_images=pages[1:],
        title="F-test Summary Tables: 2024 Transfer-function Polynomial Scan",
        author="CMS Work in Progress",
    )


def source_projy_path(region, transfer_function):
    return (
        FTEST_DIR
        / region
        / f"ttbarfits_{region}2024_ftest{transfer_function}"
        / f"ttbar-signal{SIGNAL}_area"
        / "plots_fit_b"
        / "postfit_projy.pdf"
    )


def render_pdf_page(pdf_path, output_prefix):
    subprocess.run(
        [
            "pdftoppm",
            "-f",
            "1",
            "-l",
            "1",
            "-singlefile",
            "-png",
            "-r",
            "130",
            str(pdf_path),
            str(output_prefix),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return Path(f"{output_prefix}.png")


def projy_section_page(region_name, page_number):
    page = blank_page(NAVY)
    draw = ImageDraw.Draw(page)
    draw.rectangle((0, 0, 28, PAGE_SIZE[1]), fill=CYAN)
    draw.text((115, 280), region_name, font=TITLE_FONT, fill=WHITE)
    draw.text(
        (118, 365),
        "Background-only postfit y projections",
        font=SECTION_FONT,
        fill="#dbeaf7",
    )
    draw.text(
        (118, 440),
        f"{len(TRANSFER_FUNCTIONS)} transfer-function candidates",
        font=SUBTITLE_FONT,
        fill=WHITE,
    )
    draw.text((1480, 835), str(page_number), font=SMALL_FONT, fill="#dbeaf7")
    return page


def projy_plot_page(region_name, transfer_function, source_image, page_number):
    page = blank_page()
    draw = ImageDraw.Draw(page)
    add_header(
        draw,
        f"Postfit y projection | TF {transfer_function}",
        region_name,
    )

    image = Image.open(source_image).convert("RGB")
    image.thumbnail((1480, 710), Image.Resampling.LANCZOS)
    x = (PAGE_SIZE[0] - image.width) // 2
    y = 105 + (710 - image.height) // 2
    draw.rounded_rectangle((45, 100, 1555, 825), radius=14, fill=WHITE, outline=GRID, width=2)
    page.paste(image, (x, y))
    add_footer(draw, page_number)
    return page


def build_projy_pdf():
    pages = [
        cover_page(
            "Postfit Projection Comparison",
            "All tested transfer-function candidates",
            "Plots are taken from the background-only fit output. Embedded source annotations are preserved unchanged.",
        )
    ]
    page_number = 2

    with tempfile.TemporaryDirectory(prefix="ftest_projy_") as temp_dir:
        temp_dir = Path(temp_dir)
        for region, region_name in REGIONS:
            pages.append(projy_section_page(region_name, page_number))
            page_number += 1
            for transfer_function in TRANSFER_FUNCTIONS:
                source_pdf = source_projy_path(region, transfer_function)
                if not source_pdf.exists():
                    raise FileNotFoundError(source_pdf)
                rendered = render_pdf_page(
                    source_pdf,
                    temp_dir / f"{region}_{transfer_function}",
                )
                pages.append(
                    projy_plot_page(
                        region_name,
                        transfer_function,
                        rendered,
                        page_number,
                    )
                )
                page_number += 1

    pages[0].save(
        PROJY_PDF,
        "PDF",
        resolution=150.0,
        save_all=True,
        append_images=pages[1:],
        title="Postfit y Projections for All 2024 F-test Transfer Functions",
        author="CMS Work in Progress",
    )


def parse_args():
    parser = argparse.ArgumentParser(description="Create F-test summary and postfit-projection PDFs.")
    parser.add_argument("--results-dir", default=str(RESULTS_DIR), help="Directory containing F-test CSVs and PNGs.")
    parser.add_argument("--ftest-dir", default=str(FTEST_DIR), help="Directory containing region/TF fit work areas.")
    parser.add_argument("--signal", default=SIGNAL, help="Raw signal name used in work-area subtags, e.g. ZPrime2000.")
    parser.add_argument("--table-pdf", default=None, help="Output path for summary-table PDF.")
    parser.add_argument("--projy-pdf", default=None, help="Output path for postfit-projection PDF.")
    return parser.parse_args()


def main():
    global RESULTS_DIR, FTEST_DIR, TABLE_PDF, PROJY_PDF, SIGNAL
    args = parse_args()
    RESULTS_DIR = Path(args.results_dir)
    FTEST_DIR = Path(args.ftest_dir)
    SIGNAL = args.signal
    TABLE_PDF = Path(args.table_pdf) if args.table_pdf else RESULTS_DIR / "FTest_summary_tables_2024.pdf"
    PROJY_PDF = Path(args.projy_pdf) if args.projy_pdf else RESULTS_DIR / "FTest_postfit_projy_all_transfer_functions_2024.pdf"

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    build_table_pdf()
    build_projy_pdf()
    print(f"Wrote {TABLE_PDF}")
    print(f"Wrote {PROJY_PDF}")


if __name__ == "__main__":
    main()
