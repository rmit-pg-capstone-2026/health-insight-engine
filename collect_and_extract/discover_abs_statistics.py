"""
ABS Health statistics-release discovery via the site's release calendar.

URL confirmed by direct inspection:
    GET https://www.abs.gov.au/release-calendar/latest-releases?page=N

This covers ABS's flagship "Statistics" content type (e.g. "National Study
of Mental Health and Wellbeing, 2020-2022", under
/statistics/health/mental-health/...) - a structurally different content
type from the "Articles" listing covered by discover_abs_articles.py (see
that module's docstring). Confirmed by direct check: that report does not
appear in the articles listing at all, so a second collector is needed to
cover it.

The release calendar is site-wide (all ABS topics: economy, labour,
industry, population, health, ...), server-rendered, and paginated 20/page
(274 entries / 14 pages, newest-first, as of Sept 2026). There is no
topic-filter parameter and no reliable per-row topic tag in the HTML - a
"views-field-field-abs-topic-releases" class exists but its value is the
release's own title text repeated, not a subject category, so it can't be
used as a filter. Instead, each row's title link's href itself carries the
topic in its path (e.g. "/statistics/health/causes-death/..."), confirmed
by direct inspection of the raw HTML, so filtering on that href prefix is
the only concrete filter available.

Rows also mix in "/media-centre/media-releases/..." entries alongside the
actual statistics release pages (e.g. a CPI release is immediately followed
by a "Media Release - CPI rose ..." row) - these are excluded the same way,
by simply not matching the /statistics/health/ prefix.
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
ABS_RELEASE_CALENDAR_URL = f"{ABS_BASE_URL}/release-calendar/latest-releases"
HEALTH_PATH_PREFIX = "/statistics/health/"

# Between successive page requests - polite pacing, same value
# collect_and_extract.py already uses between report-page fetches.
_REQUEST_DELAY = 0.3

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}


@dataclass
class DiscoveredReport:
    url: str
    title: str
    release_date: datetime
    node_guid: str | None = None
    topic: str | None = None


class AbsStatisticsDiscoveryError(Exception):
    """Raised when the ABS release calendar can't be reached or parsed."""


def _fetch_page(page: int) -> str:
    try:
        response = requests.get(
            ABS_RELEASE_CALENDAR_URL,
            params={"page": page},
            headers=_HEADERS,
            timeout=30,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise AbsStatisticsDiscoveryError(f"ABS release calendar request failed on page {page}: {exc}") from exc
    return response.text


def _parse_release_date(row) -> datetime | None:
    """Parse a row's release date from its <time datetime="..."> attribute.

    None if the row has no <time> element at all - happens for a small
    number of non-release rows (e.g. section separators) mixed into the
    calendar; skipped by the caller rather than treated as an error, since
    it's an expected, harmless shape rather than a parsing failure.
    """
    time_tag = row.select_one("time")
    if time_tag is None or not time_tag.get("datetime"):
        return None
    return datetime.fromisoformat(time_tag["datetime"].replace("Z", "+00:00"))


def _parse_row(row) -> DiscoveredReport | None:
    """Parse one already-selected `div.views-row` release block, or None if
    it's not a Health statistics release row.

    Each real release row contains one <time datetime="..."> and one
    <a href="..."> title link (inside an <h3>). A row whose href isn't
    under HEALTH_PATH_PREFIX is dropped here - this is what scopes a
    site-wide calendar down to just Health statistics releases.
    """
    release_date = _parse_release_date(row)
    if release_date is None:
        return None

    link = row.select_one("a[href]")
    if link is None:
        return None

    href = link["href"]
    if not href.startswith(HEALTH_PATH_PREFIX):
        return None

    url = href if href.startswith("http") else ABS_BASE_URL + href
    return DiscoveredReport(url=url, title=link.get_text(strip=True), release_date=release_date)


def discover_new_reports(
    since: datetime,
    max_pages: int = 30,
    items_per_page: int = 20,
) -> list[DiscoveredReport]:
    """
    Return every ABS Health statistics release released after `since`.

    `items_per_page` exists only for interface parity with the other
    discover_*.py modules - the site's page size (20/page) isn't
    configurable through this request, so the argument is unused.

    Unlike discover_abs_articles.py's pre-filtered feed, this page mixes
    every ABS topic together, so the "did this page have anything newer
    than `since`" check (which decides whether to keep paging) is done
    against ALL rows' dates, before the Health-only filter in _parse_row -
    a page can be "exhausted" (nothing newer left) even if every row on it
    happened to be non-Health.
    """
    if since.tzinfo is None:
        raise ValueError("`since` must be timezone-aware (compare in UTC)")

    discovered: list[DiscoveredReport] = []

    for page in range(max_pages):
        if page > 0:
            time.sleep(_REQUEST_DELAY)
        html = _fetch_page(page)
        rows = BeautifulSoup(html, "html.parser").select("div.views-row")
        if not rows:
            logger.debug("ABS statistics discovery: no more items at page %d, stopping", page)
            break

        row_dates = [_parse_release_date(row) for row in rows]
        found_new_this_page = any(d is not None and d > since for d in row_dates)

        if not found_new_this_page:
            logger.debug("ABS statistics discovery: page %d had nothing newer than %s, stopping", page, since)
            break

        for row, row_date in zip(rows, row_dates):
            if row_date is None or row_date <= since:
                continue
            item = _parse_row(row)
            if item is not None:
                discovered.append(item)
    else:
        logger.warning("ABS statistics discovery: hit max_pages=%d without exhausting new items", max_pages)

    logger.info("ABS statistics discovery: found %d new release(s) since %s", len(discovered), since)
    return discovered
