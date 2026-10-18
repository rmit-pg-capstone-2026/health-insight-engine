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
from call_priority_assessment import call_priority_assessment  # noqa: E402
from generate_briefing import build_pdf  # noqa: E402
from validate_priority_assessment import (  # noqa: E402
    PriorityAssessmentValidationError,
    load_json,
    validate_priority_assessment_results,
)

import storage  # noqa: E402
from llm_transport import (  # noqa: E402
    backend_from_env,
    converse,
    post_chat_completion,
)

# One file per page version. A subfolder, so the stage 2 script's batch mode
# (which only reads the top level of source-extracted-files/) never picks
# these up alongside the files the stage 1 script writes.
DOCUMENTS_DIR = storage.DATA_DIR / "source-extracted-files" / "versions"

EXTRACT_MODEL = os.environ.get("EXTRACT_MODEL")
EXTRACT_PROVIDER = os.environ.get("EXTRACT_PROVIDER", "deepinfra") or None

PRIORITY_ROOT = REPO_ROOT / "priority_assessment"
PRIORITY_PROMPT = PRIORITY_ROOT / "prompts" / "priority_assessment_v0.4.3_article.md"
PRIORITY_SCHEMA = (
    PRIORITY_ROOT / "schemas" / "priority_assessment_article_schema_v0.1.json"
)


def _converse_content(body: dict) -> str:
    try:
        blocks = body["output"]["message"]["content"]
        content = next(block["text"] for block in blocks if "text" in block)
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(
            "Unexpected Bedrock Converse response shape; missing output text"
        ) from exc
    except StopIteration as exc:
        raise RuntimeError("Bedrock Converse response contains no text block") from exc
    if not isinstance(content, str):
        raise RuntimeError("LLM response content is not a string")
    return content


def _chat_content(body: dict) -> str:
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(
            "Unexpected OpenAI-compatible response shape; "
            "missing choices[0].message.content"
        ) from exc
    if not isinstance(content, str):
        raise RuntimeError("LLM response content is not a string")
    return content


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

    If some sub-pages of a multi-page report never loaded (even after the
    retries in fetch_and_extract), the capture is incomplete. When we already
    have a version, that raises IncompleteCapture rather than saving a
    truncated copy that would look like a real change; the next run tries
    again. A page we have never seen is saved anyway - partial beats nothing
    - and "missing_pages" says how many were lost.
    """
    html, final_url = stage1.fetch_html(source["url"])
    result = stage1.fetch_and_extract(source["url"], html=html, final_url=final_url)
    content_hash = hashlib.sha256(result.body.encode("utf-8")).hexdigest()
    known = source.get("known_hashes", [])
    if content_hash in known:
        return {"changed": False, "content_hash": content_hash}
    if result.missing_pages and known:
        raise IncompleteCapture(
            f"{len(result.missing_pages)} of {len(result.pages) + len(result.missing_pages)} "
            "page(s) did not load - kept the existing version, will retry next run")

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
        "missing_pages": len(result.missing_pages),
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
    backend = backend_from_env()
    if not EXTRACT_MODEL:
        raise RuntimeError("Set EXTRACT_MODEL in the repo-root .env")
    reasoning = os.environ.get("EXTRACT_REASONING", "off")
    api_url = os.environ.get("EXTRACT_API_URL")
    api_key = (
        os.environ.get("EXTRACT_API_KEY")
        or os.environ.get("OPENROUTER_API_KEY")
    )
    if backend == "api_key" and not api_url:
        raise RuntimeError("LLM_BACKEND=api_key requires EXTRACT_API_URL")
    if backend == "api_key" and not api_key:
        raise RuntimeError(
            "LLM_BACKEND=api_key requires EXTRACT_API_KEY or OPENROUTER_API_KEY"
        )

    prompt = stage2.PROMPT_PATH.read_text(encoding="utf-8")
    path = storage.local(document["markdown_path"])
    if not path.exists():
        raise FileNotFoundError(f"document file is missing: {document['markdown_path']}")
    text = stage2.load_article(path)

    user_message = (
        "Read the document below and produce the briefing "
        "insights.\n\n<article>\n" + text + "\n</article>"
    )
    response_format = stage2.RESPONSE_FORMAT["json_schema"]

    started = time.time()
    llm = {
        "model": EXTRACT_MODEL,
        "provider": "amazon-bedrock" if backend == "bedrock" else EXTRACT_PROVIDER,
        "prompt_tokens": None,
        "completion_tokens": None,
        "cost_usd": None,
        "seconds": None,
        "error": None,
    }
    try:
        if backend == "bedrock":
            body, elapsed = converse(
                EXTRACT_MODEL,
                prompt,
                user_message,
                response_schema=response_format["schema"],
                response_schema_name=response_format["name"],
                reasoning=reasoning,
                temperature=0.0,
                timeout_seconds=stage2.TIMEOUT,
                max_attempts=2,
            )
            content = _converse_content(body)
        else:
            payload = {
                "model": EXTRACT_MODEL,
                "temperature": 0.0,
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_message},
                ],
                "response_format": stage2.RESPONSE_FORMAT,
            }
            if "openrouter.ai" in api_url.lower():
                payload["provider"] = {"require_parameters": True}
                payload["usage"] = {"include": True}
                payload["reasoning"] = {"enabled": False}
                if EXTRACT_PROVIDER:
                    payload["provider"]["only"] = [EXTRACT_PROVIDER]
                    payload["provider"]["allow_fallbacks"] = False
            body, elapsed = post_chat_completion(
                api_url,
                payload,
                api_key=api_key,
                timeout_seconds=stage2.TIMEOUT,
                max_attempts=2,
            )
            content = _chat_content(body)
        result = stage2.parse_json(content)
        if result is None:
            raise RuntimeError("stage 2 response was not valid JSON")
    except Exception as exc:
        llm.update(seconds=round(time.time() - started, 1), error=str(exc))
        raise StageError(str(exc), llm=llm) from exc

    usage = body.get("usage") or {}
    details = usage.get("completion_tokens_details") or {}
    llm.update(
        provider=(
            "amazon-bedrock"
            if backend == "bedrock"
            else body.get("provider") or EXTRACT_PROVIDER
        ),
        prompt_tokens=(
            usage.get("inputTokens")
            if backend == "bedrock"
            else usage.get("prompt_tokens")
        ),
        completion_tokens=(
            usage.get("outputTokens")
            if backend == "bedrock"
            else usage.get("completion_tokens")
        ),
        cost_usd=usage.get("cost") if backend == "api_key" else None,
        seconds=elapsed,
    )
    meta = {
        "model_returned": body.get("model"),
        "provider": llm["provider"],
        "prompt_tokens": llm["prompt_tokens"],
        "completion_tokens": llm["completion_tokens"],
        "reasoning_tokens": (
            None if backend == "bedrock" else details.get("reasoning_tokens")
        ),
        "cost_usd": llm["cost_usd"],
        "seconds": llm["seconds"],
        "reasoning_setting": reasoning if backend == "bedrock" else "off",
        "provider_pinned": EXTRACT_PROVIDER if backend == "api_key" else None,
        "backend": backend,
        "error": None,
    }

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
          "llm": {"model", "provider", "prompt_tokens", "completion_tokens",
                    "cost_usd", "seconds", "error"}

    The response is checked against the schema and must cover every input
    insight, in order - anything else raises.
    """
    backend = backend_from_env()
    model = os.environ.get("PRIORITY_ASSESSMENT_MODEL")
    reasoning = os.environ.get("PRIORITY_ASSESSMENT_REASONING", "off")
    temperature = float(
        os.environ.get("PRIORITY_ASSESSMENT_TEMPERATURE", "0.0")
    )
    if not model:
        raise RuntimeError("Set PRIORITY_ASSESSMENT_MODEL in the repo-root .env")
    api_url = os.environ.get("PRIORITY_ASSESSMENT_API_URL")
    api_key = (
        os.environ.get("PRIORITY_ASSESSMENT_API_KEY")
        or os.environ.get("OPENROUTER_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
    )
    if backend == "api_key" and not api_url:
        raise RuntimeError(
            "LLM_BACKEND=api_key requires PRIORITY_ASSESSMENT_API_URL"
        )
    if backend == "api_key" and not api_key:
        raise RuntimeError(
            "LLM_BACKEND=api_key requires PRIORITY_ASSESSMENT_API_KEY, "
            "OPENROUTER_API_KEY, or OPENAI_API_KEY"
        )

    prompt_text = PRIORITY_PROMPT.read_text(encoding="utf-8")
    article_schema = load_json(PRIORITY_SCHEMA)
    expected_ids = [x["insight_id"] for x in article["insights"]]

    started = time.time()
    llm = {
        "model": model,
        "provider": "amazon-bedrock" if backend == "bedrock" else "api-key",
        "prompt_tokens": None,
        "completion_tokens": None,
        "cost_usd": None,
        "seconds": None,
        "error": None,
    }

    # One semantic retry only. Transport-level transient retries happen inside
    # llm_transport, so retries do not multiply across layers.
    last_results = None
    for attempt in range(1, 3):
        try:
            response = call_priority_assessment(
                model,
                prompt_text,
                article,
                backend=backend,
                api_url=api_url,
                api_key=api_key,
                timeout_seconds=180,
                response_schema=article_schema,
                reasoning=reasoning,
                temperature=temperature,
            )
            results = response["result"]
            usage = response["usage"]

            llm.update(
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
                cost_usd=usage.get("cost_usd"),
                seconds=response.get("seconds"),
            )
            last_results = results
            validate_priority_assessment_results(
                results,
                expected_ids,
                article_schema,
            )
            return {"assessments": results["assessments"], "llm": llm}
        except PriorityAssessmentValidationError as exc:
            if attempt < 2:
                continue
            llm.update(seconds=round(time.time() - started, 1), error=str(exc))
            raise StageError(str(exc), llm=llm, output=last_results) from exc
        except Exception as exc:
            llm.update(seconds=round(time.time() - started, 1), error=str(exc))
            raise StageError(str(exc), llm=llm, output=last_results) from exc

    raise StageError("Priority Assessment failed", llm=llm, output=last_results)


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


class IncompleteCapture(RuntimeError):
    """Some sub-pages of a report never loaded; nothing was saved."""


class StageError(RuntimeError):
    """A stage failure that still carries what the model said, so the
    caller can log the call before recording the failure."""

    def __init__(self, message, llm=None, output=None):
        super().__init__(message)
        self.llm = llm or {}
        self.output = output
