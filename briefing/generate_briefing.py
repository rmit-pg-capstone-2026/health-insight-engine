#!/usr/bin/env python3
"""
Healthcare Intelligence Briefing - PDF generator (prototype)

Reads one or more consolidated insights JSON files (one per source report,
e.g. one AIHW report and one ABS release) and writes a single PDF with a title
block listing every source and one combined Insights section.

Usage:
    python generate_briefing.py                           # the pipeline default
    python generate_briefing.py briefing_input.json
    python generate_briefing.py aihw_dementia.json abs_respiratory.json
    python generate_briefing.py briefing_inputs/          # every .json in a folder
    python generate_briefing.py briefing_inputs/ -o my_briefing.pdf

With no inputs it reads every .json in <repo root>/data/priority-tagged-insight-files.
The PDF is saved as <repo root>/data/briefing-paper/briefing_report.pdf unless
-o is given.

Requires:
    pip install reportlab
"""

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Shared pipeline folders: stage 3 writes the first, the PDF goes in the second.
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = REPO_ROOT / "data" / "priority-tagged-insight-files"
DEFAULT_OUTPUT_PDF = REPO_ROOT / "data" / "briefing-paper" / "briefing_report.pdf"

BRAND = colors.HexColor("#0B3D91")      # dark blue for headings
TEXT = colors.HexColor("#1F2933")
MUTED = colors.HexColor("#5F6B7A")
CARD_BG = colors.HexColor("#F7F9FC")
CARD_BORDER = colors.HexColor("#D9E1EC")

# Priority label -> (tag text, tag colour, sort rank)
PRIORITY_STYLE = {
    "High Priority":   ("HIGH PRIORITY",   colors.HexColor("#C0392B"), 0),
    "Medium Priority": ("MEDIUM PRIORITY", colors.HexColor("#E67E22"), 1),
    "Watchlist":       ("WATCHLIST",       colors.HexColor("#2E86C1"), 2),
    "Informational":   ("INFORMATIONAL",   colors.HexColor("#7F8C8D"), 3),
}
UNKNOWN_PRIORITY = ("UNRATED", colors.HexColor("#95A5A6"), 9)

# section_index key -> label shown on the card
SECTION_LABELS = {
    "clinical": "Clinical",
    "pharmaceutical": "Pharmaceutical",
    "medical_technology": "Medical Technology",
    "watchlist": "Watchlist",
}

# ---------------------------------------------------------------------------
# Text styles
# ---------------------------------------------------------------------------

S = {
    "brand": ParagraphStyle("brand", fontName="Helvetica-Bold", fontSize=11,
                            textColor=BRAND, spaceAfter=2),
    "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=22,
                            leading=26, textColor=TEXT, spaceAfter=10),
    "meta": ParagraphStyle("meta", fontName="Helvetica", fontSize=9,
                           leading=12, textColor=TEXT),
    "meta_label": ParagraphStyle("meta_label", fontName="Helvetica-Bold",
                                 fontSize=9, leading=12, textColor=MUTED),
    "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=16,
                         leading=20, textColor=BRAND, spaceBefore=6,
                         spaceAfter=8),
    "tag": ParagraphStyle("tag", fontName="Helvetica-Bold", fontSize=7.5,
                          leading=9, textColor=colors.white, alignment=TA_LEFT),
    "headline": ParagraphStyle("headline", fontName="Helvetica-Bold",
                               fontSize=10.5, leading=14, textColor=TEXT),
    "section": ParagraphStyle("section", fontName="Helvetica-Oblique",
                              fontSize=8.5, leading=11, textColor=MUTED),
    "label": ParagraphStyle("label", fontName="Helvetica-Bold", fontSize=8.5,
                            leading=12, textColor=BRAND),
    "body": ParagraphStyle("body", fontName="Helvetica", fontSize=8.5,
                           leading=12, textColor=TEXT),
    "empty": ParagraphStyle("empty", fontName="Helvetica-Oblique", fontSize=9,
                            leading=12, textColor=MUTED),
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def txt(value, default="Not stated"):
    """Escape text for ReportLab paragraphs; handle None/empty values."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    return escape(str(value).strip())


def nice_date(value):
    """Turn '2026-07-30' into '30 Jul 2026'; leave other formats unchanged."""
    if not value:
        return "Not stated"
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d %b %Y").lstrip("0")
    except ValueError:
        return txt(value)


def short_publisher(source):
    """'Australian Institute of Health and Welfare (AIHW)' -> 'AIHW'."""
    publisher = (source.get("publisher") or "").strip()
    match = re.search(r"\(([^)]+)\)\s*$", publisher)
    if match:
        return match.group(1)
    return publisher or "Unknown source"


def collect_json_files(inputs):
    """Expand the command-line inputs (files and/or folders) into JSON paths."""
    files = []
    for item in inputs:
        path = Path(item)
        if path.is_dir():
            files.extend(sorted(path.glob("*.json")))
        elif path.is_file():
            files.append(path)
        else:
            print(f"Warning: not found, skipped: {path}")
    # remove duplicates while keeping order
    seen, unique = set(), []
    for f in files:
        key = f.resolve()
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


def load_briefing_json(path):
    """Load one briefing JSON; return None (with a warning) if it isn't one."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        print(f"Warning: {path.name} is not valid JSON, skipped ({e})")
        return None
    if not isinstance(data, dict) or "insights" not in data:
        print(f"Warning: {path.name} has no 'insights' list, skipped")
        return None
    return data


def build_section_lookup(section_index):
    """Map insight_id -> section label using section_index."""
    lookup = {}
    for key, ids in (section_index or {}).items():
        label = SECTION_LABELS.get(key, key.replace("_", " ").title())
        for insight_id in ids or []:
            lookup[insight_id] = label
    return lookup


def section_label_for(insight, lookup):
    """Use section_index; fall back to insight_type if the ID isn't listed."""
    if insight.get("insight_id") in lookup:
        return lookup[insight["insight_id"]]
    itype = insight.get("insight_type") or "Uncategorised"
    return SECTION_LABELS.get(itype, itype.replace("_", " ").title())


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------

def title_block(sources, insight_count):
    story = [
        Paragraph("MEDIBANK", S["brand"]),
        Paragraph("Healthcare Intelligence Briefing", S["title"]),
    ]

    header = [Paragraph(h, S["meta_label"]) for h in
              ("Source", "Publisher", "Published", "Retrieved")]
    rows = [header]
    for src in sources:
        title = txt(src.get("title"))
        url = src.get("url")
        if url:
            title = (f'<link href="{escape(url)}" color="#0B3D91">'
                     f'<u>{title}</u></link>')
        rows.append([
            Paragraph(title, S["meta"]),
            Paragraph(txt(short_publisher(src)), S["meta"]),
            Paragraph(nice_date(src.get("publication_date")), S["meta"]),
            Paragraph(nice_date(src.get("retrieval_date")), S["meta"]),
        ])

    table = Table(rows, colWidths=[None, 25 * mm, 24 * mm, 24 * mm])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, CARD_BORDER),
    ]))
    story.append(table)

    generated = date.today().strftime("%d %b %Y").lstrip("0")
    summary = (f'<font color="#5F6B7A"><b>Generated</b></font>&nbsp;&nbsp;{generated}'
               f'&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<font color="#5F6B7A"><b>Coverage</b></font>&nbsp;&nbsp;'
               f'{len(sources)} source(s)  ·  {insight_count} insight(s)')
    line = Table([[Paragraph(summary, S["meta"])]])
    line.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, -1), (-1, -1), 0.8, BRAND),
    ]))
    story += [line, Spacer(1, 10 * mm)]
    return story


def priority_tag(priority):
    tag_text, tag_colour, _ = PRIORITY_STYLE.get(priority, UNKNOWN_PRIORITY)
    tag = Table([[Paragraph(tag_text, S["tag"])]])
    tag.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), tag_colour),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return tag, tag_colour


def insight_card(insight, section_label, source, width):
    tag, tag_colour = priority_tag(insight.get("priority"))

    # Header row: priority tag + section label, then headline
    label = f"{txt(short_publisher(source))}  ·  {txt(section_label)}"
    header = Table([[tag, Paragraph(label, S["section"])]],
                   colWidths=[32 * mm, None])
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), 6),
    ]))

    # Evidence with location and source link
    evidence = f'"{txt(insight.get("evidence"))}"'
    location = insight.get("evidence_location")
    url = source.get("url")
    src_name = txt(source.get("title"), default="Source")
    ref_parts = []
    if location:
        ref_parts.append(f"Section: {txt(location)}")
    if url:
        ref_parts.append(f'Source: <link href="{escape(url)}" color="#0B3D91">'
                         f'<u>{src_name}</u></link>')
    if ref_parts:
        evidence += f'<br/><font color="#5F6B7A">{"  ·  ".join(ref_parts)}</font>'

    rows = [
        [header, ""],
        [Paragraph(txt(insight.get("finding")), S["headline"]), ""],
        [Paragraph("Evidence", S["label"]), Paragraph(evidence, S["body"])],
    ]
    if insight.get("caveat"):
        rows.append([Paragraph("Caveat", S["label"]),
                     Paragraph(txt(insight["caveat"]), S["body"])])
    rows.append([Paragraph("Why this priority", S["label"]),
                 Paragraph(txt(insight.get("priority_rationale")), S["body"])])

    card = Table(rows, colWidths=[30 * mm, width - 30 * mm])
    card.setStyle(TableStyle([
        ("SPAN", (0, 0), (-1, 0)),
        ("SPAN", (0, 1), (-1, 1)),
        ("NOSPLIT", (0, 0), (-1, 2)),   # keep tag, headline and evidence together
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), CARD_BG),
        ("BOX", (0, 0), (-1, -1), 0.6, CARD_BORDER),
        ("LINEBEFORE", (0, 0), (0, -1), 3, tag_colour),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 6),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
    ]))
    return card


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(doc.leftMargin, 12 * mm,
                      "Healthcare Intelligence Briefing  ·  Prototype  ·  "
                      "RMIT × Medibank")
    canvas.drawRightString(A4[0] - doc.rightMargin, 12 * mm,
                           f"Page {doc.page}")
    canvas.restoreState()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def generate(json_paths, pdf_path: Path) -> tuple[int, int]:
    """Build the PDF from briefing JSON files on disk."""
    briefings = [data for data in (load_briefing_json(p) for p in json_paths)
                 if data is not None]
    return build_pdf(briefings, pdf_path)


def build_pdf(briefings, pdf_path: Path) -> tuple[int, int]:
    """Build the PDF from briefing dicts already in memory (one per source
    document, same shape as the JSON files). The database pipeline calls this
    directly. Returns (source count, insight count)."""
    sources = []
    cards = []   # (priority rank, file order, insight order, insight, label, source)

    for file_no, data in enumerate(briefings):
        source = data.get("source") or {}
        sources.append(source)
        # section_index is looked up per file, so repeated IDs such as
        # INSIGHT_001 in two different files never get mixed up
        lookup = build_section_lookup(data.get("section_index"))
        for item_no, insight in enumerate(data.get("insights") or []):
            rank = PRIORITY_STYLE.get(insight.get("priority"), UNKNOWN_PRIORITY)[2]
            cards.append((rank, file_no, item_no, insight,
                          section_label_for(insight, lookup), source))

    if not sources:
        sys.exit("Error: no usable briefing JSON files were found.")

    # Highest priority first across ALL sources; ties keep file/JSON order
    cards.sort(key=lambda c: (c[0], c[1], c[2]))

    doc = SimpleDocTemplate(
        str(pdf_path), pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=20 * mm,
        title="Healthcare Intelligence Briefing",
        author="RMIT × Medibank Project Team",
    )

    story = title_block(sources, len(cards))
    story.append(Paragraph("Insights", S["h1"]))

    if not cards:
        story.append(Paragraph("No insights identified for this period.",
                               S["empty"]))
    for _, _, _, insight, label, source in cards:
        story.append(insight_card(insight, label, source, doc.width))
        story.append(Spacer(1, 5 * mm))

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return len(sources), len(cards)


def main():
    parser = argparse.ArgumentParser(
        description="Generate a Healthcare Intelligence Briefing PDF from "
                    "one or more briefing JSON files.")
    parser.add_argument("inputs", nargs="*",
                        help="JSON file(s) and/or folder(s) containing JSON files "
                             "(default: data/priority-tagged-insight-files)")
    parser.add_argument("-o", "--output",
                        help="Output PDF path "
                             "(default: data/briefing-paper/briefing_report.pdf)")
    args = parser.parse_args()

    inputs = args.inputs or [str(DEFAULT_INPUT_DIR)]
    json_paths = collect_json_files(inputs)
    if not json_paths:
        sys.exit("Error: no JSON files found in: %s" % ", ".join(inputs))

    pdf_path = Path(args.output) if args.output else DEFAULT_OUTPUT_PDF
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    source_count, insight_count = generate(json_paths, pdf_path)
    print(f"Created {pdf_path} from {source_count} source(s) "
          f"with {insight_count} insight(s).")


if __name__ == "__main__":
    main()
