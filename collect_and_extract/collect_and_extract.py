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
from bs4 import BeautifulSoup, Tag

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

# Individual UI/boilerplate strings to drop from ABS paragraphs and list
# items - ported from a teammate's ABS-specific extractor (sources/fetch_abs.py),
# which walks a page's real elements in document order instead of leaning on
# trafilatura's per-fragment scoring. This is noise-removal only (never a
# whole-section exclusion - Methodology/Data downloads/Footnotes stay in,
# since this pipeline already fixed those being dropped).
ABS_UI_TEXT_DENYLIST = {
    "download table",
    "download data",
    "download table as csv",
    "download table as xlsx",
    "download graph as png image",
    "download graph as jpg image",
    "download graph as svg vector image",
    "cite",
    "cite this article",
    "cite this release",
    "back to top",
    "share",
    "share this page",
    "share this article",
    "share this release",
    "print",
    "print this page",
    "was this page useful?",
    "skip to content",
    "skip to main content",
}


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


REFERENCE_SECTION_TITLES = {"references", "bibliography"}
_MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def strip_reference_sections(markdown: str) -> str:
    """Drop a "References"/"Bibliography" heading and everything under it, up
    to the next heading of the same or shallower level.

    Confirmed on real AIHW pages: a "References" section is a long list of
    bibliographic citations (author, year, title, accessed date) - low value
    for insight extraction, not findings, per an explicit request to skip
    these rather than fix them. Works on any heading trafilatura captured
    directly (e.g. on a report's "technical-notes" pages) as well as ones
    `_convert_aihw_accordions()` created from an accordion trigger, since
    both look identical by the time extraction reaches markdown.
    """
    lines = markdown.split("\n")
    kept: list[str] = []
    skip_level: int | None = None

    for line in lines:
        match = _MARKDOWN_HEADING.match(line)
        if match:
            level = len(match.group(1))
            if skip_level is not None and level <= skip_level:
                skip_level = None
            if skip_level is None and _normalise_heading_text(match.group(2)) in REFERENCE_SECTION_TITLES:
                skip_level = level
                continue

        if skip_level is not None:
            continue
        kept.append(line)

    return "\n".join(kept)


def _strip_chart_data(tree) -> None:
    """Remove every <pre> node in place, except a chart's own caption.

    ABS embeds raw JSON/config for its JS-rendered chart widgets in <pre>
    tags - one widget alone can carry flowchart-data, flowchart-palette,
    chart-headers, chart-annotations, and x/y axis-options as separate <pre>
    elements. trafilatura treats <pre> as preformatted text and includes it
    verbatim, dumping these blobs straight into the markdown, so all of them
    are dropped. The one exception is <pre class="chart-caption">, which -
    unlike the others - holds plain human-readable text describing what the
    chart/graph actually shows (confirmed: never JSON, always the chart's
    own title, e.g. "12-month mental disorders, by disorder group and sex,
    2020-2022"). Blindly dropping it along with the rest of a chart's <pre>
    tags silently lost every graph's description (confirmed: 12 of 19 chart
    captions on a real page were missing from the extracted output). It's
    converted to a <p class="abs-chart-caption"> - a distinctive marker
    class, not just a bare <p> - because trafilatura's own scoring can still
    drop it even as a normal paragraph: confirmed on a block that was
    otherwise just a caption immediately followed by a large data table,
    with no other prose to give trafilatura a reason to trust it as real
    content. `_extract_block()` looks for this class and pulls it out
    directly, the same way it already does for <table>, rather than leaving
    it to trafilatura's judgment a second time.
    """
    for el in tree.xpath("//pre"):
        if _has_class(el, "chart-caption"):
            caption = el.makeelement("p", {"class": "abs-chart-caption"})
            caption.text = el.text_content()
            el.getparent().replace(el, caption)
            continue
        el.getparent().remove(el)


def _strip_chart_controls(tree) -> None:
    """Remove chart tab-switcher and export-button UI chrome in place.

    Every chart widget has a "Graph"/"Table" tab switcher (class
    "chart-tabs") and a row of "Download table as CSV/XLSX", "Download
    graph as PNG/JPG/SVG" buttons (class "chart-export-buttons") - pure UI
    controls, never real content. Left in, this text can crowd out real
    content in whatever block it ends up bundled with: confirmed on a real
    page where one chart's caption survived fine elsewhere but was dropped
    by trafilatura specifically in the one block that also had this button
    chrome sitting next to it.
    """
    for class_name in ("chart-tabs", "chart-export-buttons"):
        for el in tree.xpath(f'//*[contains(@class, "{class_name}")]'):
            parent = el.getparent()
            if parent is not None:
                parent.remove(el)


AIHW_ACCORDION_SKIP_TITLES = {"references", "bibliography"}


def _convert_aihw_accordions(tree) -> None:
    """Convert AIHW's accordion-widget triggers into real heading tags, in place.

    Confirmed widespread on a real AIHW report: a topic label like "Impact
    on health, aged care and social systems" is a
    <button class="w-accordion__item__trigger">, not a heading tag at all
    (present on 58 of 81 pages checked on one report, 2-22 accordion
    sections each). trafilatura still keeps the accordion's own text
    content - the collapsed-by-default styling is presentational only, not
    reflected in the fetched HTML - but with no heading marking where one
    topic ends and the next begins, unrelated topics get silently merged
    into one undifferentiated block: confirmed, a "Childhood dementia"
    section flowed directly into an unrelated "data gaps and limitations"
    topic with no boundary between them at all.

    Uses the button's own direct text (`.text`, before its nested icon/
    "Expand" spans) rather than `.text_content()`, which would pull in that
    "Expand" label too. A trigger whose own text is empty (some are used for
    a different, sub-item purpose) is left alone.

    A trigger's whole section (the button plus its content panel) is
    dropped entirely when the label matches AIHW_ACCORDION_SKIP_TITLES -
    "References"/"Bibliography" sections use this same accordion widget and
    are low-value bibliographic listings, not findings.
    """
    for trigger in tree.xpath('//*[contains(concat(" ", normalize-space(@class), " "), " w-accordion__item__trigger ")]'):
        text = (trigger.text or "").strip()
        if not text:
            continue

        if _normalise_heading_text(text) in AIHW_ACCORDION_SKIP_TITLES:
            panel_id = trigger.get("aria-controls")
            panel = tree.xpath(f'//*[@id="{panel_id}"]') if panel_id else []
            for el in [trigger, *panel]:
                parent = el.getparent()
                if parent is not None:
                    parent.remove(el)
            continue

        heading = trigger.makeelement("h4", {})
        heading.text = text
        trigger.getparent().replace(trigger, heading)


def _has_class(element, name: str) -> bool:
    """Whether an lxml element's class attribute includes `name` as a whole token."""
    return name in (element.get("class") or "").split()


def _outermost_field_items(element) -> list:
    """Find the outermost <div class="field__item"> elements inside `element`,
    without descending past one once found (nested field__items inside it
    are handled separately, by recursing into it afterward - see
    `_expand_block`). ABS nests these multiple levels deep through plain
    wrapper divs (e.g. field__item -> abs-section -> abs-section-content ->
    field__item), so this has to walk actual DOM children rather than a
    fixed-depth "./div[...]" XPath, which only ever sees direct children.
    """
    found = []
    for child in element:
        if not isinstance(child.tag, str):
            continue  # skip comments/processing instructions
        if child.tag == "div" and _has_class(child, "field__item"):
            found.append(child)
        else:
            found.extend(_outermost_field_items(child))
    return found


def _own_heading(element, field_items: list):
    """The first heading in `element` that doesn't belong to one of its
    nested `field_items` - i.e. the container's own framing title (e.g.
    "Crisis support services"), as opposed to a nested leaf's own heading
    (e.g. "24 hours, 7 days"). None if the container has no framing title
    of its own (most don't - only sections with a visible h2/h3 title do).

    Checks ancestry by walking each heading's parent chain and comparing
    with `is` against `field_items` (kept alive in that list, so identity
    comparison is reliable) rather than comparing `id()` across separate
    .xpath() calls - lxml only guarantees a stable id() for a proxy object
    while something keeps it alive, and nothing did here, so id() reuse
    after garbage collection produced false "not excluded" matches and a
    heading got treated as several different containers' "own heading" at
    once (confirmed: a heading appearing once on the real page was
    duplicated three times in the output).
    """
    for heading in element.xpath(".//h1 | .//h2 | .//h3 | .//h4"):
        ancestor = heading.getparent()
        nested = False
        while ancestor is not None:
            if any(ancestor is item for item in field_items):
                nested = True
                break
            ancestor = ancestor.getparent()
        if not nested:
            return heading
    return None


def _wrap_heading(heading):
    """Wrap a bare heading element in a fresh <div>, so _extract_block's own
    descendant search (".//h1 | ...") can find and preserve it - it only
    looks at descendants, never the element handed to it directly."""
    wrapper = lxml.html.fromstring("<div></div>")
    wrapper.append(copy.deepcopy(heading))
    return wrapper


def _expand_block(element) -> list:
    """Recursively expand one element into its genuine leaf content blocks.

    ABS nests <div class="field__item"> wrappers multiple levels deep - a
    top-level section's field__item can itself contain several nested
    field__item "paragraph" blocks (a callout, a collapsible sub-section, a
    chart+table pairing, a plain text paragraph, ...), each of which can
    nest further again (confirmed on a real page: one section alone had 32
    nested field__item descendants). Handing an ancestor block to
    trafilatura instead of its real leaf paragraphs is exactly what causes
    it to keep only one nested paragraph and silently drop the rest -
    confirmed on a real "Crisis support services" section with two nested
    paragraphs, "24 hours, 7 days" and "COVID-19": only the first survived
    (duplicated), the second was dropped entirely. So every container with
    its own field__item children is expanded into those children,
    recursively, all the way down to genuine leaves. The container's own
    framing heading (e.g. "Crisis support services" itself), if it has one,
    is kept as its own small leaf ahead of its expanded children - dropping
    it entirely was tried first and cost far more than expected: with
    several levels of nesting (e.g. "Prevalence of mental disorders" ->
    "12-month Anxiety disorders" -> "Support Services"), losing every
    intermediate heading left many leaves as unlabelled floating text with
    no indication what topic they belonged to.

    A leaf is a field__item with no further field__item of its own, or -
    when there's no field__item at all - a "methodology overview" style
    container wrapping several <div class="section ..."> cards inside a
    <div class="grid"> (confirmed separately: without this check, a whole
    "Methodology" area gets handed to trafilatura as one fragment, which
    drops every card's heading and even whole cards' content).
    """
    field_items = _outermost_field_items(element)
    if field_items:
        expanded = []
        own_heading = _own_heading(element, field_items)
        if own_heading is not None:
            expanded.append(_wrap_heading(own_heading))
        for item in field_items:
            expanded.extend(_expand_block(item))
        return expanded

    section_cards = element.xpath(
        './/div[contains(@class, "grid")]/div[contains(concat(" ", normalize-space(@class), " "), " section ")]'
    )
    return section_cards if section_cards else [element]


def _flatten_field_items(root) -> list:
    """Direct children of `root`, each recursively expanded into leaf blocks."""
    blocks = []
    for child in root:
        blocks.extend(_expand_block(child))
    return blocks


def _table_to_markdown(table) -> str | None:
    """Render a simple (no rowspan/colspan) HTML <table> to markdown
    directly, without trafilatura's table conversion - which has
    demonstrated more than one row/column-dropping bug on real ABS tables: a
    cell wrapped in <p> silently lost its own text, shifting every following
    column in that row one to the left; and a plain-text first row was
    dropped outright for a cause never fully isolated even after matching
    its exact HTML byte-for-byte in isolation. Doing this ourselves
    guarantees every row and cell survives. It also preserves the table's
    own <caption> (e.g. "New South Wales", labelling which state a resource
    table is for) as a bold label above it - previously silently lost either
    way, since trafilatura's table conversion doesn't carry it through.
    """
    rows = table.xpath(".//tr")
    if not rows:
        return None

    def cell_text(cell) -> str:
        """One cell's text, single-line and pipe-escaped for a markdown table."""
        return " ".join(cell.text_content().split()).replace("|", "\\|")

    grid = [[cell_text(cell) for cell in row.xpath("./th | ./td")] for row in rows]
    grid = [r for r in grid if any(r)]
    if not grid:
        return None

    width = max(len(r) for r in grid)
    grid = [r + [""] * (width - len(r)) for r in grid]

    lines = []
    caption = table.xpath("./caption")
    caption_text = caption[0].text_content().strip() if caption else ""
    if caption_text:
        lines.extend([f"**{caption_text}**", ""])

    lines.append("| " + " | ".join(grid[0]) + " |")
    lines.append("|" + "|".join(["---"] * width) + "|")
    lines.extend("| " + " | ".join(row) + " |" for row in grid[1:])
    return "\n".join(lines)


def _extract_table(table) -> str | None:
    """Render one <table> element to markdown on its own.

    Tables without rowspan/colspan go through `_table_to_markdown()`
    directly - see its docstring for why. A table that does use rowspan/
    colspan needs proper grid expansion to render correctly, which
    `_table_to_markdown()` doesn't attempt, so those fall back to
    trafilatura (which has worked fine on this site's rowspan/colspan
    tables in practice; the bugs above were only ever seen on plain ones).
    Cells wrapped in <p> are stripped either way, for the same "shifts
    every following column" reason.
    """
    table = copy.deepcopy(table)
    lxml.etree.strip_tags(table, "p")
    if not table.xpath(".//*[@rowspan] | .//*[@colspan]"):
        return _table_to_markdown(table)
    table_html = f"<html><body>{lxml.html.tostring(table, encoding='unicode')}</body></html>"
    return trafilatura.extract(table_html, output_format="markdown", include_tables=True)


def _clean_abs_text(text: str | None) -> str:
    """Normalize whitespace in one piece of extracted ABS text."""
    if not text:
        return ""
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _is_abs_ui_text(text: str) -> bool:
    """Whether `text` is a known ABS interface/download-button label."""
    normalised = _clean_abs_text(text).lower().rstrip(":")
    if normalised in ABS_UI_TEXT_DENYLIST:
        return True
    return normalised.startswith(("download table as ", "download graph as "))


def _get_abs_main_content(soup: BeautifulSoup) -> Tag | None:
    """Locate an ABS page's <main> or <article> region, or None if neither exists."""
    return soup.find("main") or soup.find("article")


# Pure navigation/UI chrome sections to skip entirely (heading + everything
# until the next heading of the same or higher level) - distinct from, and
# much narrower than, the teammate script's EXCLUDED_SECTION_TITLES, which
# also drops Methodology/Data downloads/Footnotes/Media releases (real
# content this pipeline already fixed and deliberately keeps). "on this
# page" is safe to skip this way too: confirmed on a real page it's a JS
# table-of-contents widget whose own list is just empty placeholder <li>
# items, not real content - nothing follows it before the next real heading.
ABS_NAV_SECTION_TITLES = {"breadcrumb", "apa", "citation", "abs main menu", "on this page"}


def _normalise_heading_text(text: str) -> str:
    """Lowercase and de-punctuate a heading for matching against ABS_NAV_SECTION_TITLES."""
    return _clean_abs_text(text).lower().rstrip(":").strip()


def _extract_abs_table(table: Tag) -> str | None:
    """Render one bs4 <table> to markdown via our own lxml table renderer.

    Re-parses the table as lxml and reuses `_extract_table()` rather than
    building a second table-to-markdown converter: a from-scratch bs4 one
    (ported from the same teammate's script this whole extraction approach
    is based on) mishandles a multi-row header built with rowspan/colspan -
    confirmed on a real ABS table with a 2-level "Recommendation / Threshold"
    header, where the second header row was rendered as a data row and a
    rowspanned "Sleep" row's data was split across two separate table rows.
    `_extract_table()` already detects that shape and falls back to
    trafilatura specifically to avoid this.
    """
    lxml_table = lxml.html.fromstring(str(table))
    return _extract_table(lxml_table)


def _extract_abs_content_blocks(main_content: Tag) -> list[str]:
    """Walk an ABS page's real content elements in document order and
    render each one to markdown directly - ported from a teammate's
    ABS-specific extractor (sources/fetch_abs.py). Unlike this pipeline's
    other extraction path (splitting into "field__item" blocks and handing
    each to trafilatura), this never trusts trafilatura's own scoring to
    decide what counts as real content: every heading, paragraph, list item,
    chart caption and table is picked up directly from its tag, so there's
    nothing for a per-fragment heuristic to silently drop.

    Deliberately does not port that script's whole-section exclusions
    (Methodology/Data downloads/Footnotes/Media releases) - this pipeline
    already fixed those being missing and shouldn't re-drop them - or its
    image downloading, which is a separate capability this pipeline doesn't
    have at all yet. It does skip pure navigation chrome sections
    (ABS_NAV_SECTION_TITLES) the same way, since <main>/<article> is a wider
    scope than this pipeline's other extraction path (which never saw this
    chrome at all, being scoped to "#page-content" instead) - confirmed on a
    real page: without this, a page's Breadcrumb list and APA/Citation boxes
    were rendered as if they were real article content.
    """
    parts: list[str] = []
    skipping_section = False
    skipped_heading_level: int | None = None

    elements = main_content.find_all(["h2", "h3", "h4", "h5", "h6", "p", "ul", "ol", "table", "pre"])

    for element in elements:
        # Avoid nested duplicates: a cell's own <p>, a sub-list nested inside
        # another list, or a list item's own <p> would otherwise be picked up
        # both as part of their parent's text and again as their own element.
        if element.name != "table" and element.find_parent("table"):
            continue
        if element.name in {"ul", "ol"} and element.find_parent(["ul", "ol"]):
            continue
        if element.name == "p" and element.find_parent("li"):
            continue

        if element.name in {"h2", "h3", "h4", "h5", "h6"}:
            text = _clean_abs_text(element.get_text(" ", strip=True))
            if not text:
                continue
            level = int(element.name[1])

            if skipping_section:
                if skipped_heading_level is not None and level <= skipped_heading_level:
                    skipping_section = False
                    skipped_heading_level = None
                else:
                    continue

            if _normalise_heading_text(text) in ABS_NAV_SECTION_TITLES:
                skipping_section = True
                skipped_heading_level = level
                continue

            if _is_abs_ui_text(text):
                continue
            parts.append(f"{'#' * max(2, min(level, 6))} {text}")
            continue

        # Continues the same if/elif dispatch as above: skip non-heading
        # content while inside a skipped nav section, otherwise handle it by
        # element type below.
        if skipping_section:
            continue

        elif element.name == "p":
            text = _clean_abs_text(element.get_text(" ", strip=True))
            if not text or _is_abs_ui_text(text):
                continue
            parts.append(text)

        elif element.name in {"ul", "ol"}:
            items = []
            for li in element.find_all("li", recursive=False):
                text = _clean_abs_text(li.get_text(" ", strip=True))
                if text and not _is_abs_ui_text(text):
                    items.append(text)
            if items:
                ordered = element.name == "ol"
                parts.append(
                    "\n".join(f"{i}. {item}" if ordered else f"- {item}" for i, item in enumerate(items, start=1))
                )

        elif element.name == "table":
            table_md = _extract_abs_table(element)
            if table_md:
                parts.append(table_md)

        elif element.name == "pre" and "chart-caption" in (element.get("class") or []):
            # A chart's own caption (e.g. "12-month mental disorders, by
            # disorder group and sex, 2020-2022") - not part of the teammate's
            # original element list at all (it only ever selects p/ul/ol/
            # table/figure), which would silently drop every chart's
            # description the same way trafilatura's own per-fragment
            # scoring was confirmed to. Rendered in its natural document
            # position, immediately after the data table it describes.
            text = _clean_abs_text(element.get_text(" ", strip=True))
            if text:
                parts.append(f"*{text}*")

    return parts


def extract_abs_article_markdown(html: str, page_url: str) -> str | None:
    """Extract an ABS page as markdown via the document-order walker above.

    Returns None if the page has no <main>/<article> region or the walk
    produced no content blocks at all, so the caller can fall back to this
    pipeline's other, more general extraction path instead of failing the
    whole page outright.
    """
    soup = BeautifulSoup(html, "html.parser")
    main_content = _get_abs_main_content(soup)
    if main_content is None:
        return None
    parts = _extract_abs_content_blocks(main_content)
    return "\n\n".join(parts) if parts else None


def _extract_block(element) -> str:
    """Render one content block to markdown, preserving its own heading.

    trafilatura treats a bare fragment's first heading as the document title
    and drops it from the body, so the heading is pulled out here and
    re-added manually before handing the remainder to trafilatura.

    Every <table> in the block is also extracted independently and appended
    after the prose, rather than left for trafilatura to find on its own
    within the surrounding fragment. Confirmed on a real ABS chart: each
    chart is actually a two-tab widget - an empty, JS-only chart mount div
    plus a genuine data table (the chart's accessible alternative, with a
    real <caption> and header cells) - and trafilatura's single-pass scoring
    drops the table when it sees the whole tabbed block at once, even though
    the same table extracts cleanly in isolation.

    A chart's caption (marked <p class="abs-chart-caption"> by
    `_strip_chart_data()`) is pulled out and paired with its table the same
    way, for the same reason: trafilatura can still drop it even as a plain
    paragraph when a block is just a caption immediately followed by a large
    table with no other prose around it to signal that the caption is real
    content.
    """
    element = copy.deepcopy(element)
    headings = element.xpath(".//h1 | .//h2 | .//h3 | .//h4")
    prefix = ""
    if headings:
        first = headings[0]
        prefix = f'{"#" * int(first.tag[1])} {first.text_content().strip()}\n\n'
        first.getparent().remove(first)

    captions_md = []
    for caption in element.xpath('.//p[contains(concat(" ", normalize-space(@class), " "), " abs-chart-caption ")]'):
        text = caption.text_content().strip()
        if text:
            captions_md.append(text)
        caption.getparent().remove(caption)

    tables_md = []
    for table in element.xpath(".//table"):
        table_md = _extract_table(table)
        if table_md:
            tables_md.append(table_md.strip())
        table.getparent().remove(table)

    fragment_html = lxml.html.tostring(element, encoding="unicode")
    wrapped = f"<html><head><title>x</title></head><body>{fragment_html}</body></html>"
    body_md = trafilatura.extract(wrapped, output_format="markdown", include_tables=True) or ""

    # Pair each caption with its table (the common case: one caption
    # describing one table) so it reads right above the data it describes;
    # any leftover of either list (uneven counts) is just appended after.
    paired = [f"{cap}\n\n{tbl}" for cap, tbl in zip(captions_md, tables_md)]
    leftover_captions = captions_md[len(tables_md):]
    leftover_tables = tables_md[len(captions_md):]

    parts = [prefix + body_md, *paired, *leftover_captions, *leftover_tables]
    return "\n\n".join(p.strip() for p in parts if p.strip())


def extract_markdown(html: str, page_url: str = "", *, tree=None) -> str | None:
    """Extract a page's main content as markdown.

    For an ABS page (detected from `page_url`'s domain - AIHW never takes
    this branch), tries the document-order element walker
    (`extract_abs_article_markdown()`) first, since it doesn't depend on
    trafilatura's per-fragment scoring at all. Falls back to the logic below
    if that finds nothing (e.g. a page shape the walker doesn't recognize),
    so an ABS page is never worse off than before this walker existed.

    A single trafilatura pass over the whole page works for most other sites
    (e.g. AIHW reports). ABS statistics releases instead split their content
    into many separate "field__item" blocks under a "#page-content"
    container; trafilatura's main-content scoring picks only one of those
    blocks (usually just the intro paragraph) and silently drops the rest.
    When that structure is detected - even down to a single block, since
    relying on trafilatura's whole-page pass at all reintroduces the same
    "picks one region, drops the rest" risk - every block found is extracted
    and combined separately instead of trusting a single whole-page pass.

    Accepts an already-parsed `tree` to avoid re-parsing the same HTML that
    other extraction steps already parsed. Note this function still mutates
    it in place (chart-data <pre> tags are stripped from it) - harmless for
    other callers sharing the same tree, since none of them look at <pre>.
    """
    if page_url and is_valid_domain(page_url, "ABS"):
        abs_markdown = extract_abs_article_markdown(html, page_url)
        if abs_markdown:
            return abs_markdown

    if tree is None:
        try:
            tree = lxml.html.fromstring(html)
        except lxml.etree.LxmlError:
            tree = None

    blocks = []
    if tree is not None:
        _strip_chart_data(tree)
        _strip_chart_controls(tree)
        _convert_aihw_accordions(tree)
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

        section_md = extract_markdown(page_html, page_url, tree=tree)
        if not section_md:
            continue
        section_md = strip_boilerplate(section_md)
        section_md = strip_reference_sections(section_md)

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
