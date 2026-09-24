from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from markdownify import markdownify
from pypdf import PdfReader


VERSION = "0.2.2"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/153.0 Safari/537.36"
)

ORG_BY_HOST = {
    "www.abs.gov.au": "Australian Bureau of Statistics",
    "abs.gov.au": "Australian Bureau of Statistics",
    "www.aihw.gov.au": "Australian Institute of Health and Welfare",
    "aihw.gov.au": "Australian Institute of Health and Welfare",
}

AIHW_HOSTS = {"aihw.gov.au", "www.aihw.gov.au"}
ABS_HOSTS = {"abs.gov.au", "www.abs.gov.au"}


# ---------------------------------------------------------------------------
# Basic utilities
# ---------------------------------------------------------------------------

def write_json(path: Path, data: dict) -> None:
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def org_from_url(url: str) -> str:
    return ORG_BY_HOST.get((urlparse(url).hostname or "").lower(), "")


def meta(soup: BeautifulSoup, **attrs) -> str:
    tag = soup.find("meta", attrs=attrs)
    return (tag.get("content") or "").strip() if tag and tag.get("content") else ""


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------

def extract_dates_from_jsonld(soup: BeautifulSoup):
    published = None
    modified = None

    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text(" ", strip=True)
        if not raw:
            continue

        try:
            obj = json.loads(raw)
        except Exception:
            continue

        items = obj if isinstance(obj, list) else [obj]
        expanded = []

        for item in items:
            if isinstance(item, dict) and isinstance(item.get("@graph"), list):
                expanded.extend(item["@graph"])
            else:
                expanded.append(item)

        for item in expanded:
            if isinstance(item, dict):
                published = published or item.get("datePublished")
                modified = modified or item.get("dateModified")

    return published, modified


def normalise_abs_issued_date(value: str | None) -> str | None:
    """
    ABS commonly exposes:
        Fri, 28/08/2026 - 11:30

    Return YYYY-MM-DD where possible.
    If parsing fails, preserve the original value rather than guessing.
    """
    if not value:
        return None

    value = value.strip()

    patterns = [
        "%a, %d/%m/%Y - %H:%M",
        "%d/%m/%Y",
        "%Y-%m-%d",
    ]

    for pattern in patterns:
        try:
            return datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            pass

    return value


def normalise_human_date(value: str | None) -> str | None:
    if not value:
        return None

    value = value.strip()
    patterns = [
        "%d %b %Y",
        "%d %B %Y",
        "%d/%m/%Y",
        "%Y-%m-%d",
    ]

    for pattern in patterns:
        try:
            return datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            pass

    return value


def extract_aihw_visible_metadata(soup: BeautifulSoup) -> dict:
    """
    AIHW pages can expose a top-level "Last updated: 30 Jul 2026" label and,
    in some editions, a separate visible version marker such as
    "Last updated 21/07/2026 v252.0".

    Treat these as update/version metadata, not as a publication date.
    """
    text = soup.get_text(" ", strip=True)

    top_updated = None
    version_date = None
    visible_version = None

    m = re.search(
        r"Last\s+updated\s*:\s*(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})",
        text,
        flags=re.IGNORECASE,
    )
    if m:
        top_updated = normalise_human_date(m.group(1))

    m = re.search(
        r"Last\s+updated\s+(\d{1,2}/\d{1,2}/\d{4})\s+(v[0-9A-Za-z._-]+)",
        text,
        flags=re.IGNORECASE,
    )
    if m:
        version_date = normalise_human_date(m.group(1))
        visible_version = m.group(2)

    return {
        "visible_last_updated_date": top_updated,
        "visible_version_date": version_date,
        "visible_version": visible_version,
    }


def html_metadata(html: bytes, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    host = host_of(url)

    h1 = soup.find("h1")

    title = (
        meta(soup, property="og:title")
        or (h1.get_text(" ", strip=True) if h1 else "")
        or (soup.title.get_text(" ", strip=True) if soup.title else "")
    )

    published_jsonld, modified_jsonld = extract_dates_from_jsonld(soup)

    explicit_published = (
        meta(soup, property="article:published_time")
        or published_jsonld
    )
    generic_date = meta(soup, name="date")

    # AIHW's visible page date is an update date, not automatically a
    # publication date. Avoid copying a generic date into publication_date.
    if host in AIHW_HOSTS:
        published = explicit_published or None
    else:
        published = explicit_published or generic_date or None

    modified = (
        meta(soup, property="article:modified_time")
        or meta(soup, name="dateModified")
        or modified_jsonld
        or None
    )

    organisation = meta(soup, property="og:site_name") or org_from_url(url)
    reference_period = None
    visible_version_date = None
    visible_version = None

    if host in ABS_HOSTS:
        abs_reference_period = meta(soup, name="dcterms.temporal")
        abs_issued = meta(soup, name="dcterms.issued")

        if abs_reference_period:
            reference_period = abs_reference_period

        if abs_issued:
            published = normalise_abs_issued_date(abs_issued)

    if host in AIHW_HOSTS:
        aihw_visible = extract_aihw_visible_metadata(soup)
        modified = aihw_visible.get("visible_last_updated_date") or modified
        visible_version_date = aihw_visible.get("visible_version_date")
        visible_version = aihw_visible.get("visible_version")

    return {
        "title": title,
        "organisation": organisation,
        "publication_date": published or None,
        "last_updated_date": modified or None,
        "reference_period": reference_period,
        "visible_version_date": visible_version_date,
        "visible_version": visible_version,
    }


# ---------------------------------------------------------------------------
# Static HTML extraction
# ---------------------------------------------------------------------------

def absolutise(root, base_url: str) -> None:
    for tag in root.find_all(href=True):
        tag["href"] = urljoin(base_url, tag["href"])

    for tag in root.find_all(src=True):
        tag["src"] = urljoin(base_url, tag["src"])


def select_content_root(soup: BeautifulSoup):
    """
    Prefer source/article-content containers so navigation, breadcrumbs,
    citation controls and footer/service links are excluded where possible.
    """
    return (
        soup.find(id="page-content")
        or soup.find(id="report-page-content")
        or soup.find("article")
        or soup.find("main")
        or soup.body
        or soup
    )


def figure_heading_labels(root) -> list[str]:
    labels = []
    seen = set()

    for tag in root.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "strong"]):
        text = tag.get_text(" ", strip=True)
        m = re.match(r"^(Figure\s+\d+\s*:[^\n]{0,250})", text, flags=re.IGNORECASE)
        if not m:
            continue
        label = re.sub(r"\s+", " ", m.group(1)).strip()
        key = label.lower()
        if key not in seen:
            seen.add(key)
            labels.append(label)

    return labels


def detect_interactive_content(root, base_url: str) -> dict:
    """
    Detect rich/interactive evidence before scripts/forms/buttons are removed.

    The detector intentionally errs on the side of flagging evidence for
    review. It does not claim that every flagged item is material.
    """
    items = []
    seen = set()

    def add(kind: str, locator: str = "", label: str = "", url: str = ""):
        key = (kind, locator, label, url)
        if key in seen:
            return
        seen.add(key)
        items.append({
            "kind": kind,
            "locator": locator,
            "label": label,
            "url": url,
        })

    for i, iframe in enumerate(root.find_all("iframe"), 1):
        src = urljoin(base_url, iframe.get("src") or "") if iframe.get("src") else ""
        add(
            "iframe",
            locator=f"iframe[{i}]",
            label=(iframe.get("title") or iframe.get("aria-label") or "").strip(),
            url=src,
        )

    # Custom dashboard/viz elements and common rich-content classes/ids.
    for tag in root.find_all(True):
        name = (tag.name or "").lower()
        attrs_text = " ".join(
            [name]
            + [str(tag.get("id") or "")]
            + [" ".join(tag.get("class") or [])]
            + [" ".join(str(k) for k in tag.attrs.keys())]
        ).lower()

        if any(token in attrs_text for token in ("tableau", "powerbi", "visualisation", "visualization")):
            label = (tag.get("title") or tag.get("aria-label") or tag.get_text(" ", strip=True)[:220]).strip()
            add("rich_visual", locator=name, label=label)

    # Downloadable or switchable table evidence.
    for link in root.find_all("a", href=True):
        label = link.get_text(" ", strip=True)
        low = (label + " " + link.get("href", "")).lower()
        if "download table" in low or ".csv" in low or re.search(r"\bcsv\b", low):
            add(
                "table_download",
                locator="a",
                label=label,
                url=urljoin(base_url, link["href"]),
            )

    labels = figure_heading_labels(root)

    # Script hints are useful when visualisation markup is injected later.
    script_hints = 0
    for script in root.find_all("script"):
        raw = (script.get("src") or "") + " " + (script.string or "")
        if re.search(r"tableau|visuali[sz]ation|chart|embed", raw, flags=re.IGNORECASE):
            script_hints += 1

    host = host_of(base_url)
    # AIHW report pages with Figure headings are rendered as a precaution because
    # important values/notes can live in client-side visualisations even when the
    # static HTML does not expose a clean iframe/table marker.
    capture_required = bool(items) or (host in AIHW_HOSTS and bool(labels))

    return {
        "detected": bool(items or labels),
        "capture_required": capture_required,
        "detected_items": items,
        "detected_item_count": len(items),
        "detected_figure_headings": labels,
        "detected_figure_heading_count": len(labels),
        "script_visualisation_hints": script_hints,
    }


def html_to_md(html: bytes, url: str):
    soup = BeautifulSoup(html, "html.parser")
    root = select_content_root(soup)

    container = (
        f"#{root.get('id')}"
        if getattr(root, "get", None) and root.get("id")
        else getattr(root, "name", "fallback")
    )

    interactive = detect_interactive_content(root, url)

    # Remove only clearly non-content elements within the selected root.
    for name in ("script", "style", "noscript", "form", "button", "svg"):
        for tag in root.find_all(name):
            tag.decompose()

    # Remove obvious page-service blocks if they exist inside the selected content.
    removable_selectors = [
        ".abs-actions",
        ".field-key-statistics + .print-links",
        ".back-to-top",
    ]
    for selector in removable_selectors:
        for tag in root.select(selector):
            tag.decompose()

    absolutise(root, url)

    notes = {
        "content_container": container,
        "detected_tables": len(root.find_all("table")),
        "detected_html_figures": len(root.find_all("figure")),
        "detected_figure_headings": interactive["detected_figure_heading_count"],
        "detected_images": len(root.find_all("img")),
        "detected_interactive_items": interactive["detected_item_count"],
        "capture_script_version": VERSION,
    }

    md = markdownify(
        str(root),
        heading_style="ATX",
        bullets="-",
    )

    # Conservative whitespace cleanup only.
    md = re.sub(r"\n{4,}", "\n\n\n", md).strip()

    return md, notes, interactive


# ---------------------------------------------------------------------------
# Browser-rendered interactive capture
# ---------------------------------------------------------------------------

def _clean_lines(text: str, limit: int = 30000) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    out = "\n".join(lines)
    return out[:limit]


def _figure_chunks(text: str) -> list[dict]:
    """Extract rendered text chunks beginning with a Figure N heading."""
    clean = _clean_lines(text, limit=120000)
    if not clean:
        return []

    matches = list(re.finditer(r"(?im)^(Figure\s+\d+\s*:[^\n]*)$", clean))
    chunks = []

    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else min(len(clean), start + 16000)
        chunk = clean[start:end].strip()
        chunks.append({
            "label": match.group(1).strip(),
            "text": chunk[:16000],
        })

    return chunks


def capture_rendered_interactive_content(url: str, timeout: int) -> dict:
    """
    Render the page in Chromium and preserve accessible evidence exposed by
    interactive frames/controls/tables.

    This function NEVER estimates values from chart geometry. If a chart does
    not expose machine-readable/accessibility text, it remains unresolved and
    requires human verification.
    """
    result = {
        "attempted": True,
        "status": "UNRESOLVED",
        "browser": "playwright_chromium",
        "error": None,
        "frames": [],
        "rendered_figure_chunks": [],
        "download_candidates": [],
    }

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        result["status"] = "DEPENDENCY_MISSING"
        result["error"] = (
            "Playwright is not available. Install requirements and run "
            "'py -m playwright install chromium'. "
            f"Original error: {exc}"
        )
        return result

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(
                viewport={"width": 1600, "height": 1400},
                user_agent=USER_AGENT,
            )

            try:
                page.goto(url, wait_until="networkidle", timeout=timeout * 1000)
            except Exception:
                # Some analytics/dashboard pages never reach network-idle.
                page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)

            # Trigger lazy-loaded figures/iframes.
            page.evaluate(
                """
                async () => {
                  const step = Math.max(600, Math.floor(window.innerHeight * 0.8));
                  for (let y = 0; y < document.body.scrollHeight; y += step) {
                    window.scrollTo(0, y);
                    await new Promise(r => setTimeout(r, 150));
                  }
                  window.scrollTo(0, 0);
                }
                """
            )
            page.wait_for_timeout(2500)

            try:
                body_text = page.locator("body").inner_text(timeout=5000)
                result["rendered_figure_chunks"] = _figure_chunks(body_text)
            except Exception:
                pass

            # Capture direct download links exposed in the rendered main page.
            try:
                links = page.locator("a").evaluate_all(
                    """
                    els => els.map(a => ({
                      text: (a.innerText || a.getAttribute('aria-label') || '').trim(),
                      href: a.href || ''
                    }))
                    """
                )
                for item in links:
                    low = f"{item.get('text','')} {item.get('href','')}".lower()
                    if "download table" in low or ".csv" in low or re.search(r"\bcsv\b", low):
                        result["download_candidates"].append(item)
            except Exception:
                pass

            # Capture all child frames that expose meaningful accessible text.
            # Playwright can inspect cross-origin frame DOM through the browser
            # automation context; ordinary requests/BeautifulSoup cannot.
            for idx, frame in enumerate(page.frames):
                if frame == page.main_frame:
                    continue

                record = {
                    "index": idx,
                    "url": frame.url,
                    "name": frame.name,
                    "accessible_text": "",
                    "controls": [],
                    "tables_markdown": [],
                    "download_candidates": [],
                    "resolved": False,
                    "error": None,
                }

                try:
                    text = frame.locator("body").inner_text(timeout=6000)
                    record["accessible_text"] = _clean_lines(text, limit=35000)
                except Exception as exc:
                    record["error"] = f"body text unavailable: {exc}"

                # Visible controls help preserve selected measure/state labels.
                try:
                    controls = frame.locator(
                        "button, [role='button'], [role='tab'], [role='option'], select"
                    ).evaluate_all(
                        """
                        els => els.map(el => ({
                          text: (el.innerText || el.getAttribute('aria-label') || el.getAttribute('title') || '').trim(),
                          selected: el.getAttribute('aria-selected'),
                          pressed: el.getAttribute('aria-pressed'),
                          value: el.value || ''
                        })).filter(x => x.text || x.value)
                        """
                    )
                    record["controls"] = controls[:200]
                except Exception:
                    pass

                # Preserve explicit HTML tables where the rendered frame exposes them.
                try:
                    table_htmls = frame.locator("table").evaluate_all(
                        "els => els.map(el => el.outerHTML)"
                    )
                    for table_html in table_htmls[:25]:
                        table_md = markdownify(table_html, heading_style="ATX", bullets="-").strip()
                        if table_md:
                            record["tables_markdown"].append(table_md[:20000])
                except Exception:
                    pass

                # Preserve downloadable table/CSV links where exposed.
                try:
                    links = frame.locator("a").evaluate_all(
                        """
                        els => els.map(a => ({
                          text: (a.innerText || a.getAttribute('aria-label') || '').trim(),
                          href: a.href || ''
                        }))
                        """
                    )
                    for item in links:
                        low = f"{item.get('text','')} {item.get('href','')}".lower()
                        if "download table" in low or ".csv" in low or re.search(r"\bcsv\b", low):
                            record["download_candidates"].append(item)
                            result["download_candidates"].append(item)
                except Exception:
                    pass

                record["resolved"] = bool(
                    record["accessible_text"]
                    or record["controls"]
                    or record["tables_markdown"]
                    or record["download_candidates"]
                )

                # Ignore unrelated analytics/cookie frames. A frame is relevant when
                # its URL looks like a visualisation/report frame or its exposed text
                # contains evidence-oriented labels.
                frame_url_low = (record["url"] or "").lower()
                frame_text_low = (record["accessible_text"] or "").lower()
                relevant = (
                    any(token in frame_url_low for token in (
                        "tableau", "powerbi", "visual", "viz", "chart", "aihw", "report"
                    ))
                    or bool(record["tables_markdown"])
                    or bool(record["download_candidates"])
                    or (
                        len(frame_text_low) >= 80
                        and any(token in frame_text_low for token in (
                            "figure", "measure", "persons", "women", "men",
                            "rank", "daly", "download table", "year"
                        ))
                    )
                )

                # Keep relevant frames with evidence or an error, so failures remain auditable.
                if relevant and (record["resolved"] or record["error"]):
                    result["frames"].append(record)

            browser.close()

    except Exception as exc:
        result["status"] = "ERROR"
        result["error"] = str(exc)
        return result

    resolved = sum(1 for f in result["frames"] if f.get("resolved"))
    unresolved = sum(1 for f in result["frames"] if not f.get("resolved"))

    if resolved and not unresolved:
        render_status = "COMPLETE"
    elif resolved:
        render_status = "PARTIAL"
    elif result["rendered_figure_chunks"] or result["download_candidates"]:
        # Useful rendered evidence exists, but no child frame was machine-readable.
        render_status = "PARTIAL"
    else:
        render_status = "UNRESOLVED"

    # Rendering successfully is not the same as preserving all material chart
    # evidence. Accessibility text can omit graphical marks (for example, a
    # displayed ranked list). Treat frames that expose only controls/text, but
    # no explicit table/download, as requiring human evidence verification.
    resolved_frames = [f for f in result["frames"] if f.get("resolved")]
    frames_without_machine_data = [
        f for f in resolved_frames
        if not (f.get("tables_markdown") or f.get("download_candidates"))
    ]

    if render_status != "COMPLETE":
        evidence_status = "PARTIAL" if (resolved_frames or result["rendered_figure_chunks"] or result["download_candidates"]) else "UNRESOLVED"
        evidence_reason = "Interactive rendering was not fully resolved."
    elif frames_without_machine_data:
        evidence_status = "PARTIAL"
        evidence_reason = (
            "At least one interactive frame rendered successfully but exposed no "
            "machine-readable table or download. Accessibility text may omit "
            "material graphical marks, so human verification is required."
        )
    else:
        evidence_status = "COMPLETE"
        evidence_reason = None

    # Keep status for compatibility, but make it the conservative overall
    # evidence status. render_status separately records browser success.
    result["render_status"] = render_status
    result["evidence_status"] = evidence_status
    result["evidence_reason"] = evidence_reason
    result["status"] = evidence_status

    return result


def interactive_capture_markdown(browser_capture: dict) -> str:
    if not browser_capture.get("attempted"):
        return ""

    lines = [
        "## Captured Interactive Evidence",
        "",
        "> This section contains rendered/accessibility evidence captured from interactive content.",
        "> Numerical values are preserved only when explicitly exposed by the page or visualisation.",
        "> No values are estimated from bar heights, line positions, colours, or other chart geometry.",
        "",
        f"**Interactive render status:** {browser_capture.get('render_status', browser_capture.get('status', 'UNRESOLVED'))}",
        f"**Interactive evidence status:** {browser_capture.get('evidence_status', browser_capture.get('status', 'UNRESOLVED'))}",
        "",
    ]

    if browser_capture.get("error"):
        lines += [
            f"**Capture error:** {browser_capture['error']}",
            "",
        ]

    chunks = browser_capture.get("rendered_figure_chunks") or []
    if chunks:
        lines += ["### Rendered figure sections", ""]
        for chunk in chunks:
            lines += [
                f"#### {chunk.get('label', 'Figure')}",
                "",
                chunk.get("text", "").strip(),
                "",
            ]

    frames = browser_capture.get("frames") or []
    for n, frame in enumerate(frames, 1):
        lines += [
            f"### Interactive frame {n}",
            "",
            f"- **Frame URL:** {frame.get('url') or 'Not exposed'}",
            f"- **Resolved:** {'Yes' if frame.get('resolved') else 'No'}",
        ]

        if frame.get("error"):
            lines.append(f"- **Frame error:** {frame['error']}")

        controls = frame.get("controls") or []
        if controls:
            lines += ["", "#### Exposed controls / state labels", ""]
            for control in controls[:80]:
                bits = []
                if control.get("text"):
                    bits.append(control["text"])
                if control.get("value"):
                    bits.append(f"value={control['value']}")
                if control.get("selected") is not None:
                    bits.append(f"selected={control['selected']}")
                if control.get("pressed") is not None:
                    bits.append(f"pressed={control['pressed']}")
                lines.append(f"- {' | '.join(bits)}")

        tables = frame.get("tables_markdown") or []
        if tables:
            lines += ["", "#### Exposed tables", ""]
            for table in tables:
                lines += [table, ""]

        text = frame.get("accessible_text") or ""
        if text:
            lines += [
                "",
                "#### Accessible visualisation text",
                "",
                text,
                "",
            ]

        downloads = frame.get("download_candidates") or []
        if downloads:
            lines += ["", "#### Downloadable table candidates", ""]
            for item in downloads:
                label = item.get("text") or "Download"
                href = item.get("href") or ""
                lines.append(f"- [{label}]({href})")
            lines.append("")

    # De-duplicate top-level candidates by URL.
    candidates = []
    seen = set()
    for item in browser_capture.get("download_candidates") or []:
        href = item.get("href") or ""
        if not href or href in seen:
            continue
        seen.add(href)
        candidates.append(item)

    if candidates:
        lines += ["### Downloadable table candidates", ""]
        for item in candidates:
            lines.append(f"- [{item.get('text') or 'Download'}]({item.get('href')})")
        lines.append("")

    evidence_status = browser_capture.get("evidence_status", browser_capture.get("status", "UNRESOLVED"))
    if evidence_status != "COMPLETE":
        lines += [
            "### Human verification required for interactive content",
            "",
            browser_capture.get("evidence_reason")
            or "At least part of the interactive evidence could not be confirmed as fully machine-readable.",
            "Review the rendered source manually before freezing. Do not infer missing chart values.",
            "",
        ]

    return "\n".join(lines).strip()


def build_interactive_metadata(static_detection: dict, browser_capture: dict | None) -> dict:
    if not static_detection.get("capture_required"):
        return {
            "detected": static_detection.get("detected", False),
            "capture_required": False,
            "detected_item_count": static_detection.get("detected_item_count", 0),
            "detected_figure_heading_count": static_detection.get("detected_figure_heading_count", 0),
            "browser_capture_attempted": False,
            "render_status": "NOT_REQUIRED",
            "evidence_status": "NOT_REQUIRED",
            "status": "NOT_REQUIRED",
            "resolved_frame_count": 0,
            "unresolved_frame_count": 0,
            "human_review_required": False,
        }

    browser_capture = browser_capture or {}
    frames = browser_capture.get("frames") or []
    render_status = browser_capture.get(
        "render_status", browser_capture.get("status", "UNRESOLVED")
    )
    evidence_status = browser_capture.get(
        "evidence_status", browser_capture.get("status", "UNRESOLVED")
    )

    return {
        "detected": True,
        "capture_required": True,
        "detected_item_count": static_detection.get("detected_item_count", 0),
        "detected_figure_heading_count": static_detection.get("detected_figure_heading_count", 0),
        "browser_capture_attempted": bool(browser_capture.get("attempted")),
        "render_status": render_status,
        "evidence_status": evidence_status,
        # status remains the conservative overall status for compatibility.
        "status": evidence_status,
        "resolved_frame_count": sum(1 for f in frames if f.get("resolved")),
        "unresolved_frame_count": sum(1 for f in frames if not f.get("resolved")),
        "rendered_figure_chunk_count": len(browser_capture.get("rendered_figure_chunks") or []),
        "download_candidate_count": len(browser_capture.get("download_candidates") or []),
        "error": browser_capture.get("error"),
        "evidence_reason": browser_capture.get("evidence_reason"),
        "human_review_required": evidence_status != "COMPLETE",
    }


# ---------------------------------------------------------------------------
# PDF extraction
# ---------------------------------------------------------------------------

def pdf_to_md(path: Path):
    reader = PdfReader(str(path))
    pages = []

    for i, page in enumerate(reader.pages, 1):
        pages.append(
            f"## PDF Page {i}\n\n{(page.extract_text() or '').strip()}"
        )

    return "\n\n".join(pages).strip(), {
        "pdf_pages": len(reader.pages),
        "warning": (
            "Check tables, charts, multi-column layout, and image-only text manually."
        ),
        "capture_script_version": VERSION,
    }


# ---------------------------------------------------------------------------
# Draft generation
# ---------------------------------------------------------------------------

def build_test_input(metadata: dict, content: str, notes: dict) -> str:
    rows = [
        "# Frozen Source Snapshot — DRAFT FOR HUMAN VERIFICATION",
        "",
        "> **Status: NOT FROZEN.** Verify this file against the preserved raw source",
        "> before running `freeze_source.py`.",
        "",
        "## Source Metadata",
        "",
        f"- **Case ID:** {metadata.get('case_id', '')}",
        f"- **Title:** {metadata.get('title') or 'Not automatically identified'}",
        f"- **Organisation:** {metadata.get('organisation') or 'Not automatically identified'}",
        f"- **Source URL:** {metadata.get('source_url', '')}",
        f"- **Reference period:** {metadata.get('reference_period') or 'Not automatically identified'}",
        f"- **Retrieval date:** {metadata.get('retrieval_date', '')}",
        f"- **Retrieved at:** {metadata.get('retrieved_at', '')}",
        f"- **Publication date:** {metadata.get('publication_date') or 'Not automatically identified'}",
        f"- **Last updated date:** {metadata.get('last_updated_date') or 'Not automatically identified'}",
        f"- **Visible version date:** {metadata.get('visible_version_date') or 'Not automatically identified'}",
        f"- **Visible version:** {metadata.get('visible_version') or 'Not automatically identified'}",
        f"- **Capture method:** {metadata.get('capture_method', '')}",
        f"- **Raw source SHA-256:** {metadata.get('raw_source_sha256', '')}",
        "",
        "## Capture Notes",
        "",
    ]

    rows += [
        f"- **{key.replace('_', ' ').title()}:** {value}"
        for key, value in notes.items()
    ]

    interactive = metadata.get("interactive_content") or {}
    if interactive:
        rows += [
            f"- **Interactive Capture Required:** {interactive.get('capture_required', False)}",
            f"- **Interactive Render Status:** {interactive.get('render_status', interactive.get('status', 'NOT_REQUIRED'))}",
            f"- **Interactive Evidence Status:** {interactive.get('evidence_status', interactive.get('status', 'NOT_REQUIRED'))}",
            f"- **Interactive Human Review Required:** {interactive.get('human_review_required', False)}",
        ]

    rows += [
        "",
        "## Publication Content",
        "",
        content,
        "",
        "## Human Verification Checklist",
        "",
        "- [ ] Material text is present.",
        "- [ ] Important tables and quantitative values are preserved.",
        "- [ ] Important chart/figure information is represented.",
        "- [ ] Interactive figures/charts were checked; no chart values were inferred from geometry.",
        "- [ ] Dates, reference periods, populations and caveats are preserved.",
        "- [ ] Navigation/citation/footer/service UI does not materially contaminate the content.",
        "- [ ] No summary or relevance/priority judgement was inserted.",
        "",
    ]

    return "\n".join(rows)


def ensure_intake_empty(source_dir: Path) -> None:
    allowed = {"source_metadata.json"}

    extras = [
        p.name
        for p in source_dir.iterdir()
        if p.is_file() and p.name not in allowed
    ]

    if extras:
        raise FileExistsError(
            "Source area already contains captured/generated files: "
            + ", ".join(extras)
            + ". Move/delete only the previous intake artifacts before recapturing."
        )


# ---------------------------------------------------------------------------
# Capture entry points
# ---------------------------------------------------------------------------

def capture_url(case: Path, url: str, timeout: int) -> None:
    source = case / "source"
    ensure_intake_empty(source)

    metadata_path = source / "source_metadata.json"
    m = load_json(metadata_path)

    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
        allow_redirects=True,
    )
    response.raise_for_status()

    raw = response.content
    content_type = (response.headers.get("Content-Type") or "").lower()
    is_pdf = "application/pdf" in content_type or raw[:5] == b"%PDF-"

    now = datetime.now().astimezone()
    browser_capture = None

    if is_pdf:
        raw_path = source / "source_snapshot.pdf"
        raw_path.write_bytes(raw)

        content, notes = pdf_to_md(raw_path)

        extracted = {
            "title": m.get("title", ""),
            "organisation": m.get("organisation", "") or org_from_url(url),
            "publication_date": m.get("publication_date"),
            "last_updated_date": m.get("last_updated_date"),
            "reference_period": m.get("reference_period"),
            "visible_version_date": m.get("visible_version_date"),
            "visible_version": m.get("visible_version"),
        }

        interactive_meta = {
            "detected": False,
            "capture_required": False,
            "status": "NOT_APPLICABLE_PDF",
            "human_review_required": False,
        }

        method = "url_download_pdf_then_pypdf_text_extraction"

    else:
        raw_path = source / "source_snapshot.html"
        raw_path.write_bytes(raw)

        extracted = html_metadata(raw, response.url)
        content, notes, interactive_detection = html_to_md(raw, response.url)

        if interactive_detection.get("capture_required"):
            browser_capture = capture_rendered_interactive_content(
                response.url,
                timeout=timeout,
            )
            rendered_md = interactive_capture_markdown(browser_capture)
            if rendered_md:
                content = content.rstrip() + "\n\n" + rendered_md

        interactive_meta = build_interactive_metadata(
            interactive_detection,
            browser_capture,
        )

        method = (
            "url_download_html_then_markdown_conversion"
            + (
                "_plus_browser_interactive_capture"
                if interactive_detection.get("capture_required")
                else ""
            )
        )

    m.update(
        {
            "source_url": url,
            "final_url": response.url,
            "retrieval_date": now.date().isoformat(),
            "retrieved_at": now.isoformat(),
            "title": extracted.get("title") or m.get("title", ""),
            "organisation": extracted.get("organisation") or m.get("organisation", ""),
            "publication_date": extracted.get("publication_date") or m.get("publication_date"),
            "last_updated_date": extracted.get("last_updated_date") or m.get("last_updated_date"),
            "reference_period": extracted.get("reference_period") or m.get("reference_period"),
            "visible_version_date": extracted.get("visible_version_date") or m.get("visible_version_date"),
            "visible_version": extracted.get("visible_version") or m.get("visible_version"),
            "capture_method": method,
            "capture_script_version": VERSION,
            "raw_source_filename": raw_path.name,
            "raw_source_sha256": sha256_bytes(raw),
            "test_input_draft_filename": "Test_Input_draft.md",
            "human_verified": False,
            "http_content_type": content_type,
            "http_last_modified": response.headers.get("Last-Modified"),
            "http_etag": response.headers.get("ETag"),
            "interactive_content": interactive_meta,
        }
    )

    write_json(metadata_path, m)

    draft = source / "Test_Input_draft.md"
    draft.write_text(
        build_test_input(m, content, notes),
        encoding="utf-8",
    )

    print("SOURCE CAPTURED — HUMAN VERIFICATION REQUIRED")
    print(f"Capture script version: {VERSION}")
    print(f"Raw source: {raw_path.resolve()}")
    print(f"Test_Input draft: {draft.resolve()}")
    print(f"Metadata: {metadata_path.resolve()}")
    print(f"Raw source SHA-256: {m['raw_source_sha256']}")
    print()
    print("Detected metadata:")
    print(f"  Title: {m.get('title') or 'Not identified'}")
    print(f"  Organisation: {m.get('organisation') or 'Not identified'}")
    print(f"  Reference period: {m.get('reference_period') or 'Not identified'}")
    print(f"  Publication date: {m.get('publication_date') or 'Not identified'}")
    print(f"  Last updated date: {m.get('last_updated_date') or 'Not identified'}")
    print(f"  Visible version: {m.get('visible_version') or 'Not identified'}")
    print()
    print("Interactive capture:")
    print(f"  Required: {interactive_meta.get('capture_required', False)}")
    print(f"  Render status: {interactive_meta.get('render_status', interactive_meta.get('status', 'NOT_REQUIRED'))}")
    print(f"  Evidence status: {interactive_meta.get('evidence_status', interactive_meta.get('status', 'NOT_REQUIRED'))}")
    print(f"  Human review required: {interactive_meta.get('human_review_required', False)}")
    print()
    print("NEXT: verify Test_Input_draft.md against the raw/rendered source.")
    print("If correct, run freeze_source.py with --approve.")
    if interactive_meta.get("human_review_required"):
        print(
            "Interactive evidence is not fully machine-readable. "
            "freeze_source.py will block the freeze unless the gap is resolved "
            "or explicitly acknowledged after manual verification."
        )


def capture_file(case: Path, file_path: Path, source_url: str) -> None:
    source = case / "source"
    ensure_intake_empty(source)

    metadata_path = source / "source_metadata.json"
    m = load_json(metadata_path)

    if not file_path.is_file():
        raise FileNotFoundError(file_path)

    suffix = file_path.suffix.lower()
    raw_path = source / f"source_snapshot{suffix}"

    shutil.copyfile(file_path, raw_path)
    raw = raw_path.read_bytes()

    now = datetime.now().astimezone()
    interactive_meta = {
        "detected": False,
        "capture_required": False,
        "status": "NOT_REQUIRED",
        "human_review_required": False,
    }

    if suffix == ".pdf" or raw[:5] == b"%PDF-":
        content, notes = pdf_to_md(raw_path)
        method = "local_pdf_copy_then_pypdf_text_extraction"
        interactive_meta["status"] = "NOT_APPLICABLE_PDF"

    elif suffix in {".html", ".htm"}:
        extracted = html_metadata(raw, source_url)

        m["title"] = extracted.get("title") or m.get("title", "")
        m["organisation"] = extracted.get("organisation") or m.get("organisation", "")
        m["publication_date"] = extracted.get("publication_date") or m.get("publication_date")
        m["last_updated_date"] = extracted.get("last_updated_date") or m.get("last_updated_date")
        m["reference_period"] = extracted.get("reference_period") or m.get("reference_period")
        m["visible_version_date"] = extracted.get("visible_version_date") or m.get("visible_version_date")
        m["visible_version"] = extracted.get("visible_version") or m.get("visible_version")

        content, notes, interactive_detection = html_to_md(raw, source_url)
        interactive_meta = build_interactive_metadata(interactive_detection, None)

        if interactive_detection.get("capture_required"):
            interactive_meta["status"] = "UNRESOLVED_LOCAL_HTML"
            interactive_meta["human_review_required"] = True
            content = content.rstrip() + "\n\n" + interactive_capture_markdown({
                "attempted": True,
                "status": "UNRESOLVED_LOCAL_HTML",
                "error": (
                    "Interactive content was detected in a local HTML copy. "
                    "Use --url for browser-rendered interactive capture, or verify/supplement manually."
                ),
                "frames": [],
                "rendered_figure_chunks": [],
                "download_candidates": [],
            })

        method = "local_html_copy_then_markdown_conversion"

    elif suffix in {".md", ".txt"}:
        content = raw_path.read_text(encoding="utf-8", errors="replace")
        notes = {
            "local_text_source": True,
            "capture_script_version": VERSION,
        }
        method = "local_text_copy"

    else:
        raise ValueError("Supported local formats: PDF, HTML, MD, TXT.")

    m.update(
        {
            "source_url": source_url or m.get("source_url", ""),
            "retrieval_date": now.date().isoformat(),
            "retrieved_at": now.isoformat(),
            "organisation": m.get("organisation", "") or org_from_url(source_url),
            "capture_method": method,
            "capture_script_version": VERSION,
            "raw_source_filename": raw_path.name,
            "raw_source_sha256": sha256_bytes(raw),
            "test_input_draft_filename": "Test_Input_draft.md",
            "human_verified": False,
            "interactive_content": interactive_meta,
        }
    )

    write_json(metadata_path, m)

    draft = source / "Test_Input_draft.md"
    draft.write_text(
        build_test_input(m, content, notes),
        encoding="utf-8",
    )

    print("LOCAL SOURCE CAPTURED — HUMAN VERIFICATION REQUIRED")
    print(f"Capture script version: {VERSION}")
    print(f"Raw source: {raw_path.resolve()}")
    print(f"Test_Input draft: {draft.resolve()}")
    print(f"Metadata: {metadata_path.resolve()}")
    print(f"Interactive status: {interactive_meta.get('status', 'NOT_REQUIRED')}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description=f"Capture a public source and generate a Test_Input draft (v{VERSION})."
    )

    parser.add_argument("case_dir", type=Path)

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--url")
    group.add_argument("--file", type=Path)

    parser.add_argument("--source-url", default="")
    parser.add_argument("--timeout", type=int, default=45)

    args = parser.parse_args()

    if not args.case_dir.is_dir():
        print("ERROR: case directory not found", file=sys.stderr)
        return 1

    if not (args.case_dir / "source" / "source_metadata.json").is_file():
        print("ERROR: source_metadata.json missing", file=sys.stderr)
        return 1

    try:
        if args.url:
            capture_url(args.case_dir, args.url, args.timeout)
        else:
            capture_file(args.case_dir, args.file, args.source_url)

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
