#!/usr/bin/env python3
"""
Healthcare Intelligence Briefing - PDF generator (prototype)

Reads one or more consolidated insights JSON files (one per source report,
e.g. one AIHW report and one ABS release) and writes a single PDF with a title
block, then follows the agreed briefing format
(Healthcare_Intelligence_Briefing_sample_output.docx):

    Executive Summary            one paragraph (LLM)
    What Changed This Period     one line per key development (LLM)
    Clinical Insights            insight cards grouped by insight_type,
    Pharmaceutical Insights      highest priority first, each with its
    Prosthesis & Medical         priority tag (Watchlist items stay in their
      Technology Insights        topic section with a WATCHLIST tag)
    Emerging Watchlist           topics to keep watching (LLM)

The Executive Summary is written by an LLM through the pipeline's shared
transport (same Bedrock / API-key settings as the other stages) and checked
before use; if no LLM is available it falls back to a rule-based summary.
See executive_summary.py.

Usage:
    python generate_briefing.py                           # the pipeline default
    python generate_briefing.py briefing_input.json
    python generate_briefing.py aihw_dementia.json abs_respiratory.json
    python generate_briefing.py briefing_inputs/          # every .json in a folder
    python generate_briefing.py briefing_inputs/ -o my_briefing.pdf
    python generate_briefing.py --summary rules     # no LLM call
    python generate_briefing.py --summary none      # no executive summary

With no inputs it reads every .json in <repo root>/data/priority-tagged-insight-files.
The PDF is saved as <repo root>/data/briefing-paper/briefing_report.pdf unless
-o is given.

Requires:
    pip install reportlab   (plus boto3/requests for the LLM summary)
"""

import argparse
import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path
from xml.sax.saxutils import escape

from executive_summary import make_executive_summary

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
# insight_type -> (card label, section heading), in the order sections appear.
# An insight_type not listed here gets its own section after these.
TOPIC_SECTIONS = {
    "clinical": ("Clinical", "Clinical Insights"),
    "pharmaceutical": ("Pharmaceutical", "Pharmaceutical Insights"),
    "medical_technology": ("Medical Technology",
                           "Prosthesis & Medical Technology Insights"),
}

# Short priority words for the "What Changed" list, as in the sample briefing.
PRIORITY_WORD = {"High Priority": "HIGH", "Medium Priority": "MEDIUM",
                 "Watchlist": "WATCH", "Informational": "INFO"}
WATCH_COLOUR = colors.HexColor("#2E86C1")

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
                         spaceAfter=8,
                         keepWithNext=1),
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
    "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=11,
                         leading=14, textColor=BRAND, spaceBefore=8,
                         spaceAfter=4,
                         keepWithNext=1),
    "summary": ParagraphStyle("summary", fontName="Helvetica", fontSize=9.5,
                              leading=14, textColor=TEXT),
    "bullet": ParagraphStyle("bullet", fontName="Helvetica", fontSize=9,
                             leading=13, textColor=TEXT, leftIndent=10,
                             bulletIndent=0, spaceAfter=3),
    "note": ParagraphStyle("note", fontName="Helvetica-Oblique", fontSize=7.5,
                           leading=10, textColor=MUTED, spaceAfter=4),
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


def topic_key(insight):
    """'Medical technology' / 'medical_technology' -> 'medical_technology'."""
    raw = str(insight.get("insight_type") or "uncategorised").strip().lower()
    return re.sub(r"[\s-]+", "_", raw)


def topic_labels(key):
    """Return (card label, section heading) for an insight_type key."""
    if key in TOPIC_SECTIONS:
        return TOPIC_SECTIONS[key]
    label = key.replace("_", " ").title()
    return label, f"{label} Insights"


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


def insight_card(insight, section_label, source, width, number=None):
    tag, tag_colour = priority_tag(insight.get("priority"))

    # Header row: priority tag + section label, then headline. The number is
    # what the Executive Summary cites ("Insight 3"), and the anchor lets its
    # links jump straight to this card.
    label = f"{txt(short_publisher(source))}  ·  {txt(section_label)}"
    if number is not None:
        label = (f'<a name="insight{number}"/><b>Insight {number}</b>'
                 f'  ·  {label}')
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


def _insight_links(refs):
    """['I1', 'I4'] -> 'Insight 1, 4' with each number linking to its card."""
    links = []
    for ref in refs:
        n = ref[1:]
        links.append(f'<link href="#insight{n}" color="#0B3D91"><u>{n}</u></link>')
    word = "Insight" if len(links) == 1 else "Insights"
    return f'<font color="#5F6B7A">{word} {", ".join(links)}</font>'


def _summary_note(summary):
    if summary.get("method") == "llm":
        return (f"Drafted by an AI model ({txt(summary.get('model'))}) from the "
                "insights in this briefing, and checked so that every figure "
                "matches the insight it cites. Numbers link to the full insight.")
    if summary.get("note"):
        return ("Generated automatically from the insights' priority ratings "
                "(AI summary unavailable for this run).")
    return "Generated automatically from the insights' priority ratings."


def _best_priority(refs, priority_by_ref):
    ranked = sorted((PRIORITY_STYLE.get(priority_by_ref.get(r), UNKNOWN_PRIORITY)[2],
                     priority_by_ref.get(r)) for r in refs)
    return ranked[0][1] if ranked else None


def executive_summary_block(summary, priority_by_ref, width):
    """Executive Summary paragraph + What Changed list, as in the sample."""
    story = [Paragraph("Executive Summary", S["h1"]),
             Paragraph(_summary_note(summary), S["note"]),
             Paragraph(txt(summary.get("executive_summary")), S["summary"]),
             Spacer(1, 4 * mm)]

    changed = summary.get("what_changed") or []
    if changed:
        story.append(Paragraph("What Changed This Period", S["h1"]))
        for c in changed:
            priority = _best_priority(c["refs"], priority_by_ref)
            word = PRIORITY_WORD.get(priority, "")
            colour = PRIORITY_STYLE.get(priority, UNKNOWN_PRIORITY)[1].hexval()[2:]
            text = (f'<font color="#{colour}"><b>{word}</b></font>&nbsp;&nbsp;'
                    f'{txt(c.get("text"))}&nbsp;&nbsp;{_insight_links(c["refs"])}')
            story.append(Paragraph(text, S["bullet"], bulletText="•"))
    story.append(Spacer(1, 6 * mm))
    return story


def watchlist_block(summary, items, width):
    """Emerging Watchlist: from the summary, or the Watchlist-priority insights."""
    story = [Paragraph("Emerging Watchlist", S["h1"]),
             Paragraph("Topics to keep watching, drawn from the insights in this "
                       "briefing.", S["note"])]
    if summary is not None:
        entries = summary.get("watchlist") or []
    else:
        entries = [{"topic": it["source"].get("title") or "Watchlist item",
                    "note": it["insight"].get("finding") or "",
                    "refs": [f'I{it["number"]}']}
                   for it in items if it["insight"].get("priority") == "Watchlist"]
    if not entries:
        story.append(Paragraph("No items flagged for monitoring in this briefing.",
                               S["empty"]))
        return story

    rows = []
    for e in entries:
        tag = Table([[Paragraph("WATCH", S["tag"])]])
        tag.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), WATCH_COLOUR),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        text = (f'<b>{txt(e.get("topic"))}</b> — {txt(e.get("note"))}'
                f'&nbsp;&nbsp;{_insight_links(e["refs"])}')
        rows.append([tag, Paragraph(text, S["body"])])
    table = Table(rows, colWidths=[16 * mm, width - 16 * mm])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (0, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(table)
    return story


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

def generate(json_paths, pdf_path: Path, summary_mode=None) -> tuple[int, int]:
    """Build the PDF from briefing JSON files on disk."""
    briefings = [data for data in (load_briefing_json(p) for p in json_paths)
                 if data is not None]
    return build_pdf(briefings, pdf_path, summary_mode=summary_mode)


def build_pdf(briefings, pdf_path: Path, summary_mode=None) -> tuple[int, int]:
    """Build the PDF from briefing dicts already in memory (one per source
    document, same shape as the JSON files). The database pipeline calls this
    directly. Returns (source count, insight count).

    summary_mode: "llm" (falls back to "rules" if the LLM fails), "rules" (no
    LLM call) or "none" (no executive summary). When not given, the
    EXEC_SUMMARY_MODE environment variable is used (handy on Lambda), and
    "llm" if that is not set either."""
    summary_mode = (summary_mode or os.environ.get("EXEC_SUMMARY_MODE") or "llm").strip().lower()
    if summary_mode not in ("llm", "rules", "none"):
        raise ValueError(f"summary_mode must be llm, rules or none (got {summary_mode!r})")
    sources = []
    cards = []   # (topic, priority rank, file order, insight order, insight, source)

    for file_no, data in enumerate(briefings):
        source = data.get("source") or {}
        sources.append(source)
        for item_no, insight in enumerate(data.get("insights") or []):
            rank = PRIORITY_STYLE.get(insight.get("priority"), UNKNOWN_PRIORITY)[2]
            cards.append((topic_key(insight), rank, file_no, item_no, insight, source))

    if not sources:
        sys.exit("Error: no usable briefing JSON files were found.")

    # Section order: the standard topics first, then any other insight_type.
    topics = list(TOPIC_SECTIONS) + sorted({c[0] for c in cards} - set(TOPIC_SECTIONS))
    topic_order = {t: n for n, t in enumerate(topics)}
    # Within a topic: highest priority first; ties keep file/JSON order.
    cards.sort(key=lambda c: (topic_order[c[0]], c[1], c[2], c[3]))

    doc = SimpleDocTemplate(
        str(pdf_path), pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=20 * mm,
        title="Healthcare Intelligence Briefing",
        author="RMIT × Medibank Project Team",
    )

    story = title_block(sources, len(cards))

    # Cards are numbered in display order; the summary cites these numbers.
    items = [{"number": n, "topic": topic, "insight": insight,
              "section": topic_labels(topic)[0], "source": source}
             for n, (topic, _, _, _, insight, source) in enumerate(cards, start=1)]
    summary = make_executive_summary(items, sources, mode=summary_mode)
    if summary:
        priority_by_ref = {f'I{it["number"]}': it["insight"].get("priority")
                           for it in items}
        story += executive_summary_block(summary, priority_by_ref, doc.width)

    # One section per topic, as in the sample briefing.
    for topic in topics:
        story.append(Paragraph(topic_labels(topic)[1], S["h1"]))
        in_topic = [it for it in items if it["topic"] == topic]
        if not in_topic:
            story.append(Paragraph("No insights identified for this period.",
                                   S["empty"]))
            story.append(Spacer(1, 4 * mm))
        for it in in_topic:
            story.append(insight_card(it["insight"], it["section"], it["source"],
                                      doc.width, number=it["number"]))
            story.append(Spacer(1, 5 * mm))

    # Emerging Watchlist: from the summary, or straight from the
    # Watchlist-priority insights when the summary is switched off.
    story += watchlist_block(summary, items, doc.width)

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
    parser.add_argument("--summary", choices=("llm", "rules", "none"), default=None,
                        help="How to write the Executive Summary: llm (default, or "
                             "EXEC_SUMMARY_MODE from .env; "
                             "falls back to rules if the LLM fails), rules (no "
                             "LLM call) or none")
    args = parser.parse_args()

    inputs = args.inputs or [str(DEFAULT_INPUT_DIR)]
    json_paths = collect_json_files(inputs)
    if not json_paths:
        sys.exit("Error: no JSON files found in: %s" % ", ".join(inputs))

    pdf_path = Path(args.output) if args.output else DEFAULT_OUTPUT_PDF
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    source_count, insight_count = generate(json_paths, pdf_path,
                                           summary_mode=args.summary)
    print(f"Created {pdf_path} from {source_count} source(s) "
          f"with {insight_count} insight(s).")


if __name__ == "__main__":
    main()
