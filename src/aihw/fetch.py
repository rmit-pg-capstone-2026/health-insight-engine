"""Fetch and extract AIHW article content.

AIHW publishes reports as HTML pages with no public API, so we download the
page directly and pull out the main article text. trafilatura does the heavy
lifting; BeautifulSoup is a fallback for pages it can't parse.
"""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import trafilatura
import yaml
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Seconds to wait between successive page requests for the same report, so we
# don't hammer AIHW's server. A small random jitter spreads the load.
POLITENESS_DELAY_RANGE = (1.0, 2.0)

# A descriptive User-Agent so AIHW can identify the traffic; some gov.au
# sites reject the default python-requests agent outright.
USER_AGENT = (
    "health-insight-engine/0.1 (RMIT x Medibank capstone; "
    "research use; contact via project maintainers)"
)

REQUEST_TIMEOUT = 30  # seconds


class FetchError(RuntimeError):
    """Raised when an article page can't be downloaded or parsed."""


def _download_html(url: str) -> str:
    """Return the raw HTML for ``url`` or raise :class:`FetchError`."""
    try:
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise FetchError(f"Request to {url} failed: {exc}") from exc

    if response.status_code != 200:
        raise FetchError(
            f"Request to {url} returned HTTP {response.status_code} "
            f"(expected 200)"
        )

    return response.text


def _extract_with_trafilatura(html: str) -> tuple[str | None, str | None]:
    """Return ``(title, body_text)`` from trafilatura, or ``(None, None)``."""
    metadata = trafilatura.extract_metadata(html)
    title = metadata.title if metadata else None

    body_text = trafilatura.extract(
        html,
        include_comments=False,
        include_tables=True,
        favor_precision=True,
    )
    return title, body_text


def _extract_with_beautifulsoup(html: str) -> tuple[str | None, str]:
    """Fallback extraction: main/article region text via BeautifulSoup."""
    soup = BeautifulSoup(html, "html.parser")

    title = None
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    heading = soup.find("h1")
    if heading and heading.get_text(strip=True):
        title = heading.get_text(strip=True)

    # Drop chrome that isn't article content.
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()

    container = soup.find("main") or soup.find("article") or soup.body
    if container is None:
        raise FetchError("Could not locate article content in the page")

    body_text = container.get_text(separator="\n", strip=True)
    return title, body_text


def fetch_article(url: str) -> dict:
    """Download an AIHW article and return its normalised content.

    Parameters
    ----------
    url:
        The AIHW article page to fetch.

    Returns
    -------
    dict
        Keys: ``source``, ``url``, ``title``, ``fetch_date`` (ISO 8601, UTC),
        ``body_text``.

    Raises
    ------
    FetchError
        If the request fails, returns a non-200 status, or no article text
        can be extracted.
    """
    html = _download_html(url)

    title, body_text = _extract_with_trafilatura(html)

    if not body_text:
        title, body_text = _extract_with_beautifulsoup(html)

    if not body_text or not body_text.strip():
        raise FetchError(f"No article text could be extracted from {url}")

    return {
        "source": "AIHW",
        "url": url,
        "title": (title or "").strip() or None,
        "fetch_date": datetime.now(timezone.utc).isoformat(),
        "body_text": body_text.strip(),
    }


def fetch_report(source_config: dict) -> list[dict]:
    """Fetch every sub-page of a multi-page AIHW report.

    Parameters
    ----------
    source_config:
        One entry from ``config/sources.yaml`` describing an AIHW report.
        Must contain ``id``, ``base_url`` and a ``pages`` list of page paths
        relative to ``base_url`` (e.g. ``"contents/key-findings"``).

    Returns
    -------
    list[dict]
        One dict per successfully fetched page. Each is the dict returned by
        :func:`fetch_article`, plus ``report_id`` (the source's ``id``) and
        ``page_slug`` (the page path). Pages that fail to fetch are logged as
        warnings and omitted.
    """
    report_id = source_config["id"]
    base_url = source_config["base_url"].rstrip("/")
    pages = source_config.get("pages", [])

    results: list[dict] = []
    for index, page_slug in enumerate(pages):
        if index > 0:
            time.sleep(random.uniform(*POLITENESS_DELAY_RANGE))

        full_url = f"{base_url}/{page_slug.lstrip('/')}"
        try:
            page = fetch_article(full_url)
        except Exception as exc:  # noqa: BLE001 - one bad page must not abort the report
            logger.warning(
                "Skipping page '%s' of report '%s' (%s): %s",
                page_slug,
                report_id,
                full_url,
                exc,
            )
            continue

        page["report_id"] = report_id
        page["page_slug"] = page_slug
        results.append(page)

    return results


def _load_sources() -> list[dict]:
    """Return the ``sources`` list from config/sources.yaml."""
    config_path = (
        Path(__file__).resolve().parents[2] / "config" / "sources.yaml"
    )
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return config.get("sources", [])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    report_id = "aihw-burden-of-disease-2024"
    source_entry = next(
        (s for s in _load_sources() if s.get("id") == report_id), None
    )
    if source_entry is None:
        raise SystemExit(
            f"Could not find '{report_id}' in config/sources.yaml"
        )

    print(f"Fetching report: {source_entry['name']}\n")
    fetched_pages = fetch_report(source_entry)

    raw_dir = Path(__file__).resolve().parents[2] / "data" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nSuccessfully fetched {len(fetched_pages)} "
          f"of {len(source_entry.get('pages', []))} pages.\n")
    for page in fetched_pages:
        body_text = page["body_text"]
        slug_part = page["page_slug"].replace("/", "-")
        out_path = raw_dir / f"{page['report_id']}__{slug_part}.txt"
        out_path.write_text(body_text, encoding="utf-8")

        print(f"--- {page['page_slug']} ---")
        print(f"body_text length: {len(body_text)} chars")
        print(f"saved to: {out_path}\n")
