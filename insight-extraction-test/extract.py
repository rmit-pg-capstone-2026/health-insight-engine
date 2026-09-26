#!/usr/bin/env python3

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from schema import EXTRACTION_SCHEMA, RESPONSE_FORMAT  # noqa: E402

try:
    import jsonschema
except ImportError:
    jsonschema = None

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
PROMPT_PATH = HERE / "prompt.md"
RUNS_DIR = HERE / "runs"
# Shared pipeline folders: stage 1 writes the first, stage 3 reads the second.
SOURCE_DIR = REPO_ROOT / "data" / "source-extracted-files"
OUTPUT_DIR = REPO_ROOT / "data" / "insight-generated-files"

# Settings come from the repo-root .env. Anything already set in the shell
# wins, so a one-off `export` still overrides the file.
try:
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass
TEXT_SUFFIXES = (".txt", ".md", ".markdown")
BINARY_SUFFIXES = (".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".zip")
API_URL = "https://openrouter.ai/api/v1/chat/completions"
MODELS_URL = "https://openrouter.ai/api/v1/models"


DEFAULT_MODELS = [
    "anthropic/claude-haiku-4.5",          # quality bar
    "mistralai/mistral-small",             # mid open-weight
    "deepseek/deepseek-v4-flash-0731",     # cheap open-weight
]

TIMEOUT = 180
MAX_RETRIES = 3


# ----------------------------------------------------------- model check

def check_models(models):
    """Ask OpenRouter which of these models actually support a strict JSON
    schema, and what they cost. No API key needed - the endpoint is public.

    Note: supported_parameters is the union across every provider serving the
    model. An individual provider may still not support it, which is why the
    extraction call sets provider.require_parameters to true."""
    try:
        resp = requests.get(MODELS_URL, timeout=60)
        resp.raise_for_status()
        catalogue = {m["id"]: m for m in resp.json().get("data", [])}
    except (requests.RequestException, ValueError, KeyError) as exc:
        sys.exit("Could not fetch the model list: %s" % exc)

    print("%-38s %-10s %-12s %s" % ("MODEL", "SCHEMA?", "$/M IN", "$/M OUT"))
    print("-" * 74)
    ok = True
    for model in models:
        entry = catalogue.get(model)
        if entry is None:
            print("%-38s %s" % (model, "NOT FOUND - check the slug"))
            ok = False
            continue
        params = entry.get("supported_parameters") or []
        supported = "structured_outputs" in params
        ok = ok and supported
        pricing = entry.get("pricing") or {}

        def per_million(key):
            try:
                return "$%.3f" % (float(pricing.get(key, 0)) * 1_000_000)
            except (TypeError, ValueError):
                return "n/a"

        print("%-38s %-10s %-12s %s" % (
            model, "yes" if supported else "NO",
            per_million("prompt"), per_million("completion")))
        if not supported:
            print("    supported parameters: %s" % ", ".join(sorted(params)))
    print()
    if not ok:
        print("At least one model can't do strict JSON schemas. Swap it out, or")
        print("expect require_parameters to refuse the call.")
    return ok


# ---------------------------------------------------------------- API call

REASONING_CHOICES = ["off", "low", "medium", "high", "default"]


def build_reasoning(setting):
    """Translate our --reasoning flag into OpenRouter's `reasoning` parameter.

    "default" means send nothing and let the model do whatever it normally
    does. "off" actually disables thinking (as opposed to `exclude`, which
    only hides it from the response - you still pay for those tokens)."""
    if setting == "default":
        return None
    if setting == "off":
        return {"enabled": False}
    return {"effort": setting}


def _looks_like_routing_error(text):
    """Did the request fail because no provider supports what we asked for?"""
    lowered = (text or "").lower()
    return any(s in lowered for s in (
        "no allowed providers", "no endpoints", "not support",
        "no providers", "unsupported parameter",
    ))


def call_model(model, article_text, system_prompt, api_key,
               temperature=0.0, reasoning="off", provider=None, indent="    "):
    """One extraction call. Returns (parsed_json_or_None, metadata_dict).

    Prints progress as it goes, so a slow call is visibly different from a
    hung one."""
    payload = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    "Read the document below and produce the briefing "
                    "insights.\n\n"
                    "<article>\n" + article_text + "\n</article>"
                ),
            },
        ],
        "response_format": RESPONSE_FORMAT,
        # Only route to providers that actually support a strict JSON schema.
        # Without this, a provider that ignores response_format returns prose
        # and you spend a day blaming the prompt.
        "provider": {"require_parameters": True},
        # Ask OpenRouter to return the real cost of this call.
        "usage": {"include": True},
    }
    reasoning_param = build_reasoning(reasoning)
    if reasoning_param is not None:
        payload["reasoning"] = reasoning_param

    if provider:
        # Pin to one backend. The same model served by different providers
        # gives different results (different hardware, quantisation and
        # serving config), which otherwise shows up as "prompt instability".
        # allow_fallbacks False means the call fails rather than quietly
        # going elsewhere - which is what you want while measuring.
        payload["provider"]["only"] = [provider]
        payload["provider"]["allow_fallbacks"] = False

    headers = {
        "Authorization": "Bearer " + api_key,
        "Content-Type": "application/json",
    }

    last_error = None
    dropped_reasoning = False

    for attempt in range(1, MAX_RETRIES + 1):
        print("%sattempt %d/%d, waiting (timeout %ds) ... "
              % (indent, attempt, MAX_RETRIES, TIMEOUT), end="", flush=True)
        started = time.time()
        try:
            resp = requests.post(
                API_URL, headers=headers, json=payload, timeout=TIMEOUT
            )
        except requests.Timeout:
            elapsed = time.time() - started
            print("timed out after %.0fs" % elapsed)
            last_error = "timed out after %.0fs" % elapsed
            if attempt < MAX_RETRIES:
                print("%sretrying" % indent)
            continue
        except requests.RequestException as exc:
            elapsed = time.time() - started
            print("failed after %.0fs (%s)" % (elapsed, exc))
            last_error = "request failed: %s" % exc
            if attempt < MAX_RETRIES:
                print("%sretrying in %ds" % (indent, 2 * attempt))
                time.sleep(2 * attempt)
            continue

        elapsed = time.time() - started
        print("responded in %.1fs" % elapsed)

        if resp.status_code != 200:
            last_error = "HTTP %s: %s" % (resp.status_code, resp.text[:500])
            # Asking for `reasoning` narrows routing to providers that support
            # it. If that is what broke, drop it and try once more.
            if ("reasoning" in payload and not dropped_reasoning
                    and _looks_like_routing_error(resp.text)):
                print("%sno provider accepted the reasoning setting - "
                      "retrying without it" % indent)
                payload.pop("reasoning")
                dropped_reasoning = True
                continue
            print("%sHTTP %s: %s" % (indent, resp.status_code,
                                     resp.text[:300]))
            if resp.status_code != 429 and 400 <= resp.status_code < 500:
                break
            if attempt < MAX_RETRIES:
                print("%sretrying in %ds" % (indent, 2 * attempt))
                time.sleep(2 * attempt)
            continue

        body = resp.json()
        usage = body.get("usage") or {}
        details = usage.get("completion_tokens_details") or {}
        meta = {
            "model_returned": body.get("model"),
            "provider": body.get("provider"),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "reasoning_tokens": details.get("reasoning_tokens"),
            "cost_usd": usage.get("cost"),
            "seconds": round(elapsed, 1),
            "reasoning_setting": "dropped" if dropped_reasoning else reasoning,
            "provider_pinned": provider,
            "error": None,
        }

        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError):
            meta["error"] = "no content in response"
            meta["raw"] = body
            return None, meta

        parsed = parse_json(content)
        if parsed is None:
            meta["error"] = "response was not valid JSON"
            meta["raw_content"] = content
            return None, meta
        return parsed, meta

    return None, {"error": last_error or "unknown failure", "seconds": None}


def parse_json(content):
    """Parse the model's reply, tolerating a code fence around the JSON."""
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```[a-zA-Z]*\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    # Last resort: the outermost {...} block.
    start, end = content.find("{"), content.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(content[start:end + 1])
        except json.JSONDecodeError:
            return None
    return None


# ------------------------------------------------------------ verification

LIST_MARKER = re.compile(r"^\s*(?:[-*•‣▪◦]+|\d+[.)])\s+")
ELLIPSIS = re.compile(r"\s*(?:\.\.\.+|…)\s*")


def normalise(text):
    """Collapse whitespace and unify punctuation for comparison.

    Source documents are markdown, so a quote the model copies faithfully can
    still differ from the file by a leading "- " bullet marker or a pair of
    emphasis asterisks. Those are formatting, not content, and treating them
    as mismatches made the checker cry wolf on nearly every quote."""
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("–", "-").replace("—", "-")
    text = text.replace(" ", " ")
    # Strip list markers per line, so a quote spanning several bullets matches.
    lines = [LIST_MARKER.sub("", ln) for ln in text.split("\n")]
    text = " ".join(lines).replace("*", "").replace("_", "")
    return re.sub(r"\s+", " ", text).strip().lower()


SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")


def evidence_fragments(evidence):
    """Break a quote into checkable pieces: first on ellipses, then on
    sentence boundaries.

    The prompt asks for one contiguous passage. When the model instead
    stitches separate sentences together, every piece can be real while the
    passage as a whole never existed - so we need to tell those apart."""
    pieces = []
    for part in ELLIPSIS.split(evidence or ""):
        part = part.strip()
        if part:
            pieces.extend(p.strip() for p in SENTENCE_END.split(part) if p.strip())
    return pieces or ([evidence] if evidence else [])


def verify_quotes(result, article_text):
    """Check every insight's evidence appears verbatim in the source.

    The finding itself is written by the model and cannot be checked this way,
    so evidence is the only anchor left - it matters more here than it did
    when findings were copied."""
    haystack = normalise(article_text)
    checks = []
    for i, ins in enumerate(result.get("insights", [])):
        evidence = ins.get("evidence", "")
        finding = ins.get("finding", "")
        fragments = evidence_fragments(evidence)
        found = [normalise(f) in haystack for f in fragments] or [False]
        contiguous = bool(evidence) and normalise(evidence) in haystack
        checks.append({
            "index": i,
            "finding": finding,
            # Every piece is real text from the document.
            "found_in_source": all(found),
            # The passage appears in the document exactly as quoted.
            "contiguous_in_source": contiguous,
            # Real sentences welded into a passage that never existed.
            "stitched": all(found) and not contiguous and len(fragments) > 1,
            "fragments": len(fragments),
            "fragments_missing": [
                f[:200] for f, ok in zip(fragments, found) if not ok],
            "is_ellipsis_joined": bool(ELLIPSIS.search(evidence or "")),
            "finding_is_copied": (
                normalise(finding) == normalise(evidence) and bool(finding)),
            "evidence": evidence,
        })
    return checks


STOP = set(
    "the a an of and or to in on for with by at as is are was were be been had "
    "has have this that these those it its their there who whom which what "
    "more than over under about from into during between among people person "
    "persons year years aged age last previous prior months month any all "
    "three four five one two half most some each per cent percent".split())


def _content_words(text):
    return {w for w in re.findall(r"[a-z][a-z0-9-]{2,}", (text or "").lower())
            if w not in STOP}


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / float(len(a | b))


def check_direction(result):
    """Catch reversed conditionals.

    "74.9% of people with suicidal thoughts had a mental disorder" and
    "74.9% of people with a mental disorder had suicidal thoughts" are
    different claims, and only one of them is in the document. The quote check
    passes either way because the evidence is verbatim and correct - it is the
    finding that is wrong.

    The signature is mechanical: the same percentage appears in both, and the
    group named BEFORE it in the finding is the group named AFTER it in the
    evidence, and vice versa."""
    flagged = []
    for i, ins in enumerate(result.get("insights", [])):
        finding = ins.get("finding") or ""
        evidence = ins.get("evidence") or ""
        pct_re = re.compile(r"\d+(?:\.\d+)?\s*%")
        shared = (set(pct_re.findall(finding.replace(" %", "%")))
                  & set(pct_re.findall(evidence.replace(" %", "%"))))
        for pct in shared:
            fi = finding.find(pct)
            # Compare against the fragment that actually holds this figure,
            # not the whole quote - otherwise unrelated sentences in a
            # stitched passage poison the comparison.
            frag = next((f for f in evidence_fragments(evidence) if pct in f),
                        evidence)
            ei = frag.find(pct)
            if fi < 0 or ei < 0:
                continue
            fb = _content_words(finding[max(0, fi - 90):fi])
            fa = _content_words(finding[fi + len(pct):fi + len(pct) + 90])
            eb = _content_words(frag[max(0, ei - 90):ei])
            ea = _content_words(frag[ei + len(pct):ei + len(pct) + 90])
            straight = _jaccard(fb, eb) + _jaccard(fa, ea)
            swapped = _jaccard(fb, ea) + _jaccard(fa, eb)
            # The genuine reversal scored 1.38; the false positives 0.31-0.69.
            if swapped > straight and swapped >= 0.90:
                flagged.append({
                    "index": i,
                    "percentage": pct,
                    "straight_score": round(straight, 2),
                    "swapped_score": round(swapped, 2),
                    "finding": finding[:160],
                    "evidence": frag[:160],
                })
                break
    return flagged


def check_scope(result):
    """The out-of-scope verdict and the insight list have to agree.

    A model that says out_of_scope and then lists six insights has decided
    one thing and done another, which is worth seeing rather than silently
    keeping the insights."""
    scope = result.get("document_scope")
    n = len(result.get("insights") or [])
    problems = []
    if scope == "out_of_scope" and n:
        problems.append("document_scope is out_of_scope but %d insight(s) "
                        "were returned" % n)
    if scope == "out_of_scope" and not result.get("no_insights_reason"):
        problems.append("document_scope is out_of_scope but no reason given")
    if not n and not result.get("no_insights_reason"):
        problems.append("no insights returned and no reason given")
    return problems


def check_reasoning(result):
    """Flag reasoning that could be pasted under any other finding. The
    prompt bans these phrases by name; this counts how often it ignores it."""
    lazy = [
        "informs health service planning", "affects demand for health services",
        "relevant to healthcare", "supports strategic planning",
        "can lead to", "may result in", "could drive", "is associated with",
        "may affect", "relates to",
    ]
    flagged = []
    for i, ins in enumerate(result.get("insights", [])):
        text = (ins.get("reasoning") or "").lower()
        hits = [p for p in lazy if p in text]
        if hits:
            flagged.append({"index": i, "phrases": hits,
                            "finding": ins.get("finding", "")[:80]})
    return flagged


def validate_schema(result):
    if jsonschema is None:
        return ["jsonschema not installed - skipped structural validation"]
    validator = jsonschema.Draft7Validator(EXTRACTION_SCHEMA)
    return [
        "%s: %s" % ("/".join(str(p) for p in e.path) or "(root)", e.message)
        for e in validator.iter_errors(result)
    ]


def annotate(result, retrieval_date):
    """Add the two fields the model never sees.

    insight_id is assigned here rather than asked for, because models are
    unreliable at sequential numbering; retrieval_date is assigned here
    because a model cannot know when the file was fetched. Both are added in
    place, after validation, so the wire schema stays exactly what was sent.

    Ids are per document. If the next stage merges several documents into one
    briefing it should prefix these with a source identifier of its own."""
    if not isinstance(result, dict):
        return result
    source = result.setdefault("source", {})
    if isinstance(source, dict):
        source["retrieval_date"] = retrieval_date
    for n, ins in enumerate(result.get("insights") or [], 1):
        if isinstance(ins, dict):
            ins["insight_id"] = "INSIGHT_%03d" % n
    return result


def load_article(path):
    """Read one article, or raise ValueError with a readable reason."""
    if path.suffix.lower() in BINARY_SUFFIXES:
        raise ValueError("%s is a binary format - convert to .txt or .md first"
                         % path.suffix)
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise ValueError("not readable as UTF-8 text")
    if not text.strip():
        raise ValueError("file is empty")
    return text


def process_article(path, prompt, api_key, out_dir, args):
    """Run every model over one article. Returns {model: [run records]}."""
    article_text = load_article(path)
    print("Article:   %s (%d characters)" % (path.name, len(article_text)))
    print("Reasoning: %s" % args.reasoning)
    print("Provider:  %s" % (args.provider or "whatever OpenRouter picks"))
    print("Output:    %s\n" % out_dir)

    all_runs = {}
    for model in args.models:
        print(model)
        all_runs[model] = run_model(
            model, article_text, prompt, api_key, args.repeats, out_dir,
            args.temperature, args.reasoning, args.provider, path.stem,
        )
    return all_runs


def run_batch(in_dir, out_dir, prompt, api_key, args):
    """Process every text file in a folder, writing results flat into another.

    One file failing does not stop the batch - a run of twenty articles
    should not be lost because the fourth one was a PDF."""
    if not in_dir.is_dir():
        sys.exit("No such folder: %s\nCreate it and put .txt or .md files in "
                 "it, or pass a single file path instead." % in_dir)

    files = sorted(f for f in in_dir.iterdir()
                   if f.is_file() and f.suffix.lower() in TEXT_SUFFIXES)
    skipped = sorted(f.name for f in in_dir.iterdir()
                     if f.is_file() and f.suffix.lower() not in TEXT_SUFFIXES
                     and not f.name.startswith("."))
    if not files:
        sys.exit("No .txt or .md files in %s" % in_dir)

    out_dir.mkdir(parents=True, exist_ok=True)
    print("Batch: %d file(s) from %s" % (len(files), in_dir))
    print("       output to %s" % out_dir)
    if skipped:
        print("       ignoring non-text file(s): %s" % ", ".join(skipped))
    print()

    results, failures = {}, []
    for i, path in enumerate(files, 1):
        print("-" * 74)
        print("[%d/%d] %s" % (i, len(files), path.name))
        print("-" * 74)
        try:
            results[path.name] = process_article(
                path, prompt, api_key, out_dir, args)
        except ValueError as exc:
            print("  SKIPPED: %s" % exc)
            failures.append((path.name, str(exc)))
        except Exception as exc:                       # keep the batch alive
            print("  FAILED: %s" % exc)
            failures.append((path.name, str(exc)))
        print()

    batch_summary(results, failures)
    return results


def batch_summary(results, failures):
    print("=" * 78)
    print("BATCH SUMMARY")
    print("=" * 78)
    print("%-26s %-34s %8s %6s %6s" % ("ARTICLE", "MODEL", "INSIGHTS",
                                       "FLAGS", "COST"))
    print("-" * 78)
    total_cost, total_insights, total_flags = 0.0, 0, 0
    for name, all_runs in results.items():
        for model, runs in all_runs.items():
            for r in runs:
                if r["result"] is None:
                    print("%-26s %-34s %8s %6s %6s"
                          % (name[:26], model[:34], "FAILED", "-", "-"))
                    continue
                n = len(r["result"].get("insights", []))
                flags = (
                    sum(1 for c in r["quote_checks"]
                        if not c["found_in_source"])
                    + len(r.get("lazy_reasoning", []))
                    + len(r.get("reversed_conditionals", []))
                    + len(r.get("scope_problems", []))
                    + len(r.get("schema_errors", []))
                )
                cost = r["meta"].get("cost_usd") or 0.0
                total_cost += cost
                total_insights += n
                total_flags += flags
                print("%-26s %-34s %8d %6d %6s"
                      % (name[:26], model[:34], n, flags, "$%.4f" % cost))
    print("-" * 78)
    print("%d insight(s), %d flag(s), $%.4f total"
          % (total_insights, total_flags, total_cost))
    if failures:
        print("\n%d file(s) not processed:" % len(failures))
        for name, why in failures:
            print("  %-30s %s" % (name, why))
    print("\nReview anything with flags before passing these on.")


# ------------------------------------------------------------- run + report

def run_model(model, article_text, prompt, api_key, repeats, out_dir,
              temperature, reasoning, provider, stem):
    runs = []
    retrieval_date = time.strftime("%Y-%m-%d")
    for n in range(1, repeats + 1):
        print("  run %d/%d" % (n, repeats))
        result, meta = call_model(model, article_text, prompt, api_key,
                                  temperature, reasoning, provider)

        record = {"model": model, "run": n, "meta": meta, "result": result}
        if result is not None:
            # Validate the model's output first, then add our own fields -
            # otherwise additionalProperties:false rejects what we just added.
            record["schema_errors"] = validate_schema(result)
            annotate(result, retrieval_date)
            record["quote_checks"] = verify_quotes(result, article_text)
            record["lazy_reasoning"] = check_reasoning(result)
            record["reversed_conditionals"] = check_direction(result)
            record["scope_problems"] = check_scope(result)

        path = out_dir / ("%s__%s__run%d.json"
                          % (stem, model.replace("/", "_"), n))
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False))
        runs.append(record)

        if result is None:
            print("    FAILED: %s" % meta.get("error"))
        else:
            bad_quotes = sum(
                1 for c in record["quote_checks"] if not c["found_in_source"]
            )
            copied = sum(
                1 for c in record["quote_checks"] if c["finding_is_copied"]
            )
            reasoning_note = ""
            if meta.get("reasoning_tokens"):
                reasoning_note = ", %s reasoning tokens" % meta["reasoning_tokens"]
            reversed_n = len(record["reversed_conditionals"])
            for msg in record["scope_problems"]:
                print("      !! %s" % msg)
            print("      scope: %s" % result.get("document_scope"))
            stitched_n = sum(
                1 for c in record["quote_checks"] if c.get("stitched"))
            if stitched_n:
                print("      %d quote(s) stitched from non-adjacent sentences"
                      % stitched_n)
            print("    %d insights, %d schema errors, %d unverified "
                  "evidence, %d copied findings, %d lazy reasoning, "
                  "%d REVERSED%s"
                  % (len(result.get("insights", [])),
                     len(record["schema_errors"]), bad_quotes, copied,
                     len(record["lazy_reasoning"]), reversed_n, reasoning_note))
            for rv in record["reversed_conditionals"]:
                print("      !! possible reversed conditional (%s) in insight %d"
                      % (rv["percentage"], rv["index"] + 1))
    return runs


def stability(runs):
    """How much do repeat runs agree? Compares the set of quotes each run
    returned - if the model is picking different findings each time, the
    granularity rule in the prompt is not landing."""
    ok = [r for r in runs if r["result"] is not None]
    if len(ok) < 2:
        return None
    sets = [
        {normalise(i.get("evidence", ""))
         for i in r["result"].get("insights", [])}
        for r in ok
    ]
    counts = [len(s) for s in sets]
    common = set.intersection(*sets)
    union = set.union(*sets)
    return {
        "insights_per_run": counts,
        "in_every_run": len(common),
        "seen_at_least_once": len(union),
        "agreement": round(len(common) / len(union), 2) if union else None,
    }


def summarise(all_runs):
    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)
    total_cost = 0.0
    for model, runs in all_runs.items():
        print("\n%s" % model)
        for r in runs:
            meta = r["meta"]
            if r["result"] is None:
                print("  run %d: FAILED - %s" % (r["run"], meta.get("error")))
                continue
            cost = meta.get("cost_usd")
            total_cost += cost or 0.0
            unverified = sum(
                1 for c in r["quote_checks"] if not c["found_in_source"]
            )
            copied = sum(
                1 for c in r["quote_checks"] if c["finding_is_copied"]
            )
            stitched = sum(1 for c in r["quote_checks"] if c.get("stitched"))
            print("  run %d: %2d insights | %d schema err | %d unverified"
                  " evidence | %d stitched | %d copied | %d lazy |"
                  " %d reversed | %ss | %s | %s"
                  % (r["run"], len(r["result"].get("insights", [])),
                     len(r["schema_errors"]), unverified, stitched, copied,
                     len(r.get("lazy_reasoning", [])),
                     len(r.get("reversed_conditionals", [])),
                     meta.get("seconds"),
                     meta.get("provider") or "?",
                     ("$%.5f" % cost) if cost is not None else "cost n/a"))
        s = stability(runs)
        if s:
            print("  stability: %s insights per run, %d passage(s) in every "
                  "run of %d seen, agreement %s"
                  % (s["insights_per_run"], s["in_every_run"],
                     s["seen_at_least_once"], s["agreement"]))
    if total_cost:
        print("\nTotal cost this session: $%.5f" % total_cost)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("article", nargs="?",
                    help="a single .txt or .md file. Omit it to process every "
                         "text file in --in-dir instead")
    ap.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    ap.add_argument("--repeats", type=int, default=1,
                    help="run each model this many times on the same article")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--reasoning", choices=REASONING_CHOICES, default="off",
                    help="thinking effort for reasoning models. 'off' disables "
                         "it (this task is copying sentences, not reasoning); "
                         "'default' sends nothing and lets the model decide")
    ap.add_argument("--provider", default=None,
                    help="pin every call to one OpenRouter provider slug "
                         "(e.g. deepinfra). Fallbacks are turned off, so the "
                         "call fails rather than silently going elsewhere. "
                         "Use this whenever you are comparing runs")
    ap.add_argument("--in-dir", default=str(SOURCE_DIR),
                    help="folder of .txt/.md files to process when no single "
                         "article is given (default: %s)" % SOURCE_DIR.name)
    ap.add_argument("--out-dir", default=str(OUTPUT_DIR),
                    help="folder the batch writes into, one JSON per article "
                         "per model per run (default: %s)" % OUTPUT_DIR.name)
    ap.add_argument("--out", default=None,
                    help="single-file mode only: output directory")
    ap.add_argument("--check-models", action="store_true",
                    help="report which models support strict JSON schemas, "
                         "and what they cost, then exit")
    args = ap.parse_args()

    if args.check_models:
        sys.exit(0 if check_models(args.models) else 1)

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        sys.exit("Set OPENROUTER_API_KEY (see .env.example)")

    prompt = PROMPT_PATH.read_text(encoding="utf-8")

    # No single article named: process the whole folder.
    if not args.article:
        run_batch(Path(args.in_dir), Path(args.out_dir), prompt, api_key, args)
        return

    article_path = Path(args.article)
    if not article_path.exists():
        sys.exit("No such file: %s" % article_path)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.out) if args.out else RUNS_DIR / (
        "%s__%s" % (article_path.stem, stamp))
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        all_runs = process_article(article_path, prompt, api_key, out_dir, args)
    except ValueError as exc:
        sys.exit("%s: %s" % (article_path, exc))

    summarise(all_runs)
    print("\nPer-run JSON written to %s" % out_dir)


if __name__ == "__main__":
    main()
