"""
Finds AIHW and ABS pages published (or updated) recently, for the collect stage.

Uses the three finders in collect_and_extract/ unchanged:
    discover_aihw.py            AIHW's report search (every AIHW topic)
    discover_abs_articles.py    ABS articles, Health only
    discover_abs_statistics.py  ABS release calendar, Health only

and applies the filters from collect_settings.json:
    discovery_days     how far back to look, every run (a fixed window, wider
                       than the gap between runs, so one missed run loses nothing)
    skip_hub_pages     skip AIHW landing pages one level deep, e.g. /mental-health.
                       They merge many sub-pages into one document, and their
                       date moves whenever anything under them changes.
    aihw_skip_topics   AIHW topics to ignore, matched on the topic in the address:
                       /reports/<topic>/... or /<topic>/...

A finder that fails is reported and skipped; the others still run.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "collect_and_extract"))

import discover_abs_articles  # noqa: E402
import discover_abs_statistics  # noqa: E402
import discover_aihw  # noqa: E402

FINDERS = (
    ("aihw", "AIHW", discover_aihw.discover_new_reports),
    ("abs_articles", "ABS", discover_abs_articles.discover_new_reports),
    ("abs_statistics", "ABS", discover_abs_statistics.discover_new_reports),
)


def _path_parts(url: str) -> list:
    return [p for p in urlparse(url).path.split("/") if p]


def topic_of(url: str) -> str | None:
    """The topic in an address: /reports/<topic>/..., /statistics/<theme>/<topic>/...,
    or else the first part: /<topic>/..."""
    parts = _path_parts(url)
    if not parts:
        return None
    if parts[0] == "reports" and len(parts) > 1:
        return parts[1]
    if parts[0] == "statistics" and len(parts) > 2:
        return parts[2]
    return parts[0]


def is_hub(url: str) -> bool:
    """An AIHW landing page: one level deep, e.g. https://www.aihw.gov.au/mental-health"""
    return len(_path_parts(url)) == 1


def find(settings: dict, now: datetime | None = None) -> dict:
    """Ask every finder for pages dated within the window, then filter.

    Returns {"since": "...",
             "found":   [{"url", "agency", "title", "release_date", "topic"}, ...],
             "skipped": [{"url", "reason"}, ...],
             "errors":  {"aihw": "...", ...}}      only finders that failed
    """
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=int(settings.get("discovery_days", 14)))
    skip_topics = {t.lower() for t in settings.get("aihw_skip_topics", [])}
    skip_hubs = settings.get("skip_hub_pages", True)

    found, skipped, errors, seen = [], [], {}, set()
    for key, agency, finder in FINDERS:
        try:
            reports = finder(since=since)
        except Exception as exc:  # one finder down must not stop the others
            errors[key] = str(exc)[:500]
            continue
        for r in reports:
            if r.url in seen:
                continue
            seen.add(r.url)
            topic = topic_of(r.url)
            if agency == "AIHW" and skip_hubs and is_hub(r.url):
                skipped.append({"url": r.url, "reason": "hub page"})
                continue
            if agency == "AIHW" and topic and topic.lower() in skip_topics:
                skipped.append({"url": r.url, "reason": f"skipped topic: {topic}"})
                continue
            found.append({"url": r.url, "agency": agency, "title": r.title,
                          "release_date": r.release_date.date().isoformat(), "topic": topic})
    return {"since": since.date().isoformat(), "found": found, "skipped": skipped,
            "errors": errors}
