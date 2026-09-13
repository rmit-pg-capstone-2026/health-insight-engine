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

HERE = Path(__file__).parent
PROMPT_PATH = HERE / "prompt.md"
RUNS_DIR = HERE / "runs"
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
                    "Extract findings from the article below.\n\n"
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

def normalise(text):
    """Collapse whitespace and unify quote characters for comparison."""
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("–", "-").replace("—", "-")
    text = text.replace(" ", " ")
    return re.sub(r"\s+", " ", text).strip().lower()


def verify_quotes(result, article_text):
    """Check every quote appears verbatim in the source. This is the
    traceability check - it is what makes week 12's evaluation automatic.

    connection_quote gets the same treatment: it is the model's evidence that
    the article itself links this finding to care. If it cannot be found in
    the source, the model invented the connection."""
    haystack = normalise(article_text)
    checks = []
    for i, finding in enumerate(result.get("findings", [])):
        quote = finding.get("quote", "")
        link = finding.get("connection_quote", "")
        checks.append({
            "index": i,
            "topic": finding.get("topic"),
            "found_in_source": normalise(quote) in haystack if quote else False,
            "connection_found_in_source": (
                normalise(link) in haystack if link else False),
            "connection_same_as_quote": normalise(link) == normalise(quote),
            "quote": quote,
            "connection_quote": link,
        })
    return checks


def check_measures(result):
    """The prompt says value_text must contain a digit. Words like "highest"
    in a measure field mean the model is stuffing prose into a numeric slot."""
    bad = []
    for i, finding in enumerate(result.get("findings", [])):
        for m in finding.get("measures", []):
            text = m.get("value_text") or ""
            if not any(ch.isdigit() for ch in text):
                bad.append({"index": i, "topic": finding.get("topic"),
                            "value_text": text})
    return bad


def validate_schema(result):
    if jsonschema is None:
        return ["jsonschema not installed - skipped structural validation"]
    validator = jsonschema.Draft7Validator(EXTRACTION_SCHEMA)
    return [
        "%s: %s" % ("/".join(str(p) for p in e.path) or "(root)", e.message)
        for e in validator.iter_errors(result)
    ]


# ------------------------------------------------------------- run + report

def run_model(model, article_text, prompt, api_key, repeats, out_dir,
              temperature, reasoning, provider):
    runs = []
    for n in range(1, repeats + 1):
        print("  run %d/%d" % (n, repeats))
        result, meta = call_model(model, article_text, prompt, api_key,
                                  temperature, reasoning, provider)

        record = {"model": model, "run": n, "meta": meta, "result": result}
        if result is not None:
            record["schema_errors"] = validate_schema(result)
            record["quote_checks"] = verify_quotes(result, article_text)
            record["bad_measures"] = check_measures(result)

        path = out_dir / ("%s__run%d.json" % (model.replace("/", "_"), n))
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False))
        runs.append(record)

        if result is None:
            print("    FAILED: %s" % meta.get("error"))
        else:
            bad_quotes = sum(
                1 for c in record["quote_checks"] if not c["found_in_source"]
            )
            bad_links = sum(
                1 for c in record["quote_checks"]
                if not c["connection_found_in_source"]
            )
            reasoning_note = ""
            if meta.get("reasoning_tokens"):
                reasoning_note = ", %s reasoning tokens" % meta["reasoning_tokens"]
            print("    %d findings, %d schema errors, %d unverified quotes, "
                  "%d invented connections, %d non-numeric measures%s"
                  % (len(result.get("findings", [])),
                     len(record["schema_errors"]), bad_quotes, bad_links,
                     len(record["bad_measures"]), reasoning_note))
    return runs


def stability(runs):
    """How much do repeat runs agree? Compares the set of quotes each run
    returned - if the model is picking different findings each time, the
    granularity rule in the prompt is not landing."""
    ok = [r for r in runs if r["result"] is not None]
    if len(ok) < 2:
        return None
    sets = [
        {normalise(f.get("quote", "")) for f in r["result"].get("findings", [])}
        for r in ok
    ]
    counts = [len(s) for s in sets]
    common = set.intersection(*sets)
    union = set.union(*sets)
    return {
        "findings_per_run": counts,
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
            invented = sum(
                1 for c in r["quote_checks"]
                if not c["connection_found_in_source"]
            )
            own_link = sum(
                1 for c in r["quote_checks"]
                if not c["connection_same_as_quote"]
            )
            print("  run %d: %2d findings | %d schema err | %d unverified"
                  " quotes | %d invented links (%d needed a separate link) |"
                  " %d bad measures | %ss | %s | %s"
                  % (r["run"], len(r["result"].get("findings", [])),
                     len(r["schema_errors"]), unverified, invented, own_link,
                     len(r.get("bad_measures", [])),
                     meta.get("seconds"),
                     meta.get("provider") or "?",
                     ("$%.5f" % cost) if cost is not None else "cost n/a"))
        s = stability(runs)
        if s:
            print("  stability: %s findings per run, %d quote(s) in every run "
                  "of %d seen, agreement %s"
                  % (s["findings_per_run"], s["in_every_run"],
                     s["seen_at_least_once"], s["agreement"]))
    if total_cost:
        print("\nTotal cost this session: $%.5f" % total_cost)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("article", nargs="?",
                    help="path to a .txt file holding the article")
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
    ap.add_argument("--out", default=None, help="output directory")
    ap.add_argument("--check-models", action="store_true",
                    help="report which models support strict JSON schemas, "
                         "and what they cost, then exit")
    args = ap.parse_args()

    if args.check_models:
        sys.exit(0 if check_models(args.models) else 1)

    if not args.article:
        ap.error("an article file is required (or use --check-models)")

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        sys.exit("Set OPENROUTER_API_KEY (see .env.example)")

    article_path = Path(args.article)
    if not article_path.exists():
        sys.exit("No such file: %s" % article_path)
    article_text = article_path.read_text(encoding="utf-8")
    if not article_text.strip():
        sys.exit("Article file is empty: %s" % article_path)

    prompt = PROMPT_PATH.read_text(encoding="utf-8")

    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.out) if args.out else RUNS_DIR / (
        "%s__%s" % (article_path.stem, stamp))
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Article:   %s (%d characters)" % (article_path, len(article_text)))
    print("Reasoning: %s" % args.reasoning)
    print("Provider:  %s" % (args.provider or "whatever OpenRouter picks"))
    print("Output:    %s\n" % out_dir)

    all_runs = {}
    for model in args.models:
        print(model)
        all_runs[model] = run_model(
            model, article_text, prompt, api_key,
            args.repeats, out_dir, args.temperature, args.reasoning,
            args.provider,
        )

    summarise(all_runs)
    print("\nPer-run JSON written to %s" % out_dir)


if __name__ == "__main__":
    main()
