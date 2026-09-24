"""
collect_and_extract.py

Interactive prototype script for the Medibank capstone pipeline.

Flow (matches the sketch):
1. Ask for AIHW-1 and AIHW-2 URLs (mandatory).
2. Keep asking "do you have more?" -> AIHW-3, AIHW-4, ... until the user says no.
3. Repeat the same prompt loop for ABS.
4. Once all URLs are collected, fetch each page, extract the main content as
   Markdown (trafilatura), attach YAML frontmatter, and save one .md file per
   URL into:
       source-extracted-files/AIHW/
       source-extracted-files/ABS/

   AIHW publishes long reports as many pages under a shared
   ".../contents/<section>" path (a sidebar table of contents), rather than
   as HTTP pagination. Giving this script any one section URL from such a
   report (e.g. the "About" landing page) will discover every sibling
   section from that table of contents, fetch them all, and stitch them
   into a single combined markdown file so the whole report is captured
   instead of just the one section.

5. Each page is also checked for a "last updated" <time> tag and for links
   to downloadable data files (.xlsx/.xls/.csv/.zip), recorded in the
   frontmatter. A manifest.json tracks each report's content hash and saved
   file path across runs so the console output can flag whether a report's
   content actually changed since the last run (AIHW reshuffles page layout
   without changing content, so this is hash-based, not URL- or HTML-based).

6. Unless you opt into re-checking, a URL that's already in the manifest
   with its .md file still on disk is skipped after one cheap request
   (no re-fetching/re-combining every section again) - that's what makes
   repeat runs on the same URLs fast.

Usage:
    pip install requests trafilatura --break-system-packages
    python collect_and_extract.py
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urljoin, urlparse

import lxml.html
import requests
import trafilatura

OUTPUT_ROOT = Path("source-extracted-files")
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"
REQUEST_TIMEOUT = 20
USER_AGENT = "MedibankCapstoneBot/0.1 (RMIT WIL project; contact: team)"
CONTENTS_MARKER = "/contents/"
MAX_REPORT_PAGES = 150
REQUEST_DELAY = 0.3
DATA_FILE_EXTENSIONS = ("xlsx", "xls", "csv", "zip")
LAST_UPDATED_CLASS_PREFERENCE = ("f-back-to-top__last-updated__date", "s-report-title__emphasis")
SOURCE_DOMAINS = {"AIHW": "aihw.gov.au", "ABS": "abs.gov.au"}


class ExtractResult(NamedTuple):
    """Everything extracted from one URL, ready to be saved and recorded.

    `body` is the final combined markdown (all sections joined for a
    multi-page report). `pages` lists every section/page URL that went into
    it, in order. `page_details` maps each of those URLs to its own
    {"content_hash", "last_updated"} - used for per-section change tracking
    in the manifest. `canonical_url` is the post-redirect URL, used as the
    stable manifest key regardless of which entry-point URL was given.
    """

    title: str
    body: str
    pages: list[str]
    last_updated: str | None
    data_links: list[str]
    canonical_url: str
    page_details: dict[str, dict]


class FetchError(Exception):
    """Raised when a URL can't be fetched or has no extractable content."""


def is_valid_domain(url: str, source_label: str) -> bool:
    """Check the URL's host matches (or is a subdomain of) the expected agency domain."""
    expected = SOURCE_DOMAINS.get(source_label)
    if not expected:
        return True
    host = urlparse(url).netloc.lower()
    return host == expected or host.endswith(f".{expected}")


def collect_urls(source_label: str) -> list[str]:
    """Interactively collect URLs for one source (e.g. 'AIHW' or 'ABS')."""
    urls: list[str] = []
    expected_domain = SOURCE_DOMAINS.get(source_label, source_label)

    # First two are mandatory, as sketched.
    for i in (1, 2):
        url = input(f"Please enter {source_label}-{i} URL: ").strip()
        while not url or not is_valid_domain(url, source_label):
            if url:
                print(f"  That doesn't look like a {expected_domain} URL. Please try again.")
            url = input(f"  (required) Please enter {source_label}-{i} URL: ").strip()
        urls.append(url)

    # Then keep asking "do you have more?" until the user says no.
    next_index = 3
    while True:
        more = input("Do you have more URLs? (y/n): ").strip().lower()
        if more != "y":
            print("Closing this source's URL list.\n")
            break
        url = input(f"Please enter {source_label}-{next_index} URL: ").strip()
        if not url:
            print("  (empty input ignored)")
        elif not is_valid_domain(url, source_label):
            print(f"  That doesn't look like a {expected_domain} URL - ignored.")
        else:
            urls.append(url)
            next_index += 1

    return urls


def slugify(text: str, max_len: int = 60) -> str:
    """Turn a title into a safe, lowercase filename fragment."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return slug[:max_len] or "untitled"


def fetch_html(url: str) -> tuple[str, str]:
    """GET a URL and return (html, final_url_after_redirects)."""
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise FetchError(f"Could not fetch {url}: {e}") from e
    return resp.text, resp.url


def discover_report_pages(html: str, final_url: str) -> list[str]:
    """Find every sibling section of an AIHW multi-page report.

    AIHW reports live under ".../contents/<section>" and list every other
    section as a link in their table of contents. If final_url matches that
    shape, return the absolute URL of each linked section (document order,
    deduped). Otherwise return [] (single-page URL, nothing to expand).
    """
    parsed = urlparse(final_url)
    marker_idx = parsed.path.find(CONTENTS_MARKER)
    if marker_idx == -1:
        return []

    prefix = parsed.path[: marker_idx + len(CONTENTS_MARKER)]
    pattern = re.compile(rf'href="({re.escape(prefix)}[^"#?]*)"')

    seen: list[str] = []
    for match in pattern.finditer(html):
        path = match.group(1)
        if path not in seen:
            seen.append(path)

    base = f"{parsed.scheme}://{parsed.netloc}"
    return [urljoin(base, path) for path in seen[:MAX_REPORT_PAGES]]


ABS_METHODOLOGY_LINK_TEXT = re.compile(r"^\s*Methodology\s*$", re.I)


def discover_methodology_page(html: str, final_url: str, *, tree=None) -> list[str]:
    """Find an ABS release's separate companion methodology page.

    Unlike AIHW's ".../contents/" pattern, this can't be detected from the
    URL shape alone: an ABS statistics page keeps only a short summary of
    its methodology inline and links out to the real, much longer document
    under a completely different "/methodologies/" URL path, via a link
    literally labelled "Methodology" (confirmed against a real release; ABS
    feature articles don't have this - their outbound links are just
    citations to related surveys, not a dedicated companion page).

    Accepts an already-parsed `tree` (the same page gets parsed by more than
    one of these extraction functions - passing it in once avoids repeating
    an lxml parse of the same HTML for every check).
    """
    if tree is None:
        try:
            tree = lxml.html.fromstring(html)
        except lxml.etree.LxmlError:
            return []

    nodes = tree.xpath('//*[@id="page-content"]')
    if not nodes:
        return []

    final_host = urlparse(final_url).netloc
    found: list[str] = []
    for link in nodes[0].xpath(".//a[@href]"):
        if not ABS_METHODOLOGY_LINK_TEXT.match(link.text_content() or ""):
            continue
        absolute = urljoin(final_url, link.get("href")).split("#")[0]
        if urlparse(absolute).netloc != final_host or "/methodologies/" not in absolute:
            continue
        if absolute not in found:
            found.append(absolute)
    return found


def _time_tag_attrs(html: str) -> list[dict[str, str]]:
    """Return {attr: value} dicts for every <time ...> tag, attribute order agnostic."""
    tags = re.findall(r"<time\b[^>]*>", html, flags=re.I)
    parsed = []
    for tag in tags:
        attrs = dict(re.findall(r'(\w[\w-]*)="([^"]*)"', tag))
        parsed.append(attrs)
    return parsed


def extract_abs_release_date(html: str, *, tree=None) -> str | None:
    """Find an ABS page's own release date.

    ABS marks this as plain text (no <time> tag at all) in a div with class
    "field--name-field-abs-release-date field--label-above". The same field
    name is reused by unrelated "related articles" cards elsewhere on the
    page for THEIR OWN release date, but those are marked
    "field--label-visually_hidden" instead - confirmed on a real page (3
    occurrences: 1 genuine, 2 from unrelated cards) - so the label-position
    class is what distinguishes the page's own date from an unrelated one.

    Accepts an already-parsed `tree` to avoid re-parsing the same HTML that
    other extraction steps already parsed.
    """
    if tree is None:
        try:
            tree = lxml.html.fromstring(html)
        except lxml.etree.LxmlError:
            return None

    nodes = tree.xpath(
        '//div[contains(@class, "field-abs-release-date") and contains(@class, "field--label-above")]'
    )
    if not nodes:
        return None

    match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", nodes[0].text_content())
    if not match:
        return None
    day, month, year = match.groups()
    try:
        return datetime(int(year), int(month), int(day)).strftime("%Y-%m-%d")
    except ValueError:
        return None


def extract_last_updated(html: str, *, tree=None) -> str | None:
    """Find a page's last-updated date, normalized to YYYY-MM-DD.

    Tries, in order: ABS's own release-date field; the footer "last updated"
    <time> tag; the report-title <time> tag; any other <time datetime>, but
    only when there is exactly one candidate (multiple unrelated <time> tags
    can share an identical generic class, e.g. class="datetime", which would
    otherwise collide into looking like a single safe choice - counting
    tags, not distinct class names, avoids that); then a "Last updated" text
    fallback for pages with no <time> markup at all.
    """
    abs_date = extract_abs_release_date(html, tree=tree)
    if abs_date:
        return abs_date

    candidates = [(attrs.get("class", ""), attrs["datetime"]) for attrs in _time_tag_attrs(html) if attrs.get("datetime")]

    for preferred in LAST_UPDATED_CLASS_PREFERENCE:
        for cls, value in candidates:
            if preferred in cls:
                return value.split("T")[0]

    if len(candidates) == 1:
        return candidates[0][1].split("T")[0]

    match = re.search(r"Last updated:?\s*(\d{1,2}\s+\w+\s+\d{4})", html, flags=re.I)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%d %B %Y").strftime("%Y-%m-%d")
    except ValueError:
        return match.group(1)


def extract_data_links(html: str, page_url: str) -> list[str]:
    """Collect absolute links to downloadable data files (not downloaded, just noted)."""
    extensions = "|".join(DATA_FILE_EXTENSIONS)
    pattern = re.compile(rf'href="([^"?#]+\.(?:{extensions}))"', flags=re.I)
    seen: list[str] = []
    for match in pattern.finditer(html):
        link = urljoin(page_url, match.group(1))
        if link not in seen:
            seen.append(link)
    return seen


# Only whole-line matches confirmed (against real AIHW output) to be orphaned
# in-page-nav labels left behind after trafilatura strips their link list -
# never a substring match, since "On this page, ..." and "In this section, ..."
# also occur as real prose and must not be touched.
BOILERPLATE_LINE_PATTERNS = [
    re.compile(r"^\*\*On this page:?\*\*$"),
    re.compile(r"^#{1,6}\s*On this page(\s+In this section)?\s*$", re.I),
    re.compile(r"^#{1,6}\s*In this section\s*$", re.I),
]


def strip_boilerplate(markdown: str) -> str:
    """Drop orphaned nav-label lines and collapse the blank lines left behind."""
    kept = [line for line in markdown.split("\n") if not any(p.match(line.strip()) for p in BOILERPLATE_LINE_PATTERNS)]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept))


def _strip_chart_data(tree) -> None:
    """Remove every <pre> node in place.

    ABS embeds raw JSON/config for its JS-rendered chart widgets in <pre>
    tags - one widget alone can carry flowchart-data, flowchart-palette,
    chart-caption, chart-headers, chart-annotations, and x/y axis-options as
    separate <pre> elements, alongside the chart's real alt-text
    description elsewhere in the DOM. trafilatura treats <pre> as
    preformatted text and includes it verbatim, dumping these blobs
    straight into the markdown. None of this site's <pre> tags hold genuine
    readable content, so all of them are dropped before extraction runs.
    """
    for el in tree.xpath("//pre"):
        el.getparent().remove(el)


def _flatten_field_items(root) -> list:
    """Direct children of `root`, expanding any child that itself wraps
    <div class="field__item"> grandchildren into those grandchildren."""
    blocks = []
    for child in root:
        field_items = child.xpath('./div[contains(concat(" ", normalize-space(@class), " "), " field__item ")]')
        blocks.extend(field_items) if field_items else blocks.append(child)
    return blocks


def _extract_block(element) -> str:
    """Render one content block to markdown, preserving its own heading.

    trafilatura treats a bare fragment's first heading as the document title
    and drops it from the body, so the heading is pulled out here and
    re-added manually before handing the remainder to trafilatura.
    """
    element = copy.deepcopy(element)
    headings = element.xpath(".//h1 | .//h2 | .//h3 | .//h4")
    prefix = ""
    if headings:
        first = headings[0]
        prefix = f'{"#" * int(first.tag[1])} {first.text_content().strip()}\n\n'
        first.getparent().remove(first)

    fragment_html = lxml.html.tostring(element, encoding="unicode")
    wrapped = f"<html><head><title>x</title></head><body>{fragment_html}</body></html>"
    body_md = trafilatura.extract(wrapped, output_format="markdown", include_tables=True) or ""
    return (prefix + body_md).strip()


def extract_markdown(html: str, *, tree=None) -> str | None:
    """Extract a page's main content as markdown.

    A single trafilatura pass over the whole page works for most sites (e.g.
    AIHW reports). ABS statistics releases instead split their content into
    many separate "field__item" blocks under a "#page-content" container;
    trafilatura's main-content scoring picks only one of those blocks
    (usually just the intro paragraph) and silently drops the rest. When
    that structure is detected - even down to a single block, since relying
    on trafilatura's whole-page pass at all reintroduces the same "picks one
    region, drops the rest" risk - every block found is extracted and
    combined separately instead of trusting a single whole-page pass.

    Accepts an already-parsed `tree` to avoid re-parsing the same HTML that
    other extraction steps already parsed. Note this function still mutates
    it in place (chart-data <pre> tags are stripped from it) - harmless for
    other callers sharing the same tree, since none of them look at <pre>.
    """
    if tree is None:
        try:
            tree = lxml.html.fromstring(html)
        except lxml.etree.LxmlError:
            tree = None

    blocks = []
    if tree is not None:
        _strip_chart_data(tree)
        nodes = tree.xpath('//*[@id="page-content"]')
        blocks = _flatten_field_items(nodes[0]) if nodes else []

    if not blocks:
        cleaned_html = lxml.html.tostring(tree, encoding="unicode") if tree is not None else html
        return trafilatura.extract(cleaned_html, output_format="markdown", include_tables=True)

    parts = [part for part in (_extract_block(b) for b in blocks) if part]
    return "\n\n".join(parts) if parts else None


def fetch_and_extract(url: str, *, html: str | None = None, final_url: str | None = None) -> ExtractResult:
    """Fetch a URL and return an ExtractResult.

    For an ordinary page this is just the one URL. For an AIHW multi-page
    report, every section listed in its table of contents is fetched and
    combined into one markdown document, since fetching only the given
    section (e.g. just ".../contents/about") would leave out the rest. For
    an ABS release with a separate methodology page, that page is appended
    the same way, since the inline "Methodology" section is often just a
    short stub pointing at the real document.

    A caller that already fetched `url` to resolve its canonical form (e.g.
    for a cache check) can pass the resulting `html`/`final_url` straight in
    to avoid fetching the same entry page twice.
    """
    if html is None or final_url is None:
        html, final_url = fetch_html(url)

    try:
        entry_tree = lxml.html.fromstring(html)
    except lxml.etree.LxmlError:
        entry_tree = None

    page_urls = discover_report_pages(html, final_url) or [
        final_url, *discover_methodology_page(html, final_url, tree=entry_tree)
    ]
    multi_page = len(page_urls) > 1

    sections: list[str] = []
    fetched: list[str] = []
    report_title: str | None = None
    last_updated: str | None = None
    data_links: list[str] = []
    page_details: dict[str, dict] = {}

    for page_url in page_urls:
        if page_url == final_url:
            page_html, tree = html, entry_tree
        else:
            try:
                page_html = fetch_html(page_url)[0]
            except FetchError:
                continue
            time.sleep(REQUEST_DELAY)
            try:
                tree = lxml.html.fromstring(page_html)
            except lxml.etree.LxmlError:
                tree = None

        section_md = extract_markdown(page_html, tree=tree)
        if not section_md:
            continue
        section_md = strip_boilerplate(section_md)

        metadata = trafilatura.extract_metadata(page_html)
        section_title = (metadata.title if metadata and metadata.title else None) or page_url
        page_date = extract_last_updated(page_html, tree=tree)

        if report_title is None:
            report_title = re.sub(r"\s*[,-]\s*(About|Summary)\s*$", "", section_title, flags=re.I)
        if last_updated is None:
            last_updated = page_date
        for link in extract_data_links(page_html, page_url):
            if link not in data_links:
                data_links.append(link)

        page_details[page_url] = {
            "content_hash": hashlib.sha256(section_md.encode("utf-8")).hexdigest(),
            "last_updated": page_date,
        }
        sections.append(f"## {section_title}\n\nSource: {page_url}\n\n{section_md}" if multi_page else section_md)
        fetched.append(page_url)

    if not sections:
        raise FetchError(f"No extractable content found at {url}")

    if multi_page:
        print(f"    Combined {len(fetched)}/{len(page_urls)} report sections")

    body = "\n\n---\n\n".join(sections)
    return ExtractResult(report_title or url, body, fetched, last_updated, data_links, final_url, page_details)


def save_markdown(source_label: str, url: str, result: ExtractResult, content_hash: str, extracted_at: str) -> Path:
    """Write one .md file with YAML frontmatter and return its path.

    The filename is the slugified title plus an 8-character hash of the
    canonical URL. The URL suffix is what actually guarantees uniqueness -
    two different reports can easily produce the same slug (many government
    reports share generic titles like "Summary"), which would otherwise let
    one silently overwrite the other's file. It's stable across runs for the
    same URL, so re-fetching a report always rewrites the same file.
    """
    dest_dir = OUTPUT_ROOT / source_label
    dest_dir.mkdir(parents=True, exist_ok=True)

    url_suffix = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
    filename = f"{slugify(result.title)}-{url_suffix}.md"
    dest_path = dest_dir / filename

    page_lines = "".join(
        f"  - url: {p}\n"
        f"    last_updated: {result.page_details.get(p, {}).get('last_updated') or 'unknown'}\n"
        f"    content_hash: {result.page_details.get(p, {}).get('content_hash', '')}\n"
        for p in result.pages
    )

    frontmatter = (
        "---\n"
        f"source: {source_label}\n"
        f"url: {url}\n"
        f"title: {result.title}\n"
        f"extracted_at: {extracted_at}\n"
        f"content_hash: {content_hash}\n"
        f"last_updated: {result.last_updated or 'unknown'}\n"
        f"page_count: {len(result.pages)}\n"
        f"pages:\n{page_lines}"
        f"data_link_count: {len(result.data_links)}\n"
        "data_links:\n" + "".join(f"  - {d}\n" for d in result.data_links) +
        "---\n\n"
    )

    dest_path.write_text(frontmatter + result.body, encoding="utf-8")
    return dest_path


def load_manifest() -> dict:
    """Load the cross-run change-detection state.

    Returns {} on a first run, or if the file is unreadable/corrupted (e.g.
    a previous run was killed mid-write) - a manifest that can't be parsed
    should degrade to "start fresh", not crash the whole script.
    """
    if not MANIFEST_PATH.exists():
        return {}
    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"Warning: {MANIFEST_PATH} is corrupted ({e}) - starting with an empty manifest.\n")
        return {}


def save_manifest(manifest: dict) -> None:
    """Persist the manifest back to disk, pretty-printed for easy diffing."""
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")


def record_content(
    manifest: dict, key: str, content_hash: str, title: str, path: Path, page_details: dict[str, dict]
) -> tuple[str, list[str]]:
    """Update the manifest entry for `key`; return (status, changed_pages).

    status is "new" (first time seeing this report), "changed" (the combined
    content_hash differs from last run), or "unchanged". changed_pages lists
    which specific section/page URLs had a different hash than last run, so
    a change in a multi-page report can be pinpointed to a section instead
    of just "something in here changed" - empty for "new" reports (nothing
    to compare against yet) and for any page not tracked in a previous run
    (avoids a false "everything changed" burst the first time this ships).

    Keyed by the canonical URL (after redirects), not the URL the user typed
    or the report title/filename, so two different entry points into the
    same report (e.g. with or without a trailing "/contents/about") share
    one manifest entry instead of fragmenting into two.
    """
    now = datetime.now(timezone.utc).isoformat()
    entry = manifest.get(key)
    prev_pages = entry.get("pages", {}) if entry else {}

    pages: dict[str, dict] = {}
    changed_pages: list[str] = []
    for page_url, info in page_details.items():
        prev = prev_pages.get(page_url)
        page_changed = prev is not None and prev.get("content_hash") != info["content_hash"]
        pages[page_url] = {
            "content_hash": info["content_hash"],
            "last_updated": info["last_updated"],
            "last_changed_at": now if page_changed or prev is None else prev["last_changed_at"],
        }
        if page_changed:
            changed_pages.append(page_url)

    if entry is None:
        manifest[key] = {
            "title": title,
            "content_hash": content_hash,
            "path": str(path),
            "first_seen_at": now,
            "last_seen_at": now,
            "last_changed_at": now,
            "pages": pages,
        }
        return "new", []

    report_changed = entry.get("content_hash") != content_hash
    entry["title"] = title
    entry["content_hash"] = content_hash
    entry["path"] = str(path)
    entry["last_seen_at"] = now
    entry["pages"] = pages
    if report_changed:
        entry["last_changed_at"] = now
    return ("changed" if report_changed else "unchanged"), changed_pages


def process_source(source_label: str, urls: list[str], manifest: dict, force_refresh: bool) -> None:
    """Fetch, extract, save, and record every URL for one source (AIHW/ABS).

    Skips a URL entirely (after one cheap request to resolve its canonical
    form) when it's already in the manifest with its .md file still on disk
    and force_refresh is False - that's what keeps repeat runs fast. A
    failed or empty fetch is skipped with a message, not fatal to the batch,
    and neither is a disk-write failure when saving the result.
    """
    print(f"\nExtracting {source_label} URLs...")
    for i, url in enumerate(urls):
        if i > 0:
            time.sleep(REQUEST_DELAY)

        try:
            html, final_url = fetch_html(url)
        except FetchError as e:
            print(f"  Skipped ({e})")
            continue

        cached = manifest.get(final_url)
        if cached and not force_refresh and Path(cached.get("path", "")).exists():
            checked = cached["last_seen_at"][:10]
            print(f"  Already have: {cached['path']} (last checked {checked}) - skipping re-fetch")
            continue

        try:
            result = fetch_and_extract(url, html=html, final_url=final_url)
        except FetchError as e:
            print(f"  Skipped ({e})")
            continue

        content_hash = hashlib.sha256(result.body.encode("utf-8")).hexdigest()
        extracted_at = datetime.now(timezone.utc).isoformat()
        try:
            path = save_markdown(source_label, result.canonical_url, result, content_hash, extracted_at)
        except OSError as e:
            print(f"  Skipped (could not save to disk: {e})")
            continue

        status, changed_pages = record_content(
            manifest, result.canonical_url, content_hash, result.title, path, result.page_details
        )

        label = status.upper() if status != "unchanged" else status
        page_note = ""
        if status == "changed" and len(result.pages) > 1:
            page_note = f" ({len(changed_pages)}/{len(result.pages)} sections changed)"
        updated_note = f", last updated {result.last_updated}" if result.last_updated else ""
        print(f"  Saved: {path} [{label}{page_note}{updated_note}, {len(result.data_links)} data file(s)]")


def main() -> None:
    """Entry point: collect all URLs first, then fetch/extract/save each source."""
    print("=== Step 1: AIHW URLs ===")
    aihw_urls = collect_urls("AIHW")

    print("=== Step 2: ABS URLs ===")
    abs_urls = collect_urls("ABS")

    force_refresh = input(
        "\nRe-check already-extracted URLs for content updates? "
        "This re-fetches everything and is slower. (y/n): "
    ).strip().lower() == "y"

    manifest = load_manifest()
    process_source("AIHW", aihw_urls, manifest, force_refresh)
    process_source("ABS", abs_urls, manifest, force_refresh)
    try:
        save_manifest(manifest)
    except OSError as e:
        print(
            f"\nWarning: could not save {MANIFEST_PATH} ({e}). Your .md files were "
            "saved successfully, but change-detection state for this run was not persisted."
        )

    print("\nDone. Files saved under:", OUTPUT_ROOT.resolve())


if __name__ == "__main__":
    main()
