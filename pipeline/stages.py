"""
The four pipeline stages as plain functions: a dict goes in, a dict comes out.

None of these touch the database. run.py reads each stage's input from the
database, calls the stage, and saves what it returns. That keeps every stage
callable on its own - from run.py today, or from its own Lambda later.

    collect(source)          -> a markdown file per new page version
    extract(document)        -> summary + insights
    assess(article)          -> a priority for each insight
    brief(briefings, path)   -> the PDF

A stage that fails raises an exception; the caller decides what to do.
"""

import hashlib
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for folder in ("collect_and_extract", "insight-extraction-test",
               "priority_assessment/src", "briefing"):
    sys.path.insert(0, str(REPO_ROOT / folder))

import collect_and_extract as stage1  # noqa: E402
import extract as stage2  # noqa: E402  (also loads the repo-root .env)
from call_priority_assessment import call_openai_compatible_chat  # noqa: E402
from generate_briefing import build_pdf  # noqa: E402
from run_priority_assessment import DEFAULT_PROMPT, DEFAULT_SCHEMA  # noqa: E402
from validate_priority_assessment import load_json, validate_priority_assessment_results  # noqa: E402

import storage  # noqa: E402

# One file per page version. A subfolder, so the stage 2 script's batch mode
# (which only reads the top level of source-extracted-files/) never picks
# these up alongside the files the stage 1 script writes.
DOCUMENTS_DIR = storage.DATA_DIR / "source-extracted-files" / "versions"

EXTRACT_MODEL = os.environ.get("EXTRACT_MODEL", "deepseek/deepseek-v4-flash-0731")
EXTRACT_PROVIDER = os.environ.get("EXTRACT_PROVIDER", "deepinfra") or None


# ----------------------------------------------------------------- stage 1

def collect(source: dict) -> dict:
    """Fetch one watched page and save it as markdown if it changed.

    In:  {"agency": "ABS", "url": "https://...", "known_hashes": ["490084b2...", ...]}
    Out: {"changed": False, "content_hash": "490084b2..."}                when nothing changed
         {"changed": True, "content_hash": "a91c3e2b...", "title": "...",
          "fetched_at": "2026-10-02T03:10:00+00:00",
          "markdown_path": "source-extracted-files/versions/abs-...-ec4e2569-a91c3e2b.md"}

    markdown_path is relative to the data folder (see storage.py), so it is
    also the file's key in S3.

    Each version gets its own file (URL hash + content hash in the name), so
    a file is never overwritten and always matches the version that points
    to it. The database stores only the path.
    """
    html, final_url = stage1.fetch_html(source["url"])
    result = stage1.fetch_and_extract(source["url"], html=html, final_url=final_url)
    content_hash = hashlib.sha256(result.body.encode("utf-8")).hexdigest()
    if content_hash in source.get("known_hashes", []):
        return {"changed": False, "content_hash": content_hash}

    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path = stage1.save_markdown(source["agency"], result.canonical_url, result,
                                content_hash, fetched_at,
                                dest_dir=DOCUMENTS_DIR, versioned=True)
    return {
        "changed": True,
        "content_hash": content_hash,
        "title": result.title,
        "fetched_at": fetched_at,
        "markdown_path": storage.relative(path),
    }


# ----------------------------------------------------------------- stage 2

def extract(document: dict) -> dict:
    """Run the insight extraction prompt on one document.

    In:  {"markdown_path": "source-extracted-files/versions/abs-....md",
          "retrieval_date": "2026-10-02"}
    Out: {"document": {"publisher", "title", "publication_date", "period_covered",
                       "summary", "document_scope"},
          "insights": [{"position": 1, "insight_type", "finding", "evidence",
                        "evidence_location", "target_population", "caveat",
                        "reasoning", "evidence_found": True}, ...],
          "llm": {"model", "provider", "prompt_tokens", "completion_tokens",
                  "cost_usd", "seconds", "error"},
          "record": {...the same run record extract.py writes to disk...}}

    evidence_found is the verbatim-quote check: False means the quote is not
    in the document, and the insight should not be trusted.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("Set OPENROUTER_API_KEY in the repo-root .env")

    prompt = stage2.PROMPT_PATH.read_text(encoding="utf-8")
    path = storage.local(document["markdown_path"])
    if not path.exists():
        raise FileNotFoundError(f"document file is missing: {document['markdown_path']}")
    text = stage2.load_article(path)
    result, meta = stage2.call_model(EXTRACT_MODEL, text, prompt, api_key,
                                     temperature=0.0, reasoning="off",
                                     provider=EXTRACT_PROVIDER, indent="    ")
    llm = {"model": EXTRACT_MODEL,
           "provider": meta.get("provider") or EXTRACT_PROVIDER,
           "prompt_tokens": meta.get("prompt_tokens"),
           "completion_tokens": meta.get("completion_tokens"),
           "cost_usd": meta.get("cost_usd"),
           "seconds": meta.get("seconds"),
           "error": meta.get("error")}
    if result is None:
        raise StageError(f"stage 2 call failed: {meta.get('error')}", llm=llm,
                         output=meta.get("raw") or meta.get("raw_content"))

    # The same checks, in the same order, as extract.py.
    record = {"meta": meta, "result": result,
              "schema_errors": stage2.validate_schema(result)}
    stage2.annotate(result, document["retrieval_date"])
    record["quote_checks"] = stage2.verify_quotes(result, text)
    record["lazy_reasoning"] = stage2.check_reasoning(result)
    record["reversed_conditionals"] = stage2.check_direction(result)
    record["scope_problems"] = stage2.check_scope(result)
    if record["schema_errors"]:
        raise StageError(f"stage 2 output has schema errors: {record['schema_errors']}",
                         llm=llm, output=record)

    found = {c["index"]: c["found_in_source"] for c in record["quote_checks"]}
    source = result.get("source") or {}
    fields = ("insight_type", "finding", "evidence", "evidence_location",
              "target_population", "caveat", "reasoning")
    return {
        "document": {
            "publisher": source.get("publisher"),
            "title": source.get("title"),
            "publication_date": source.get("publication_date"),
            "period_covered": source.get("period_covered"),
            "summary": result.get("summary"),
            "document_scope": result.get("document_scope"),
        },
        "insights": [
            {"position": n + 1, **{f: ins.get(f) for f in fields},
             "evidence_found": bool(found.get(n, False))}
            for n, ins in enumerate(result.get("insights") or [])
        ],
        "llm": llm,
        "record": record,
    }


# ----------------------------------------------------------------- stage 3

def assess(article: dict) -> dict:
    """Run the priority assessment prompt on one document's insights.

    In:  the article-mode handoff stage 3 has always used -
         {"source": {"publisher", "title", "url", "publication_date", "retrieval_date"},
          "summary": "...",
          "insights": [{"insight_id": "INSIGHT_001", "insight_type", "finding",
                        "evidence", "evidence_location", "target_population",
                        "caveat"}, ...]}
    Out: {"assessments": [{"insight_id": "INSIGHT_001", "relevance": "Relevant",
                           "criteria": {...10 factors...}, "priority": "High Priority",
                           "priority_rationale": "..."}, ...],
          "llm": {"model", "seconds", "error"}}

    The response is checked against the schema and must cover every input
    insight, in order - anything else raises.
    """
    api_url = os.environ.get("PROMPT2_API_URL")
    api_key = os.environ.get("PROMPT2_API_KEY") or os.environ.get("OPENAI_API_KEY")
    model = os.environ.get("PROMPT2_MODEL")
    if not (api_url and api_key and model):
        raise RuntimeError("Set PROMPT2_API_URL, PROMPT2_API_KEY and PROMPT2_MODEL "
                           "in the repo-root .env")

    started = time.time()
    llm = {"model": model, "seconds": None, "error": None}
    try:
        results = call_openai_compatible_chat(
            api_url, api_key, model, DEFAULT_PROMPT.read_text(encoding="utf-8"),
            article, timeout_seconds=180)
    except Exception as exc:
        llm.update(seconds=round(time.time() - started, 1), error=str(exc))
        raise StageError(str(exc), llm=llm) from exc
    llm["seconds"] = round(time.time() - started, 1)

    expected_ids = [x["insight_id"] for x in article["insights"]]
    try:
        validate_priority_assessment_results(results, expected_ids, load_json(DEFAULT_SCHEMA))
    except Exception as exc:
        llm["error"] = str(exc)
        raise StageError(str(exc), llm=llm, output=results) from exc
    return {"assessments": results["assessments"], "llm": llm}


# ----------------------------------------------------------------- stage 4

def brief(briefings: list, pdf_path: Path) -> dict:
    """Render the PDF.

    In:  one dict per document, in the shape stage 3's script writes to
         data/priority-tagged-insight-files/ -
         [{"source": {...}, "summary": "...",
           "insights": [{"insight_id", "insight_type", "finding", "evidence",
                         "evidence_location", "caveat", "priority",
                         "priority_rationale", ...}, ...],
           "section_index": {"clinical": [...], "pharmaceutical": [...],
                             "medical_technology": [...], "watchlist": [...]}}, ...]
    Out: {"pdf_path": "...", "source_count": 3, "insight_count": 18}
    """
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    source_count, insight_count = build_pdf(briefings, pdf_path)
    return {"pdf_path": str(pdf_path), "source_count": source_count,
            "insight_count": insight_count}


class StageError(RuntimeError):
    """A stage failure that still carries what the model said, so the
    caller can log the call before recording the failure."""

    def __init__(self, message, llm=None, output=None):
        super().__init__(message)
        self.llm = llm or {}
        self.output = output
