"""
Executive summary for the Healthcare Intelligence Briefing.

make_executive_summary() takes every insight that will appear in the PDF and
returns the summary at the top of the briefing: up to two paragraphs, then a
scannable Top 5 Insights list:

    executive_summary  the top 5 insights by priority (High first, then
                       Medium, then Informational; Watchlist excluded), each
                       with its key figure and what it may affect for Medibank
    watch_summary      early signals worth watching, from the Watchlist-
                       priority insights only (at most 3). Empty when the
                       briefing has no Watchlist insights.
    top_insights       the same top 5 as paragraph 1, in the same order, as a
                       list of {ref, title, key_figure}: a short topic label
                       and one key figure, shown with a link to the insight.

How it is produced
------------------
mode="llm"   (default) One LLM call through the pipeline's shared transport
             (pipeline/llm_transport.py), so it uses the same Bedrock or
             API-key setup as the extract and priority-assessment stages.
             The answer is checked before it is used:
               - it must be valid JSON in the expected shape;
               - every insight it cites must exist;
               - every figure (2+ digits) must appear in the insights it cites;
               - paragraph 1 must cite the top 5 by priority rank (no lower
                 rank while a higher one is left out) and no Watchlist insight;
               - paragraph 2 may cite only Watchlist insights (1 to 3), and
                 must be empty when there are none;
               - the Top 5 list must cover exactly the paragraph-1 insights
                 in the same order, with a title for each, and every figure
                 must appear in that entry's own insight.
             These accuracy checks are strict: if the one retry still fails
             one, or no LLM is configured, the rule-based summary is used.
             Style is checked loosely (clearly too long, or a sentence packed
             with figures). A style problem gets the same one retry, but if
             the retry is still too long the accurate answer is kept anyway -
             style never causes the rule-based fallback.
             If only the Top 5 list still fails after the retry, the accurate
             paragraphs are kept and the list alone is built by the rules.
mode="rules" No LLM call. Built directly from the insights' priorities and
             criteria ratings - same input always gives the same output.
mode="none"  No executive summary.

Configuration (repo-root .env)
------------------------------
LLM_BACKEND (bedrock | api_key) works as for the other stages. With bedrock
(the default) the call goes through Bedrock Converse, so Claude models work.
EXEC_SUMMARY_MODEL / EXEC_SUMMARY_REASONING are optional; when unset the
PRIORITY_ASSESSMENT_* values are used, so nothing new needs configuring.
EXEC_SUMMARY_API_URL / EXEC_SUMMARY_API_KEY are only for api_key mode.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
PROMPT_PATH = HERE / "prompts" / "executive_summary_v0.5.md"

# Load the repo-root .env when run locally (on Lambda the environment is set).
try:
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass

PRIORITY_RANK = {"High Priority": 0, "Medium Priority": 1,
                 "Watchlist": 2, "Informational": 3}

# Paragraph 1 covers the top this-many insights; paragraph 2 at most
# MAX_WATCH Watchlist insights.
MAX_DEVELOPMENTS = 5
MAX_WATCH = 3
# Ranks that can appear in paragraph 1, highest first.
TOP_RANKS = ("High Priority", "Medium Priority", "Informational")

# Style limits. The prompt asks for about 120 / 60 words and one figure per
# development; these only catch answers that are clearly over.
MAX_WORDS_SUMMARY = 180
MAX_WORDS_WATCH = 90
MAX_FIGURES_PER_SENTENCE = 2
# Top 5 list: a title is a short label, the key figure a short phrase.
MAX_WORDS_TITLE = 8
MAX_WORDS_KEY_FIGURE = 16

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
    "required": ["executive_summary", "summary_refs", "watch_summary", "watch_refs",
                 "top_insights"],
    "properties": {
        "executive_summary": {"type": "string"},
        "summary_refs": {"type": "array", "items": {"type": "string"}},
        "watch_summary": {"type": "string"},
        "watch_refs": {"type": "array", "items": {"type": "string"}},
        "top_insights": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["ref", "title", "key_figure"],
                "properties": {
                    "ref": {"type": "string"},
                    "title": {"type": "string"},
                    "key_figure": {"type": "string"},
                },
            },
        },
    },
}


class SummaryCheckError(ValueError):
    """The LLM answer failed an accuracy check; the message is sent back on retry."""


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


def _priority(it):
    return it["insight"].get("priority")


def check_llm_summary(raw, items):
    """Validate the parsed LLM answer and return a clean summary dict."""
    if not isinstance(raw, dict):
        raise SummaryCheckError("The answer must be a JSON object.")
    by_ref = {_ref(it["number"]): it for it in items}
    text_by_ref = {r: _source_text(it["insight"]) for r, it in by_ref.items()}
    watch_all = [r for r, it in by_ref.items() if _priority(it) == "Watchlist"]

    # --- Paragraph 1: the top MAX_DEVELOPMENTS insights by rank ---------------
    paragraph = raw.get("executive_summary")
    if not isinstance(paragraph, str) or not paragraph.strip():
        raise SummaryCheckError("'executive_summary' must be a non-empty string.")
    summary_refs = _clean_refs(raw.get("summary_refs"), by_ref, "The executive summary")
    _check_figures(paragraph, summary_refs, text_by_ref, "The executive summary")

    wrong = [r for r in summary_refs if _priority(by_ref[r]) not in TOP_RANKS]
    if wrong:
        raise SummaryCheckError(
            f"The first paragraph cites {', '.join(wrong)}, which are not High, "
            f"Medium or Informational priority. Watchlist insights belong only "
            f"in 'watch_summary'.")
    if len(summary_refs) > MAX_DEVELOPMENTS:
        raise SummaryCheckError(
            f"The first paragraph cites {len(summary_refs)} insights; cite "
            f"exactly the top {MAX_DEVELOPMENTS}.")
    # Fill the 5 places rank by rank: all High (up to 5), then Medium, then
    # Informational. Each rank must contribute what it is owed.
    remaining = MAX_DEVELOPMENTS
    for rank in TOP_RANKS:
        at_rank = [r for r, it in by_ref.items() if _priority(it) == rank]
        owed = min(remaining, len(at_rank))
        cited = [r for r in summary_refs if r in at_rank]
        if len(cited) < owed:
            missing = [r for r in at_rank if r not in summary_refs]
            raise SummaryCheckError(
                f"The first paragraph must cover {owed} {rank} insight(s) but "
                f"covers {len(cited)}. Not covered: {', '.join(missing)}. Take "
                f"the top {MAX_DEVELOPMENTS} in rank order: every High Priority "
                f"insight first (the most important five if there are more), "
                f"then Medium Priority, then Informational.")
        remaining -= owed

    # --- Paragraph 2: early signals (Watchlist only) --------------------------
    watch_text = raw.get("watch_summary") or ""
    if not isinstance(watch_text, str):
        raise SummaryCheckError("'watch_summary' must be a string.")
    watch_text = watch_text.strip()
    watch_refs = raw.get("watch_refs") or []
    if not watch_all:
        # No Watchlist insights: no second paragraph, whatever was returned.
        watch_text, watch_refs = "", []
    else:
        if not watch_text:
            raise SummaryCheckError(
                f"'watch_summary' is empty, but the briefing has Watchlist "
                f"insight(s) {', '.join(watch_all)}. Write the second paragraph "
                f"about up to {MAX_WATCH} of them.")
        watch_refs = _clean_refs(watch_refs, by_ref, "The watch paragraph")
        not_watch = [r for r in watch_refs if r not in watch_all]
        if not_watch:
            raise SummaryCheckError(
                f"The watch paragraph cites {', '.join(not_watch)}, which are not "
                f"Watchlist insights. Use only: {', '.join(watch_all)}.")
        if len(watch_refs) > MAX_WATCH:
            raise SummaryCheckError(
                f"The watch paragraph cites {len(watch_refs)} insights; mention "
                f"at most {MAX_WATCH}.")
        _check_figures(watch_text, watch_refs, text_by_ref, "The watch paragraph")

    return {"executive_summary": paragraph.strip(), "summary_refs": summary_refs,
            "watch_summary": watch_text, "watch_refs": watch_refs}


class TopInsightsError(SummaryCheckError):
    """Only the Top 5 list is wrong; the paragraphs passed their checks."""


def check_top_insights(raw, summary_refs, items):
    """Validate the Top 5 list against the paragraph-1 refs; return a clean list."""
    by_ref = {_ref(it["number"]): it for it in items}
    text_by_ref = {r: _source_text(it["insight"]) for r, it in by_ref.items()}
    entries = raw.get("top_insights") if isinstance(raw, dict) else None
    if not isinstance(entries, list) or not entries:
        raise TopInsightsError(
            f"'top_insights' is missing. Give one entry per summary ref, in "
            f"the same order: {', '.join(summary_refs)}.")
    refs = [e.get("ref") if isinstance(e, dict) else None for e in entries]
    if refs != summary_refs:
        raise TopInsightsError(
            f"'top_insights' covers {', '.join(map(str, refs))} but must cover "
            f"exactly the summary refs, in the same order: "
            f"{', '.join(summary_refs)}.")
    clean = []
    for entry in entries:
        ref = entry["ref"]
        title = (entry.get("title") or "").strip().rstrip(".")
        key_figure = (entry.get("key_figure") or "").strip().rstrip(".")
        if not title:
            raise TopInsightsError(f"The Top 5 entry for {ref} has no 'title'.")
        if _numbers(title):
            raise TopInsightsError(
                f"The Top 5 title for {ref} ('{title}') contains a figure; put "
                f"figures only in 'key_figure'.")
        try:
            _check_figures(key_figure, [ref], text_by_ref,
                           f"The Top 5 key figure for {ref}")
        except SummaryCheckError as problem:
            raise TopInsightsError(str(problem))
        clean.append({"ref": ref, "title": title, "key_figure": key_figure})
    return clean


_YEAR = re.compile(r"\b(?:19|20)\d{2}(?:\s*[\u2013\u2014/-]\s*\d{2,4})?\b")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(])")


def _figure_count(sentence):
    """Figures (2+ digits) in a sentence, not counting years like 2024-25."""
    return len(_numbers(_YEAR.sub(" ", sentence)))


def style_problem(summary):
    """Return a message if the summary is clearly too long or too dense with
    figures, else None. Loose on purpose - see the module docstring."""
    problems = []
    for key, label, limit in (("executive_summary", "The first paragraph", MAX_WORDS_SUMMARY),
                              ("watch_summary", "The watch paragraph", MAX_WORDS_WATCH)):
        text = summary.get(key) or ""
        words = len(text.split())
        if words > limit:
            problems.append(f"{label} is {words} words; keep it to about "
                            f"{limit * 2 // 3} words.")
        dense = [sent for sent in _SENTENCE_END.split(text)
                 if _figure_count(sent) > MAX_FIGURES_PER_SENTENCE]
        if dense:
            problems.append(f"{label} has {len(dense)} sentence(s) with more than "
                            f"{MAX_FIGURES_PER_SENTENCE} figures, e.g. \"{dense[0][:120]}\". "
                            "Use one figure per development.")
    for entry in summary.get("top_insights") or []:
        if len(entry["title"].split()) > MAX_WORDS_TITLE:
            problems.append(f"The Top 5 title for {entry['ref']} is too long; use "
                            f"2 to 6 words.")
        if (len(entry["key_figure"].split()) > MAX_WORDS_KEY_FIGURE
                or _figure_count(entry["key_figure"]) > 1):
            problems.append(f"The Top 5 key figure for {entry['ref']} is too long "
                            "or has more than one figure; use one figure in at "
                            "most 12 words.")
    if not problems:
        return None
    return ("The answer is accurate but hard to read: " + " ".join(problems)
            + " Rewrite it shorter in plain language, keeping the same insights.")


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

def _env(name, default=None):
    """EXEC_SUMMARY_<name>, falling back to PRIORITY_ASSESSMENT_<name>."""
    return (os.environ.get(f"EXEC_SUMMARY_{name}")
            or os.environ.get(f"PRIORITY_ASSESSMENT_{name}")
            or default)


def _transport():
    """Import the pipeline's shared LLM transport (pipeline/llm_transport.py)."""
    pipeline_dir = str(REPO_ROOT / "pipeline")
    if pipeline_dir not in sys.path:
        sys.path.insert(0, pipeline_dir)
    import llm_transport
    return llm_transport


def _chat_content(body):
    try:
        return body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("Unexpected LLM response shape (no choices[0].message.content)")


def _converse_content(body):
    try:
        blocks = body["output"]["message"]["content"]
    except (KeyError, TypeError):
        raise RuntimeError("Unexpected Bedrock response shape (no output.message.content)")
    texts = [b["text"] for b in blocks if isinstance(b, dict) and b.get("text")]
    if not texts:
        raise RuntimeError("Bedrock response had no text content")
    return "".join(texts)


def _ask_bedrock(transport, model, system_prompt, user_text):
    body, _ = transport.converse(
        model, system_prompt, user_text,
        response_schema=RESPONSE_SCHEMA,
        response_schema_name="executive_summary",
        reasoning=_env("REASONING", "off"),
        temperature=0.0,
        timeout_seconds=180,
        max_attempts=2,
    )
    return _converse_content(body)


def _ask_api_key(transport, model, messages):
    api_url = _env("API_URL")
    api_key = _env("API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_url:
        raise RuntimeError("LLM_BACKEND=api_key needs EXEC_SUMMARY_API_URL "
                           "(or PRIORITY_ASSESSMENT_API_URL) in .env")
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
    body, _ = transport.post_chat_completion(api_url, payload, api_key=api_key,
                                             timeout_seconds=180)
    return _chat_content(body)


def llm_summary(items, sources, max_attempts=2):
    """Call the LLM and return (summary, model). Raises on failure.

    LLM_BACKEND=bedrock (default): Bedrock Converse, so Claude models work.
    LLM_BACKEND=api_key: an OpenAI-compatible chat-completions endpoint.
    """
    transport = _transport()
    backend = transport.backend_from_env()
    model = _env("MODEL")
    if not model:
        raise RuntimeError("Set EXEC_SUMMARY_MODEL (or PRIORITY_ASSESSMENT_MODEL) in .env")

    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    user_content = json.dumps(build_llm_input(items, sources), ensure_ascii=False)

    last_problem = None
    previous = None
    accurate = None   # an accurate answer that only failed the style check
    paragraphs_ok = None  # accurate paragraphs whose Top 5 list failed a check
    for attempt in range(1, max_attempts + 1):
        if previous is None:
            user_text = user_content
            messages = [{"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content}]
        else:
            # Retry once, telling the model exactly what was wrong.
            fix = (f"Your answer failed a check: {last_problem} "
                   "Return the corrected JSON object only.")
            user_text = (f"{user_content}\n\nYour previous answer was:\n{previous}"
                         f"\n\n{fix}")
            messages = [{"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                        {"role": "assistant", "content": previous},
                        {"role": "user", "content": fix}]

        if backend == "bedrock":
            content = _ask_bedrock(transport, model, system_prompt, user_text)
        else:
            content = _ask_api_key(transport, model, messages)

        try:
            raw = _parse_json(content)
            summary = check_llm_summary(raw, items)
        except SummaryCheckError as problem:
            last_problem = problem
            previous = content
            print(f"  executive summary attempt {attempt} failed a check: {problem}")
            continue
        try:
            summary["top_insights"] = check_top_insights(
                raw, summary["summary_refs"], items)
        except TopInsightsError as problem:
            paragraphs_ok = summary
            last_problem = problem
            previous = content
            print(f"  executive summary attempt {attempt} Top 5 list failed a "
                  f"check: {problem}")
            continue

        problem = style_problem(summary)
        if problem is None:
            return summary, model
        accurate = summary
        last_problem = problem
        previous = content
        print(f"  executive summary attempt {attempt} style: {problem}")

    if accurate is not None:
        # Accurate but long: better than the rule-based fallback.
        print("  executive summary: keeping the accurate (if long) answer")
        return accurate, model
    if paragraphs_ok is not None:
        # Paragraphs are accurate; only the list failed. Keep the paragraphs
        # and build the list from the insights themselves.
        print("  executive summary: Top 5 list built by the rules instead")
        paragraphs_ok["top_insights"] = rules_top_insights(
            paragraphs_ok["summary_refs"], items)
        paragraphs_ok["top_insights_method"] = "rules"
        return paragraphs_ok, model
    raise RuntimeError(f"LLM summary failed checks: {last_problem}")


# ---------------------------------------------------------------------------
# Rule-based summary (no LLM)
# ---------------------------------------------------------------------------

_CLAUSE_SPLIT = re.compile(r"\s*(?:[:;]|,\s|\s[\u2013\u2014-]\s)\s*")


def _shorten(text, max_words):
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).rstrip(",;:") + "\u2026"


def rules_top_insights(refs, items):
    """Top 5 list without an LLM: the opening words of each finding as the
    title, and a clause holding a figure (not the opening one, where there
    is another) as the key figure. Plainer than the LLM list, but accurate."""
    by_ref = {_ref(it["number"]): it for it in items}
    entries = []
    for ref in refs:
        finding = (by_ref[ref]["insight"].get("finding") or "").strip().rstrip(".")
        clauses = [c for c in _CLAUSE_SPLIT.split(finding) if c]
        title = _shorten(clauses[0] if clauses else finding, 7) or "See insight"
        with_figure = [c for c in clauses[1:] if _figure_count(c)] or \
                      [c for c in clauses[:1] if _figure_count(c)]
        key_figure = _shorten(with_figure[0], 12) if with_figure else ""
        entries.append({"ref": ref, "title": title, "key_figure": key_figure})
    return entries


def rules_summary(items, sources):
    counts = {p: 0 for p in PRIORITY_RANK}
    for it in items:
        if _priority(it) in counts:
            counts[_priority(it)] += 1
    publishers = sorted({(s.get("publisher") or "").strip() for s in sources} - {""})

    def strength(it):
        crit = it["insight"].get("criteria") or {}
        return sum(1 for key, good, _ in CRITERIA_PHRASES if crit.get(key) in good)

    ranked = sorted(items, key=lambda it: (
        PRIORITY_RANK.get(_priority(it), 9), -strength(it), it["number"]))
    top = [it for it in ranked if _priority(it) in TOP_RANKS][:MAX_DEVELOPMENTS]
    watch = [it for it in ranked if _priority(it) == "Watchlist"][:MAX_WATCH]

    parts = [f"{counts[p]} {p}" for p in PRIORITY_RANK if counts[p]]
    paragraph = (f"This briefing covers {len(sources)} publication(s)"
                 f"{' from ' + ' and '.join(publishers) if publishers else ''}, "
                 f"with {len(items)} insight(s): {', '.join(parts)}.")
    if counts["High Priority"]:
        paragraph += (f" {counts['High Priority']} development(s) are rated High "
                      "Priority.")
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

    watch_text = ""
    if watch:
        findings = [(it["insight"].get("finding") or "").strip().rstrip(".")
                    for it in watch]
        watch_text = ("Early signals worth watching: "
                      + "; ".join(f for f in findings if f) + ".")

    summary_refs = [_ref(it["number"]) for it in top]
    return {"executive_summary": paragraph,
            "summary_refs": summary_refs,
            "watch_summary": watch_text,
            "watch_refs": [_ref(it["number"]) for it in watch],
            "top_insights": rules_top_insights(summary_refs, items)}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def make_executive_summary(items, sources, mode="llm"):
    """Return the summary dict, or None when mode is 'none' or nothing to summarise.

    The dict has executive_summary, summary_refs, watch_summary, watch_refs
    and top_insights, plus:
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
