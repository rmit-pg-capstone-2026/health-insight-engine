from pathlib import Path
import sqlite3
import html
import shutil

import boto3

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from botocore.config import Config

PROFILE = "rmit-medibank"
REGION = "ap-southeast-2"
BUCKET = "medibank-insights-pipeline-rmit2026"

MODEL_ID = "au.anthropic.claude-opus-4-6-v1"

ROOT = Path("baseline_eval")
SOURCE_DIR = ROOT / "sources"

FROZEN_DB = Path("pipeline-2026-10-27.db")
FROZEN_SYSTEM_PDF = Path("last-aws-briefing.pdf")

BASELINE_MD = ROOT / "baseline-output.md"
BASELINE_PDF = ROOT / "baseline-briefing.pdf"
SYSTEM_PDF = ROOT / "last-aws-briefing.pdf"


SYSTEM_PROMPT = """
You are preparing a healthcare intelligence briefing for Medibank,
an Australian private health insurer.

Using only the supplied healthcare source documents, produce a concise
healthcare intelligence briefing.

Identify the most important healthcare developments.

For each important development:
- explain the finding;
- include important supporting statistics where available;
- explain why it may matter to Medibank;
- assign a priority of High Priority, Medium Priority, Watchlist,
  or Informational;
- clearly identify which source document supports the finding.

Produce:
1. Executive Summary
2. Key Prioritised Insights
3. Emerging Watchlist

Keep the briefing concise and suitable for healthcare executives.

Do not use outside knowledge.
Do not invent facts unsupported by the supplied source documents.
"""


def markdown_to_pdf(text, output):
    styles = getSampleStyleSheet()

    doc = SimpleDocTemplate(
        str(output),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )

    story = []

    for raw in text.splitlines():
        line = raw.strip()

        if not line:
            story.append(Spacer(1, 3 * mm))
            continue

        if line.startswith("### "):
            style = styles["Heading3"]
            content = line[4:]
        elif line.startswith("## "):
            style = styles["Heading2"]
            content = line[3:]
        elif line.startswith("# "):
            style = styles["Heading1"]
            content = line[2:]
        elif line.startswith("- "):
            style = styles["BodyText"]
            content = "• " + line[2:]
        else:
            style = styles["BodyText"]
            content = line

        story.append(
            Paragraph(html.escape(content), style)
        )
        story.append(Spacer(1, 2 * mm))

    doc.build(story)


def main():
    ROOT.mkdir(exist_ok=True)
    SOURCE_DIR.mkdir(exist_ok=True)

    if not FROZEN_DB.exists():
        raise RuntimeError(
            f"Frozen DB not found: {FROZEN_DB}"
        )

    if not FROZEN_SYSTEM_PDF.exists():
        raise RuntimeError(
            f"System PDF not found: {FROZEN_SYSTEM_PDF}"
        )

    session = boto3.Session(
        profile_name=PROFILE,
        region_name=REGION,
    )

    s3 = session.client("s3")

    bedrock_config = Config(
        read_timeout=3600,
        connect_timeout=30,
        retries={
            "total_max_attempts": 1,
            "mode": "standard",
        },
    )

    bedrock = session.client(
        "bedrock-runtime",
        config=bedrock_config,
    )

    # -------------------------------------------------
    # 1. Open frozen DB from the AWS run
    # -------------------------------------------------
    print("Using frozen DB:", FROZEN_DB)

    conn = sqlite3.connect(FROZEN_DB)
    conn.row_factory = sqlite3.Row

    # -------------------------------------------------
    # 2. Reconstruct source documents eligible for
    #    the briefing
    # -------------------------------------------------
    docs = conn.execute(
        """
        SELECT DISTINCT
            d.id,
            d.markdown_path,
            d.title,
            d.publisher,
            s.agency
        FROM documents d
        JOIN sources s
          ON s.id = d.source_id
        JOIN insights i
          ON i.document_id = d.id
        WHERE i.held_back = 0
          AND i.priority IS NOT NULL
        ORDER BY d.id
        """
    ).fetchall()

    eligible_insights = conn.execute(
        """
        SELECT COUNT(*)
        FROM insights
        WHERE held_back = 0
          AND priority IS NOT NULL
        """
    ).fetchone()[0]

    held_back = conn.execute(
        """
        SELECT COUNT(*)
        FROM insights
        WHERE held_back = 1
        """
    ).fetchone()[0]

    print()
    print("Frozen run")
    print("---------------------------")
    print("Eligible documents :", len(docs))
    print("Eligible insights  :", eligible_insights)
    print("Held-back insights :", held_back)

    # -------------------------------------------------
    # 3. Download exact source markdown files
    # -------------------------------------------------
    parts = []

    for number, row in enumerate(docs, 1):
        key = row["markdown_path"]
        local = SOURCE_DIR / Path(key).name

        print(
            f"{number}. [{row['agency']}] "
            f"{row['title'] or local.name}"
        )

        s3.download_file(
            BUCKET,
            key,
            str(local)
        )

        text = local.read_text(
            encoding="utf-8",
            errors="replace",
        )

        parts.append(
            f"""
==================================================
DOCUMENT {number}
AGENCY: {row['agency']}
TITLE: {row['title'] or ''}
SOURCE FILE: {key}
==================================================

{text}
"""
        )

    combined = "\n".join(parts)

    print()
    print(
        "Combined input size:",
        f"{len(combined):,}",
        "characters"
    )

    # -------------------------------------------------
    # 4. ONE generic LLM call
    # -------------------------------------------------
    user_prompt = (
        "Produce the healthcare intelligence briefing "
        "using the following source documents.\n\n"
        "<source_documents>\n"
        + combined
        + "\n</source_documents>"
    )

    print()
    print("Making ONE Claude Opus 4.6 call...")

    response = bedrock.converse(
        modelId=MODEL_ID,
        system=[
            {
                "text": SYSTEM_PROMPT
            }
        ],
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "text": user_prompt
                    }
                ],
            }
        ],
        inferenceConfig={
            "temperature": 0.0,
            "maxTokens": 8000,
        },
    )

    output_text = "\n".join(
        block["text"]
        for block in response["output"]["message"]["content"]
        if "text" in block
    )

    # -------------------------------------------------
    # 5. Save baseline result
    # -------------------------------------------------
    BASELINE_MD.write_text(
        output_text,
        encoding="utf-8",
    )

    markdown_to_pdf(
        output_text,
        BASELINE_PDF,
    )

    # -------------------------------------------------
    # 6. Freeze/copy production comparison PDF
    # -------------------------------------------------
    shutil.copy2(
        FROZEN_SYSTEM_PDF,
        SYSTEM_PDF,
    )

    usage = response.get("usage", {})

    print()
    print("================================")
    print("BASELINE COMPLETE")
    print("================================")
    print("Model:", MODEL_ID)
    print("Documents:", len(docs))
    print("Eligible system insights:", eligible_insights)
    print("Held-back system insights:", held_back)
    print("Input tokens:", usage.get("inputTokens"))
    print("Output tokens:", usage.get("outputTokens"))

    print()
    print("Compare:")
    print("Baseline :", BASELINE_PDF)
    print("System   :", SYSTEM_PDF)
    print("Raw text :", BASELINE_MD)

    conn.close()


if __name__ == "__main__":
    main()