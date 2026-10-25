"""
AIHW report discovery via the site's internal search API.

Endpoint found via browser DevTools (Network tab -> XHR -> "reports"):
    POST https://www.aihw.gov.au/api/search/reports

This is a JSON API, not an HTML listing page - no per-page scraping
fragility, and it returns structured fields (release date, report type,
topic, external-report flag) that an HTML listing wouldn't give us for
free.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator

import requests

logger = logging.getLogger(__name__)

AIHW_BASE_URL = "https://www.aihw.gov.au"
AIHW_SEARCH_API = f"{AIHW_BASE_URL}/api/search/reports"

# Between successive page requests to the search API - polite pacing, same
# value collect_and_extract.py already uses between report-page fetches.
_REQUEST_DELAY = 0.3

# AIHW's API sits behind Cloudflare, which blocks requests whose headers
# don't resemble a real browser tab (default requests.post sends
# "User-Agent: python-requests/x.x", an easy bot signal -> 403).
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json;charset=UTF-8",
    "Referer": f"{AIHW_BASE_URL}/reports-data/latest-reports",
    "Origin": AIHW_BASE_URL,
}

# currentNodeId=37 with filterByCurrentTopic=False returns AIHW's entire
# report archive - intentional, not a placeholder. No per-topic node-ID
# mapping is needed for full-archive discovery.
_BASE_PAYLOAD = {
    "itemsPerPage": 20,
    "filterByCurrentTopic": False,
    "orderByColumn": "",
    "currentNodeId": 37,
    "excludeHiddenReports": True,
    "includeRelatedTopics": False,
    "searchReleases": True,
    "truncateSummary": True,
}


@dataclass
class DiscoveredReport:
    url: str
    node_guid: str
    title: str
    release_date: datetime
    report_type: str
    topic: str
    is_external: bool


class AihwDiscoveryError(Exception):
    """Raised when the AIHW search API can't be reached or returns something unexpected."""


def _fetch_page(page: int, items_per_page: int = 20) -> dict:
    payload = {**_BASE_PAYLOAD, "page": page, "itemsPerPage": items_per_page}
    try:
        response = requests.post(AIHW_SEARCH_API, json=payload, headers=_HEADERS, timeout=30)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise AihwDiscoveryError(f"AIHW search API request failed on page {page}: {exc}") from exc

    try:
        return response.json()
    except ValueError as exc:
        raise AihwDiscoveryError(f"AIHW search API returned non-JSON on page {page}") from exc


def _flatten_items(data: dict) -> Iterator[dict]:
    for group in data.get("groups", []):
        yield from group.get("items", [])


def discover_new_reports(
    since: datetime,
    include_external: bool = False,
    max_pages: int = 50,
    items_per_page: int = 20,
) -> list[DiscoveredReport]:
    """
    Return every AIHW report released after `since`.

    NOTE on ordering: results are only *roughly* newest-first. Live testing
    showed release dates within a page can be locally out of order by a
    week or two (e.g. 18 Jun, then 4 Jun, then back to 17 Jun) - likely a
    topic/relevance clustering effect, not a pure chronological sort.
    Because of this we do NOT stop on the first old item seen (that risks
    skipping a genuinely new report sitting just after a stray older one).
    Instead we scan every item on a page and only stop paging once an
    entire page yields nothing new. Do not "optimize" this back to a
    first-old-item break - that risks silently missing reports near a page
    boundary.

    External reports (hosted off aihw.gov.au) are excluded by default,
    consistent with collect_and_extract.py's own domain validation, which
    only ever accepts aihw.gov.au/abs.gov.au URLs.
    """
    if since.tzinfo is None:
        raise ValueError("`since` must be timezone-aware (compare in UTC)")

    discovered: list[DiscoveredReport] = []

    for page in range(1, max_pages + 1):
        if page > 1:
            time.sleep(_REQUEST_DELAY)
        data = _fetch_page(page, items_per_page=items_per_page)
        items = list(_flatten_items(data))
        if not items:
            logger.debug("AIHW discovery: no more items at page %d, stopping", page)
            break

        found_new_this_page = False
        for item in items:
            release_date = datetime.fromisoformat(item["releaseDate"]).replace(tzinfo=timezone.utc)

            if release_date <= since:
                continue

            found_new_this_page = True

            if item["isExternalReport"] and not include_external:
                continue

            discovered.append(
                DiscoveredReport(
                    url=AIHW_BASE_URL + item["reportUrl"],
                    node_guid=item["nodeGUID"],
                    title=item["titleDisplay"],
                    release_date=release_date,
                    report_type=item["reportTypeName"],
                    topic=item["reportSourceName"],
                    is_external=item["isExternalReport"],
                )
            )

        if not found_new_this_page:
            logger.debug("AIHW discovery: page %d had nothing newer than %s, stopping", page, since)
            break
    else:
        logger.warning("AIHW discovery: hit max_pages=%d without exhausting new items", max_pages)

    logger.info("AIHW discovery: found %d new report(s) since %s", len(discovered), since)
    return discovered
