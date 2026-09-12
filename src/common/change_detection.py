"""Detect whether fetched article content is new, changed, or unchanged.

Primary signal: a SHA-256 hash of the *normalised extracted text*. This is the
source of truth for "did the content actually change?".

Secondary signal: the stated update/release date parsed from the page. It is
used to (a) cross-check the hash verdict and (b) stamp the briefing with a
human-readable "when". It is never trusted on its own.

State is persisted as one JSON file to start with (lightweight, per the
proposal). The public interface (ChangeStore.process) stays the same if you
later swap the JSON for a database.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup


# --------------------------------------------------------------------------- #
# Text normalisation + hashing (the primary signal)
# --------------------------------------------------------------------------- #

_WHITESPACE_RE = re.compile(r"\s+")


def normalise_text(text: str) -> str:
    """Canonicalise text so trivial differences don't register as changes.

    Unicode NFC (visually identical characters hash the same), all whitespace
    runs collapsed to single spaces, ends stripped.
    """
    text = unicodedata.normalize("NFC", text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


def content_hash(text: str) -> str:
    """SHA-256 hex digest of the normalised text."""
    return hashlib.sha256(normalise_text(text).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Stated-date extraction (the secondary signal) - SOURCE AWARE
# --------------------------------------------------------------------------- #
# AIHW web reports:      "Last updated: 12 Dec 2024"
# ABS modern releases:   "Release date and time" then "25/06/2024 11:30am AEST"
#                        (NB: NOT "Reference period", which is data coverage)
# ABS legacy AUSSTATS:   "This page last updated 22 November 2010" /
#                        "Released at 11:30 AM (CANBERRA TIME) 10/12/2002"

_AIHW_LAST_UPDATED = re.compile(
    r"Last updated:?\s*(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})", re.IGNORECASE
)
_ABS_RELEASE = re.compile(
    r"Release date and time\s+(\d{1,2}/\d{1,2}/\d{4})", re.IGNORECASE
)
_ABS_LEGACY_UPDATED = re.compile(
    r"This page last updated\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})", re.IGNORECASE
)
_ABS_LEGACY_RELEASED = re.compile(
    r"Released at .*?(\d{1,2}/\d{1,2}/\d{4})", re.IGNORECASE
)

_DATE_FORMATS = ("%d %b %Y", "%d %B %Y", "%d/%m/%Y")


def _parse_date(raw: str) -> Optional[str]:
    """Return an ISO date (YYYY-MM-DD) for a raw date string, or None."""
    raw = raw.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _visible_text(html: str) -> str:
    """Visible page text with newlines, so labels split across elements match."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return soup.get_text(separator="\n")


def extract_stated_date(
    html: str, source: Optional[str] = None
) -> tuple[Optional[str], Optional[str]]:
    """Return ``(iso_date, raw_string)`` for the page's stated date.

    Prefers the label used by ``source`` ("AIHW" / "ABS") but falls back to the
    other known patterns so an unexpected layout still has a chance.
    """
    text = _visible_text(html)

    by_source = {
        "AIHW": [_AIHW_LAST_UPDATED],
        "ABS": [_ABS_RELEASE, _ABS_LEGACY_UPDATED, _ABS_LEGACY_RELEASED],
    }
    ordered = list(by_source.get((source or "").upper(), []))
    for pattern in (_AIHW_LAST_UPDATED, _ABS_RELEASE,
                    _ABS_LEGACY_UPDATED, _ABS_LEGACY_RELEASED):
        if pattern not in ordered:
            ordered.append(pattern)

    for pattern in ordered:
        match = pattern.search(text)
        if match:
            raw = match.group(1).strip()
            return _parse_date(raw), raw
    return None, None


# --------------------------------------------------------------------------- #
# Change detection: combine the two signals
# --------------------------------------------------------------------------- #

@dataclass
class ChangeResult:
    url: str
    status: str                       # "new" | "changed" | "unchanged"
    current_hash: str
    previous_hash: Optional[str]
    stated_date: Optional[str]
    previous_stated_date: Optional[str]
    date_changed: Optional[bool]
    similarity: Optional[float]       # 0..1 vs previous version (None if new)
    note: str

    @property
    def should_process(self) -> bool:
        """True when there is genuinely new content worth sending downstream."""
        return self.status in ("new", "changed")


class ChangeStore:
    """Lightweight JSON-backed store of the last seen version of each page."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._data: dict = (
            json.loads(self.path.read_text(encoding="utf-8"))
            if self.path.exists() else {}
        )

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def evaluate(self, page: dict) -> ChangeResult:
        """Compare a freshly fetched page against the stored baseline.

        ``page`` is the dict returned by ``fetch.fetch_article`` (must include
        ``url`` and ``body_text``; ``stated_date`` if available).
        Does NOT mutate the store - call ``commit`` to update the baseline.
        """
        url = page["url"]
        body = page.get("body_text", "") or ""
        new_hash = content_hash(body)
        stated = page.get("stated_date")

        record = self._data.get(url)
        if record is None:
            return ChangeResult(
                url, "new", new_hash, None, stated, None, None, None,
                "First time this page has been seen.",
            )

        prev_hash = record.get("hash")
        prev_date = record.get("stated_date")
        date_changed = (stated != prev_date) if (stated or prev_date) else None

        if new_hash == prev_hash:
            note = "Content identical to last run."
            if date_changed:
                note = ("Stated date moved but content is identical "
                        "(cosmetic republish) - suppressed.")
            return ChangeResult(url, "unchanged", new_hash, prev_hash, stated,
                                prev_date, date_changed, 1.0, note)

        similarity = difflib.SequenceMatcher(
            None,
            normalise_text(record.get("body_text", "")),
            normalise_text(body),
        ).ratio()
        if date_changed:
            note = "Content changed and stated date moved - high-confidence update."
        else:
            note = ("Content changed but stated date did not move "
                    "(silent edit, or ABS URL reuse).")
        return ChangeResult(url, "changed", new_hash, prev_hash, stated,
                            prev_date, date_changed, similarity, note)

    def commit(self, page: dict, result: ChangeResult) -> None:
        """Record the current version as the new baseline for this URL."""
        self._data[page["url"]] = {
            "hash": result.current_hash,
            "stated_date": page.get("stated_date"),
            "fetch_date": page.get("fetch_date"),
            "title": page.get("title"),
            "report_id": page.get("report_id"),
            "page_slug": page.get("page_slug"),
            "body_text": page.get("body_text", ""),  # kept for next diff + provenance
        }

    def process(self, page: dict, commit: bool = True) -> ChangeResult:
        """Evaluate a page and (by default) update the baseline in one call."""
        result = self.evaluate(page)
        if commit:
            self.commit(page, result)
        return result
