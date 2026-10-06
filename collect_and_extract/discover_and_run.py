"""
discover_and_run.py

Automated discovery layer in front of collect_and_extract.py's existing,
already-hardened fetch/extract/save pipeline. Run this manually whenever you
want a fresh batch (e.g. before assembling a quarterly insights report)
instead of typing URLs in by hand.

Three independent discovery sources feed the same downstream extraction:
    - discover_aihw.py            AIHW's internal report-search API
    - discover_abs_articles.py    ABS's "Articles" listing (Health topic)
    - discover_abs_statistics.py  ABS's release calendar, filtered to Health

Each source tracks its own "since" cursor in manifest.json (under the
"_discovery" key, which is never a real URL so it can't collide with a
per-article manifest entry) - one source failing or running never moves
another source's cursor, and a cursor is only advanced after that source's
discovery call succeeds, so a transient failure can't silently skip
whatever was published during the outage.

Discovery only ever produces a list of URLs. Everything after that -
fetching, extraction, change-detection, saving - is the exact same
process_source() this project already uses for manually-entered URLs, so
none of that logic is duplicated or forked here.

**Revalidation (Fix 1) runs after discovery, every call.** Discovery's
only signal for "check this URL again" is the source itself bumping a
release/update date on its own listing - if AIHW or ABS silently edits a
page's content without that, discovery will never surface that URL again,
ever (its own date comparison stays "not newer than my cursor" forever).
Revalidation closes that gap by re-checking a small batch of already-saved
URLs every run, picked oldest-checked-first by `last_revalidated_at`,
independent of anything the source flagged. It's the same
fetch/extract/hash/compare `process_source()` already does for discovered
URLs - just triggered by "we haven't personally looked in a while"
instead of "the source said something's new". See the README's
"Revalidation" section for the full reasoning.

Usage:
    python discover_and_run.py
    python discover_and_run.py --lookback-days 30
    python discover_and_run.py --force-refresh
    python discover_and_run.py --revalidate-batch-size 50
    python discover_and_run.py --revalidate-batch-size 0   # disable revalidation for this run
    python discover_and_run.py --quiet                     # only print new/changed/failed, plus the summary
"""

from __future__ import annotations

import argparse
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

import discover_abs_articles
import discover_abs_statistics
import discover_aihw
from collect_and_extract import SOURCE_DOMAINS, is_valid_domain, load_manifest, process_source, save_manifest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_DAYS = 90
DEFAULT_REVALIDATE_BATCH_SIZE = 25
_DISCOVERY_KEY = "_discovery"
_EPOCH = datetime.fromtimestamp(0, tz=timezone.utc)


def _get_cursor(manifest: dict, source: str) -> str | None:
    return manifest.get(_DISCOVERY_KEY, {}).get("last_run_at", {}).get(source)


def _set_cursor(manifest: dict, source: str, when: datetime) -> None:
    manifest.setdefault(_DISCOVERY_KEY, {}).setdefault("last_run_at", {})[source] = when.isoformat()


def _resolve_since(manifest: dict, source: str, lookback_days: int) -> datetime:
    raw = _get_cursor(manifest, source)
    if raw is not None:
        return datetime.fromisoformat(raw)

    since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    logger.info(
        "BOOTSTRAP [%s]: no previous discovery run recorded - defaulting `since` to %s (%d days ago)",
        source, since.isoformat(), lookback_days,
    )
    return since


def _discover_source(label: str, run_fn, since: datetime) -> list | None:
    """Run one discover_new_reports() call, returning None (not raising) on failure.

    None is the caller's signal to skip processing AND leave that source's
    cursor untouched - a failed discovery run must never advance `since`
    past reports it never actually saw.

    Deliberately prints nothing of its own before or after the call: each
    discover_*.py module already logs its own "found N new ... since ..."
    line at INFO on success, fully self-identifying (it names itself
    "AIHW discovery"/"ABS articles discovery"/"ABS statistics discovery"),
    so a second, more generic line here would only restate the same fact a
    second time per source.
    """
    logger.debug("[%s] Checking for new reports since %s...", label, since.isoformat())
    try:
        reports = run_fn(since=since)
    except Exception as exc:  # noqa: BLE001 - each module raises its own error type
        logger.error("[%s] Discovery failed, skipping this source without updating its cursor: %s", label, exc)
        return None
    return reports


def _valid_urls(label: str, source_label: str, reports: list) -> list[str]:
    """Drop (and warn about) any discovered URL that fails our own domain check.

    Defensive only - every discover_*.py module already builds URLs off its
    own site's base URL, so this should never actually trigger. Cheap
    insurance against process_source() ever being handed an off-domain URL.
    """
    urls = []
    for report in reports:
        if not is_valid_domain(report.url, source_label):
            logger.warning("[%s] Dropping unexpected off-domain URL: %s", label, report.url)
            continue
        urls.append(report.url)
    return urls


def _source_label_for_url(url: str) -> str | None:
    """AIHW or ABS, by domain - None for anything that matches neither.

    Manifest entries have no explicit "source" field (the dict key is just
    the canonical URL), so revalidation re-derives which source_label to
    hand to `process_source()` the same way `is_valid_domain()` already
    validates URLs elsewhere in this project, rather than inventing a
    second way to tell AIHW and ABS URLs apart.
    """
    for label in SOURCE_DOMAINS:
        if is_valid_domain(url, label):
            return label
    return None


def _last_revalidated_at(entry: dict) -> datetime:
    """Sort key for revalidation: oldest first, never-revalidated first of all.

    Falls back to `first_seen_at` for an entry saved before
    `last_revalidated_at` existed, and to the Unix epoch if even that's
    missing or unparseable - either way, an entry with no real record of
    ever being checked sorts as the oldest possible, so it's first in line
    rather than silently never getting picked.
    """
    raw = entry.get("last_revalidated_at") or entry.get("first_seen_at")
    if not raw:
        return _EPOCH
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return _EPOCH


def _select_revalidation_batch(manifest: dict, batch_size: int) -> dict[str, list[str]]:
    """Pick the `batch_size` tracked URLs least recently revalidated, grouped by source.

    This is Fix 1: the only mechanism that forces an already-saved URL
    back through fetch/extract/hash/compare when the source itself never
    flags it as updated - discovery alone can never do this, since its
    only test is comparing the source's own release/update date against
    our cursor (see the README's "Revalidation" section). Oldest-first by
    `last_revalidated_at` so every tracked URL eventually gets re-checked,
    not just whichever ones happen to be discovered again.
    """
    candidates = [(url, entry) for url, entry in manifest.items() if url != _DISCOVERY_KEY]
    candidates.sort(key=lambda pair: _last_revalidated_at(pair[1]))

    batch: dict[str, list[str]] = {"AIHW": [], "ABS": []}
    for url, _entry in candidates[:batch_size]:
        label = _source_label_for_url(url)
        if label is None:
            logger.warning("Revalidation: dropping URL with unrecognized domain: %s", url)
            continue
        batch[label].append(url)
    return batch


def run(lookback_days: int = DEFAULT_LOOKBACK_DAYS, force_refresh: bool = False,
        revalidate_batch_size: int = DEFAULT_REVALIDATE_BATCH_SIZE, quiet: bool = False) -> None:
    logger.info("--- Health Insight Engine: automated discovery run starting ---")
    manifest = load_manifest()
    run_started_at = datetime.now(timezone.utc)
    tracked = sum(1 for key in manifest if key != _DISCOVERY_KEY)
    logger.info("Loaded manifest: %d URL(s) already tracked", tracked)

    sources = [
        ("aihw", "AIHW", discover_aihw.discover_new_reports),
        ("abs_articles", "ABS", discover_abs_articles.discover_new_reports),
        ("abs_statistics", "ABS", discover_abs_statistics.discover_new_reports),
    ]

    aihw_urls: list[str] = []
    abs_urls: list[str] = []
    succeeded: list[str] = []

    for cursor_key, output_label, run_fn in sources:
        since = _resolve_since(manifest, cursor_key, lookback_days)
        reports = _discover_source(cursor_key, run_fn, since)
        if reports is None:
            continue

        succeeded.append(cursor_key)
        urls = _valid_urls(cursor_key, output_label, reports)
        (aihw_urls if output_label == "AIHW" else abs_urls).extend(urls)

    logger.info("--- Discovery summary ---")
    print(f"  AIHW: {len(aihw_urls)} URL(s)")
    print(f"  ABS: {len(abs_urls)} URL(s)")

    counts: Counter = Counter()
    notable: list[str] = []
    if aihw_urls:
        result = process_source("AIHW", aihw_urls, manifest, force_refresh, phase="newly discovered", quiet=quiet)
        counts += result.counts
        notable += result.notable
    if abs_urls:
        result = process_source("ABS", abs_urls, manifest, force_refresh, phase="newly discovered", quiet=quiet)
        counts += result.counts
        notable += result.notable

    revalidated: Counter = Counter()
    if revalidate_batch_size > 0:
        # Selected after discovery's process_source() calls above, not
        # before - a URL just discovered/re-checked this run already has
        # last_revalidated_at stamped to now (record_content() does this
        # unconditionally), so it naturally sorts to the back of the queue
        # and won't be picked again in the same run.
        batch = _select_revalidation_batch(manifest, revalidate_batch_size)
        batch_total = sum(len(urls) for urls in batch.values())
        logger.info("--- Revalidation ---")
        print(f"  Re-checking {batch_total} previously-saved URL(s), oldest-checked-first")
        for label, urls in batch.items():
            if urls:
                # force_refresh=True regardless of the --force-refresh flag
                # above: skipping the actual re-fetch here would defeat the
                # entire point of revalidation (see README's "Revalidation").
                result = process_source(
                    label, urls, manifest, force_refresh=True, phase="revalidation", quiet=quiet
                )
                revalidated += result.counts
                notable += result.notable

    for cursor_key in succeeded:
        _set_cursor(manifest, cursor_key, run_started_at)

    try:
        save_manifest(manifest)
    except OSError as e:
        logger.warning("could not save manifest (%s). Extracted files were saved, but discovery cursors were not.", e)

    elapsed = (datetime.now(timezone.utc) - run_started_at).total_seconds()
    logger.info("--- Run summary ---")
    print(
        f"  Discovered + saved: new {counts['new']}, changed {counts['changed']}, "
        f"unchanged {counts['unchanged']}, cached {counts['cached']}, failed {counts['failed']}"
    )
    print(
        f"  Revalidated: changed {revalidated['changed']}, unchanged {revalidated['unchanged']}, "
        f"failed {revalidated['failed']}"
    )
    if notable:
        print("  Changed/new this run:")
        for line in notable:
            print(f"    {line}")
    print(f"  Elapsed: {elapsed:.1f}s")
    logger.info("--- Done ---")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS,
        help=f"Only used the first time a source has no recorded cursor (default: {DEFAULT_LOOKBACK_DAYS})",
    )
    parser.add_argument(
        "--force-refresh", action="store_true",
        help="Re-fetch and re-extract even URLs already saved with an unchanged hash",
    )
    parser.add_argument(
        "--revalidate-batch-size", type=int, default=DEFAULT_REVALIDATE_BATCH_SIZE,
        help=(
            "How many already-saved URLs to re-check per run, oldest-checked-first, "
            f"regardless of whether the source flagged them as updated (default: "
            f"{DEFAULT_REVALIDATE_BATCH_SIZE}; 0 disables revalidation for this run)"
        ),
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help=(
            "Suppress the per-URL line for anything unchanged (a cache-hit skip, or a "
            "re-checked URL whose content came back the same) - new/changed URLs and any "
            "warning or failure still print, as does the run summary at the end"
        ),
    )
    args = parser.parse_args()
    run(
        lookback_days=args.lookback_days,
        force_refresh=args.force_refresh,
        revalidate_batch_size=args.revalidate_batch_size,
        quiet=args.quiet,
    )


if __name__ == "__main__":
    main()
