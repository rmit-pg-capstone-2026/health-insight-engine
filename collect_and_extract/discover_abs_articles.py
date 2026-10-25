"""
ABS Health-article discovery via the site's server-rendered "related articles" listing.

URL confirmed by direct inspection:
    GET https://www.abs.gov.au/statistics/health/related-articles?page=N

Two other candidate URLs were checked and rejected:
  - abs.gov.au/statistics#health -- just an anchor-jump to topic nav links,
    not a listing at all.
  - abs.gov.au/articles?filter=575 -- the Health filter is applied
    client-side by JavaScript; a plain HTTP fetch ignores it and returns all
    ~764 site-wide articles across every ABS theme, unfiltered. Do NOT use --
    it would silently pull in irrelevant non-health content.

`related-articles` is server-rendered (confirmed via direct fetch, no JS
needed) and pre-scoped to exactly the Health topic (119 articles total,
paginated 20/page, 0-indexed).

This covers ABS's "Articles" content type only - shorter analytical pieces
under /articles/... . It does NOT cover ABS's flagship "Statistics" releases
(under /statistics/<topic>/...), which is a structurally different content
type with its own release-calendar-based discovery mechanism - see
discover_abs_statistics.py. Confirmed by direct check: the "National Study
of Mental Health and Wellbeing, 2020-2022" report we already extract lives
under /statistics/health/mental-health/... and does not appear in this
articles listing at all.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

ABS_BASE_URL = "https://www.abs.gov.au"
ABS_HEALTH_ARTICLES_URL = f"{ABS_BASE_URL}/statistics/health/related-articles"

# Between successive page requests - polite pacing, same value
# collect_and_extract.py already uses between report-page fetches.
_REQUEST_DELAY = 0.3

# No bot-blocking encountered on ABS (unlike AIHW's Cloudflare 403) -- a
# plain fetch works with no special Referer/Origin headers needed. Still
# sending a real User-Agent as standard practice.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


@dataclass
class DiscoveredReport:
    url: str
    title: str
    release_date: datetime
    # ABS's listing HTML has no equivalent of AIHW's per-article nodeGUID or
    # topic tag -- the whole listing is already pre-scoped to Health, so
    # there's nothing to tag. Left as None rather than inventing a value.
    node_guid: str | None = None
    topic: str | None = None


class AbsArticlesDiscoveryError(Exception):
    """Raised when the ABS related-articles page can't be reached or parsed."""


def _fetch_page(page: int) -> str:
    try:
        response = requests.get(
            ABS_HEALTH_ARTICLES_URL,
            params={"page": page},
            headers=_HEADERS,
            timeout=30,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise AbsArticlesDiscoveryError(f"ABS related-articles request failed on page {page}: {exc}") from exc
    return response.text


def _parse_date_text(text: str) -> datetime:
    """Parse ABS's human-readable release date format, e.g. "30 June 2026"."""
    parts = text.strip().split()
    if len(parts) != 3:
        raise AbsArticlesDiscoveryError(f"Unrecognised ABS release date format: {text!r}")

    day_str, month_str, year_str = parts
    month = _MONTHS.get(month_str.lower())
    if month is None:
        raise AbsArticlesDiscoveryError(f"Unrecognised month name in ABS release date: {text!r}")

    return datetime(int(year_str), month, int(day_str), tzinfo=timezone.utc)


def _parse_release_date(row) -> datetime:
    """Parse a listing row's release date.

    Each row's <time> element carries a machine-readable ISO-8601
    `datetime` attribute alongside its human-readable text. The attribute
    is preferred - unambiguous, sidesteps month-name/locale parsing - with
    the text parser as a fallback if it's ever absent.
    """
    time_tag = row.select_one("time")
    if time_tag is None:
        raise AbsArticlesDiscoveryError("Listing row has no <time> element for release date")

    iso = time_tag.get("datetime")
    if iso:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))

    return _parse_date_text(time_tag.get_text(strip=True))


def _parse_rows(html: str) -> Iterator[DiscoveredReport]:
    """Parse repeating `div.views-row` article blocks out of a listing page.

    Each `div.views-row` contains exactly one `<time datetime="...">` and
    one `<a href="/articles/...">` (title + relative link).
    """
    soup = BeautifulSoup(html, "html.parser")
    for row in soup.select("div.views-row"):
        link = row.select_one("a[href]")
        if link is None:
            logger.warning("ABS articles discovery: skipping row with no title link")
            continue

        href = link["href"]
        url = href if href.startswith("http") else ABS_BASE_URL + href

        yield DiscoveredReport(
            url=url,
            title=link.get_text(strip=True),
            release_date=_parse_release_date(row),
        )


def discover_new_reports(
    since: datetime,
    max_pages: int = 20,
    items_per_page: int = 20,
) -> list[DiscoveredReport]:
    """
    Return every ABS Health article released after `since`.

    `items_per_page` exists only for interface parity with discover_aihw.py
    -- ABS's listing page size (20/page) is fixed by the site itself and
    isn't actually configurable through this request, so the argument is
    unused.

    NOTE on ordering: this deliberately reuses the same conservative
    page-level stop logic as discover_aihw.py - scan every item on a page,
    only stop once a full page yields nothing new - rather than trusting
    strict newest-first ordering and breaking on the first old item, even
    though ABS has been observed strictly ordered so far. Not enough
    real-world paging history to be confident that holds everywhere.
    """
    if since.tzinfo is None:
        raise ValueError("`since` must be timezone-aware (compare in UTC)")

    discovered: list[DiscoveredReport] = []

    for page in range(max_pages):
        if page > 0:
            time.sleep(_REQUEST_DELAY)
        html = _fetch_page(page)
        items = list(_parse_rows(html))
        if not items:
            logger.debug("ABS articles discovery: no more items at page %d, stopping", page)
            break

        found_new_this_page = False
        for item in items:
            if item.release_date <= since:
                continue
            found_new_this_page = True
            discovered.append(item)

        if not found_new_this_page:
            logger.debug("ABS articles discovery: page %d had nothing newer than %s, stopping", page, since)
            break
    else:
        logger.warning("ABS articles discovery: hit max_pages=%d without exhausting new items", max_pages)

    logger.info("ABS articles discovery: found %d new article(s) since %s", len(discovered), since)
    return discovered
