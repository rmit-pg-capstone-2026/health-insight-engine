"""
Executive summary for the Healthcare Intelligence Briefing.

make_executive_summary() takes every insight that will appear in the PDF and
returns the three summary parts of the agreed briefing format
(Healthcare_Intelligence_Briefing_sample_output.docx):

    executive_summary  one paragraph: the developments that warrant executive
                       attention, their key figure and what they may affect
    what_changed       3-6 one-line items, each with its priority
    watchlist          one line per Watchlist-priority insight - exactly those,
                       nothing added (Emerging Watchlist section)

How it is produced
------------------
mode="llm"   (default) One LLM call through the pipeline's shared transport
             (pipeline/llm_transport.py), so it uses the same Bedrock or
             API-key setup as the extract and priority-assessment stages.
             The answer is checked before it is used:
               - it must be valid JSON in the expected shape;
               - every insight it cites must exist;
               - every figure (2+ digits) must appear in the insights it cites;
               - every High Priority insight must be in the What Changed list
                 (and in the paragraph, when there are four or fewer);
               - the watchlist must be exactly the Watchlist-priority
                 insights, one item each, with nothing added.
             If a check fails, the model gets one retry with the problem
             explained. If it still fails, or no LLM is configured, the
             rule-based summary below is used instead and the PDF says so.
mode="rules" No LLM call. Built directly from the insights' priorities and
             criteria ratings - same input always gives the same output.
mode="none"  No executive summary.

Configuration (repo-root .env)
------------------------------
EXEC_SUMMARY_API_URL / EXEC_SUMMARY_MODEL / EXEC_SUMMARY_API_KEY are optional.
When they are not set, the PRIORITY_ASSESSMENT_* values are used, so nothing
new needs configuring. LLM_BACKEND (bedrock | api_key) works as for the other
stages.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
PROMPT_PATH = HERE / "prompts" / "executive_summary_v0.3.md"

# Load the repo-root .env when run locally (on Lambda the environment is set).
try:
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass

PRIORITY_RANK = {"High Priority": 0, "Medium Priority": 1,
                 "Watchlist": 2, "Informational": 3}

MAX_WHAT_CHANGED = 6
MAX_LINE_CHARS = 400

# Criteria rating -> plain-English reason it may matter (rules mode only).
CRITERIA_PHRASES = [
    ("cost_implications", {"High"}, "potential impact on claims and benefit costs"),
    ("private_health_relevance", {"High"}, "a direct link to private health cover"),
    ("utilisation_demand", {"High"}, "higher demand for hospital and health services"),
    ("emerging_treatment_or_technology", {"Yes"},
     "a new treatment or technology that may change what members claim for"),
    ("clinical_significance", {"High"}, "significant consequences for member health outcomes"),
    ("population_affected", {"Large"}, "a large share of the population, and so of members"),
]

RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["executive_summary", "summary_refs", "what_changed", "watchlist"],
    "properties": {
        "executive_summary": {"type": "string"},
        "summary_refs": {"type": "array", "items": {"type": "string"}},
        "what_changed": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "refs"],
                "properties": {
                    "text": {"type": "string"},
                    "refs": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "watchlist": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["ref", "topic", "note"],
                "properties": {
                    "ref": {"type": "string"},
                    "topic": {"type": "string"},
                    "note": {"type": "string"},
                },
            },
        },
    },
}


class SummaryCheckError(ValueError):
    """The LLM answer failed a check; the message is sent back on retry."""


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

def _ref(number):
    return f"I{number}"


def build_llm_input(items, sources):
    """items: list of dicts with keys number, insight, section, source."""
    return {
        "sources": [
            {"publisher": s.get("publisher"), "title": s.get("title"),
             "publication_date": s.get("publication_date")}
            for s in sources
        ],
        "insights": [
            {
                "ref": _ref(it["number"]),
                "source": f'{it["source"].get("publisher") or ""} - '
                          f'{it["source"].get("title") or ""}'.strip(" -"),
                "section": it["section"],
                "priority": it["insight"].get("priority"),
                "finding": it["insight"].get("finding"),
                "evidence": it["insight"].get("evidence"),
                "caveat": it["insight"].get("caveat"),
                "target_population": it["insight"].get("target_population"),
                "criteria": it["insight"].get("criteria"),
                "priority_rationale": it["insight"].get("priority_rationale"),
            }
            for it in sorted(items, key=lambda it: (
                PRIORITY_RANK.get(it["insight"].get("priority"), 9), it["number"]))
        ],
    }


# ---------------------------------------------------------------------------
# Checks on the LLM answer
# ---------------------------------------------------------------------------

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text):
    """Figures with 2+ digits, commas removed ('644,600' -> '644600')."""
    found = []
    for raw in _NUMBER.findall(text or ""):
        value = raw.replace(",", "").rstrip(".")
        if len(value.replace(".", "")) >= 2:
            found.append((raw, value))
    return found


def _source_text(insight):
    parts = [insight.get("finding"), insight.get("evidence"), insight.get("caveat")]
    return " ".join(p for p in parts if p).replace(",", "")


def _check_figures(text, refs, text_by_ref, where):
    pool = " ".join(text_by_ref[r] for r in refs)
    for raw, value in _numbers(text):
        if value not in pool:
            raise SummaryCheckError(
                f"{where} contains the figure '{raw}', which does not appear in "
                f"the cited insight(s) {', '.join(refs)}. Use only figures that "
                f"appear in the insights you cite, copied exactly.")


def _parse_json(content):
    text = (content or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise SummaryCheckError("The answer was not a JSON object.")
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise SummaryCheckError(f"The answer was not valid JSON ({exc}).")


def _clean_refs(refs, known, where):
    if not isinstance(refs, list) or not refs:
        raise SummaryCheckError(f"{where} must cite at least one insight in 'refs'.")
    unknown = [r for r in refs if r not in known]
    if unknown:
        raise SummaryCheckError(
            f"{where} cites {', '.join(map(str, unknown))}, which do not exist. "
            f"Valid refs are I1 to I{len(known)}.")
    # keep order, drop repeats
    return list(dict.fromkeys(refs))


def check_llm_summary(raw, items):
    """Validate the parsed LLM answer and return a clean summary dict."""
    if not isinstance(raw, dict):
        raise SummaryCheckError("The answer must be a JSON object.")
    by_ref = {_ref(it["number"]): it for it in items}
    text_by_ref = {r: _source_text(it["insight"]) for r, it in by_ref.items()}
    all_refs = list(by_ref)

    paragraph = raw.get("executive_summary")
    if not isinstance(paragraph, str) or not paragraph.strip():
        raise SummaryCheckError("'executive_summary' must be a non-empty string.")
    summary_refs = _clean_refs(raw.get("summary_refs"), by_ref, "The executive summary")
    _check_figures(paragraph, summary_refs, text_by_ref, "The executive summary")

    # High Priority insights must lead. The paragraph covers all of them when
    # there are four or fewer (otherwise at least four of them).
    high_refs = [r for r, it in by_ref.items()
                 if it["insight"].get("priority") == "High Priority"]
    in_paragraph = [r for r in high_refs if r in summary_refs]
    if len(in_paragraph) < min(len(high_refs), 4):
        missing = [r for r in high_refs if r not in summary_refs]
        raise SummaryCheckError(
            f"The executive summary leaves out High Priority insight(s) "
            f"{', '.join(missing)}. Cover every High Priority insight (related "
            f"ones may be combined) before mentioning any Medium Priority one, "
            f"and list them in 'summary_refs'.")

    changed = raw.get("what_changed")
    if not isinstance(changed, list) or not changed:
        raise SummaryCheckError("'what_changed' must contain at least one item.")
    clean_changed = []
    for n, c in enumerate(changed[:MAX_WHAT_CHANGED], start=1):
        where = f"What-changed item {n}"
        if not isinstance(c, dict) or not (c.get("text") or "").strip():
            raise SummaryCheckError(f"{where} needs a non-empty 'text'.")
        refs = _clean_refs(c.get("refs"), by_ref, where)
        _check_figures(c["text"], refs, text_by_ref, where)
        clean_changed.append({"text": c["text"].strip()[:MAX_LINE_CHARS], "refs": refs})

    covered = {r for c in clean_changed for r in c["refs"]}
    missing = [r for r in high_refs if r not in covered]
    if missing:
        raise SummaryCheckError(
            f"High Priority insight(s) {', '.join(missing)} are missing from "
            f"'what_changed'. List every High Priority insight first (related "
            f"ones may share one item), then Medium Priority, up to "
            f"{MAX_WHAT_CHANGED} items in total.")

    # Show the list highest priority first, whatever order the model used.
    def best_rank(refs):
        return min(PRIORITY_RANK.get(by_ref[r]["insight"].get("priority"), 9)
                   for r in refs)
    clean_changed.sort(key=lambda c: best_rank(c["refs"]))

    # Emerging Watchlist = exactly the Watchlist-priority insights, one item
    # each, in card order. The model only words them; it cannot add or drop any.
    watch_refs = [r for r, it in by_ref.items()
                  if it["insight"].get("priority") == "Watchlist"]
    watch = raw.get("watchlist") or []
    if not isinstance(watch, list):
        raise SummaryCheckError("'watchlist' must be a list.")
    worded = {}
    for n, w in enumerate(watch, start=1):
        where = f"Watchlist item {n}"
        if not isinstance(w, dict) or not (w.get("topic") or "").strip() \
                or not (w.get("note") or "").strip():
            raise SummaryCheckError(f"{where} needs 'ref', 'topic' and 'note'.")
        ref = w.get("ref")
        if ref not in watch_refs:
            raise SummaryCheckError(
                f"{where} refers to {ref!r}, which is not a Watchlist-priority "
                f"insight. The watchlist must contain only these insights: "
                f"{', '.join(watch_refs) or 'none (return an empty list)'}.")
        if ref in worded:
            raise SummaryCheckError(f"{ref} appears twice in 'watchlist'; list it once.")
        _check_figures(w["topic"] + " " + w["note"], [ref], text_by_ref, where)
        worded[ref] = {"topic": w["topic"].strip(),
                       "note": w["note"].strip()[:MAX_LINE_CHARS], "refs": [ref]}
    missing = [r for r in watch_refs if r not in worded]
    if missing:
        raise SummaryCheckError(
            f"Watchlist-priority insight(s) {', '.join(missing)} are missing "
            f"from 'watchlist'. Include every Watchlist insight, one item each.")
    clean_watch = [worded[r] for r in watch_refs]

    return {"executive_summary": paragraph.strip(), "summary_refs": summary_refs,
            "what_changed": clean_changed, "watchlist": clean_watch}


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

def _llm_config():
    def env(name):
        return (os.environ.get(f"EXEC_SUMMARY_{name}")
                or os.environ.get(f"PRIORITY_ASSESSMENT_{name}"))
    return env("API_URL"), env("MODEL"), env("API_KEY") or os.environ.get("OPENAI_API_KEY")


def _transport():
    """Import the pipeline's shared LLM transport (pipeline/llm_transport.py)."""
    pipeline_dir = str(REPO_ROOT / "pipeline")
    if pipeline_dir not in sys.path:
        sys.path.insert(0, pipeline_dir)
    from llm_transport import backend_from_env, post_chat_completion
    return backend_from_env, post_chat_completion


def _chat_content(body):
    try:
        return body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("Unexpected LLM response shape (no choices[0].message.content)")


def llm_summary(items, sources, max_attempts=2):
    """Call the LLM and return (summary, model). Raises on failure."""
    backend_from_env, post_chat_completion = _transport()
    backend = backend_from_env()
    api_url, model, api_key = _llm_config()
    if not (api_url and model):
        raise RuntimeError("Set EXEC_SUMMARY_API_URL/EXEC_SUMMARY_MODEL "
                           "(or PRIORITY_ASSESSMENT_API_URL/_MODEL) in .env")

    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    user_content = json.dumps(build_llm_input(items, sources), ensure_ascii=False)
    messages = [{"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}]

    last_problem = None
    for attempt in range(1, max_attempts + 1):
        payload = {
            "model": model,
            "temperature": 0.0,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "executive_summary", "strict": True,
                                "schema": RESPONSE_SCHEMA},
            },
        }
        body, _ = post_chat_completion(api_url, payload, backend=backend,
                                       api_key=api_key, timeout_seconds=180)
        content = _chat_content(body)
        try:
            return check_llm_summary(_parse_json(content), items), model
        except SummaryCheckError as problem:
            last_problem = problem
            print(f"  executive summary attempt {attempt} failed a check: {problem}")
            # Retry once, telling the model exactly what was wrong.
            messages = messages[:2] + [
                {"role": "assistant", "content": content},
                {"role": "user", "content": f"Your answer failed a check: {problem} "
                                            "Return the corrected JSON object only."},
            ]
    raise RuntimeError(f"LLM summary failed checks: {last_problem}")


# ---------------------------------------------------------------------------
# Rule-based summary (no LLM)
# ---------------------------------------------------------------------------

def rules_summary(items, sources):
    counts = {p: 0 for p in PRIORITY_RANK}
    for it in items:
        p = it["insight"].get("priority")
        if p in counts:
            counts[p] += 1
    publishers = sorted({(s.get("publisher") or "").strip() for s in sources} - {""})

    def strength(it):
        crit = it["insight"].get("criteria") or {}
        return sum(1 for key, good, _ in CRITERIA_PHRASES if crit.get(key) in good)

    ranked = sorted(items, key=lambda it: (
        PRIORITY_RANK.get(it["insight"].get("priority"), 9), -strength(it), it["number"]))
    top = [it for it in ranked
           if it["insight"].get("priority") in ("High Priority", "Medium Priority")][:4]
    if not top:
        top = ranked[:3]

    parts = [f"{counts[p]} {p}" for p in PRIORITY_RANK if counts[p]]
    paragraph = (f"This briefing covers {len(sources)} publication(s)"
                 f"{' from ' + ' and '.join(publishers) if publishers else ''}, "
                 f"with {len(items)} insight(s): {', '.join(parts)}.")
    if counts["High Priority"]:
        paragraph += (f" {counts['High Priority']} development(s) are rated High "
                      "Priority and are listed first below.")
    else:
        paragraph += " No High Priority developments were identified."
    reasons = []
    for it in top:
        crit = it["insight"].get("criteria") or {}
        reasons += [phrase for key, good, phrase in CRITERIA_PHRASES
                    if crit.get(key) in good and phrase not in reasons]
    if reasons:
        paragraph += (" Based on the priority ratings, the leading items may matter "
                      "to Medibank because of " + "; ".join(reasons[:3]) + ".")

    # What Changed: every High Priority insight first, then Medium, up to the limit.
    leading = [it for it in ranked
               if it["insight"].get("priority") in ("High Priority", "Medium Priority")]
    changed = [{"text": it["insight"].get("finding") or "", "refs": [_ref(it["number"])]}
               for it in (leading or ranked)[:MAX_WHAT_CHANGED]]
    # Emerging Watchlist: every Watchlist-priority insight, in card order.
    watch = [{"topic": it["source"].get("title") or "Watchlist item",
              "note": it["insight"].get("finding") or "",
              "refs": [_ref(it["number"])]}
             for it in items if it["insight"].get("priority") == "Watchlist"]
    return {"executive_summary": paragraph, "what_changed": changed,
            "watchlist": watch}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def make_executive_summary(items, sources, mode="llm"):
    """Return the summary dict, or None when mode is 'none' or nothing to summarise.

    The dict has executive_summary, what_changed, watchlist, plus:
      method  "llm" or "rules"
      model   model id (llm only)
      note    why the rules fallback was used, if it was
    """
    if mode == "none" or not items:
        return None
    if mode == "llm":
        started = time.time()
        try:
            summary, model = llm_summary(items, sources)
            summary.update(method="llm", model=model)
            print(f"  executive summary: written by {model} "
                  f"in {time.time() - started:.0f}s")
            return summary
        except Exception as exc:  # any failure -> still produce a briefing
            print(f"  executive summary: LLM unavailable, using rule-based "
                  f"summary instead ({exc})")
            summary = rules_summary(items, sources)
            summary.update(method="rules", note="LLM unavailable")
            return summary
    summary = rules_summary(items, sources)
    summary["method"] = "rules"
    return summary
