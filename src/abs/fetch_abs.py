"""
Fetch and extract ABS article content.

RMIT x Medibank Health Insight Engine

This module:
1. Reads enabled ABS article sources from config/sources.yaml.
2. Downloads each ABS article webpage.
3. Uses Trafilatura to extract clean narrative content.
4. Uses BeautifulSoup to extract ABS-specific metadata and HTML tables.
5. Extracts the HTML tables associated with interactive ABS graphs.
6. Downloads meaningful non-chart article images.
7. Saves each article as a Markdown (.md) file.
8. Stores article images in a separate folder associated with the article ID.

"""

from __future__ import annotations

import logging
import mimetypes
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import trafilatura
import yaml
from bs4 import BeautifulSoup, Tag

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parents[2]

CONFIG_FILE = PROJECT_ROOT / "config" / "sources.yaml"

OUTPUT_DIR = PROJECT_ROOT / "data" / "raw" / "abs"

# Request configuration

USER_AGENT = (
    "health-insight-engine/0.1 "
    "(RMIT x Medibank capstone; research use)"
)

REQUEST_TIMEOUT = 30

# Logging

logger = logging.getLogger(__name__)

# Custom error
class FetchError(RuntimeError):
    """Raised when an ABS article cannot be downloaded or extracted."""

# Load ABS sources

def load_abs_sources() -> list[dict]:
    """
    Load enabled ABS article sources from config/sources.yaml.

    Only entries with:
        agency: ABS
        type: article
        enabled: true

    are returned.
    """

    try:
        config = yaml.safe_load(
            CONFIG_FILE.read_text(encoding="utf-8")
        )

    except OSError as exc:
        raise FetchError(
            f"Could not read configuration file: {CONFIG_FILE}"
        ) from exc

    except yaml.YAMLError as exc:
        raise FetchError(
            f"Invalid YAML in configuration file: {CONFIG_FILE}"
        ) from exc

    if not isinstance(config, dict):
        raise FetchError(
            "sources.yaml must contain a YAML dictionary."
        )

    sources = config.get("sources", [])

    if not isinstance(sources, list):
        raise FetchError(
            "'sources' in sources.yaml must be a list."
        )

    abs_sources = []

    for source in sources:

        if not isinstance(source, dict):
            logger.warning(
                "Skipping invalid source entry: expected dictionary, got %s",
                type(source).__name__,
            )
            continue

        if str(source.get("agency", "")).upper() != "ABS":
            continue

        if source.get("type") != "article":
            continue

        if source.get("enabled", True) is False:
            continue

        if not source.get("url"):
            logger.warning(
                "Skipping ABS source '%s' because no URL was provided.",
                source.get("id", "unknown"),
            )
            continue

        if not source.get("id"):
            logger.warning(
                "Skipping ABS source because no source ID was provided."
            )
            continue

        abs_sources.append(source)

    return abs_sources

# General helpers

def _clean_text(text: str | None) -> str:
    """
    Normalise whitespace in extracted webpage text.
    """

    if not text:
        return ""

    text = text.replace("\xa0", " ")

    text = re.sub(
        r"[ \t]+",
        " ",
        text,
    )

    text = re.sub(
        r"\n[ \t]+",
        "\n",
        text,
    )

    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text,
    )

    return text.strip()


def _absolute_url(
    value: str | None,
    page_url: str,
) -> str | None:
    """
    Convert a relative ABS URL to an absolute URL.
    """

    if not value:
        return None

    return urljoin(page_url, value)


def _escape_markdown_cell(value: str) -> str:
    """
    Escape characters that would break a Markdown table.
    """

    value = _clean_text(value)

    value = value.replace(
        "|",
        "\\|",
    )

    value = value.replace(
        "\n",
        " ",
    )

    return value

# Download webpage
def _download_html(url: str) -> str:
    """
    Download the raw HTML for an ABS article.
    """

    try:
        response = requests.get(
            url,
            headers={
                "User-Agent": USER_AGENT,
            },
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

    except requests.RequestException as exc:
        raise FetchError(
            f"Request to {url} failed: {exc}"
        ) from exc

    return response.text

# Metadata extraction

def _extract_title(
    soup: BeautifulSoup,
) -> str | None:
    """
    Extract the article title.
    """

    heading = soup.find("h1")

    if heading:
        title = _clean_text(
            heading.get_text(
                " ",
                strip=True,
            )
        )

        if title:
            return title

    if soup.title:
        title = _clean_text(
            soup.title.get_text(
                " ",
                strip=True,
            )
        )

        if title:
            return title

    return None


def _extract_publication_date(
    soup: BeautifulSoup,
) -> str | None:
    """
    Extract the ABS article publication/release date.
    """

    # Try <time> elements first.
    for time_element in soup.find_all("time"):

        datetime_value = time_element.get("datetime")

        if datetime_value:
            return _clean_text(datetime_value)

        visible_date = _clean_text(
            time_element.get_text(
                " ",
                strip=True,
            )
        )

        if visible_date:
            return visible_date

    # Fallback for ABS text such as:
    # Released 30/06/2026

    page_text = soup.get_text(
        " ",
        strip=True,
    )

    match = re.search(
        r"Released\s+(\d{1,2}/\d{1,2}/\d{4})",
        page_text,
        flags=re.IGNORECASE,
    )

    if match:
        return match.group(1)

    return None

# Main article region
def _get_main_content(
    soup: BeautifulSoup,
) -> Tag:
    """
    Locate the main ABS article region.
    """

    main_content = soup.find("main")

    if main_content is None:
        main_content = soup.find("article")

    if main_content is None:
        raise FetchError(
            "Could not locate the main ABS article content."
        )

    return main_content
# Trafilatura narrative extraction

def _extract_narrative_with_trafilatura(
    html: str,
) -> str:
    """
    Extract the main readable narrative using Trafilatura.

    Tables are excluded here because tables are extracted separately
    with BeautifulSoup and converted to Markdown.
    """

    narrative = trafilatura.extract(
        html,
        include_comments=False,
        include_tables=False,
        include_images=False,
        favor_precision=True,
    )

    if not narrative:
        return ""

    return _clean_text(narrative)

# BeautifulSoup narrative fallback
def _extract_narrative_fallback(
    main_content: Tag,
) -> str:
    """
    Fallback narrative extraction if Trafilatura cannot
    extract usable article text.
    """

    ignored_exact_text = {
        "Graph",
        "Table",
        "Download",
        "APA",
        "Copy",
        "Detail",
        "Cite",
        "Citation",
        "Close",
        "Print",
        "Search ABS",
        "Back to top of the page",
    }

    pieces = []

    for element in main_content.find_all(
        ["h2", "h3", "h4", "p", "li"]
    ):

        text = _clean_text(
            element.get_text(
                " ",
                strip=True,
            )
        )

        if not text:
            continue

        if text in ignored_exact_text:
            continue

        lower_text = text.lower()

        if lower_text.startswith("download graph"):
            continue

        if lower_text.startswith("download table"):
            continue

        if element.name in {"h2", "h3", "h4"}:

            heading_level = {
                "h2": "##",
                "h3": "###",
                "h4": "####",
            }[element.name]

            pieces.append(
                f"{heading_level} {text}"
            )

        else:
            pieces.append(text)

    return "\n\n".join(pieces)



# Table extraction


def _find_table_title(
    table: Tag,
) -> str | None:
    """
    Find a meaningful title associated with a table.
    """

    caption = table.find("caption")

    if caption:

        title = _clean_text(
            caption.get_text(
                " ",
                strip=True,
            )
        )

        if title:
            return title

    # Search backwards for a nearby heading.
    previous_heading = table.find_previous(
        ["h2", "h3", "h4", "h5"]
    )

    if previous_heading:

        title = _clean_text(
            previous_heading.get_text(
                " ",
                strip=True,
            )
        )

        if title:
            return title

    return None


def _extract_tables(
    main_content: Tag,
) -> list[dict]:
    """
    Extract HTML tables from the ABS article.

    Interactive ABS graphs commonly have an associated HTML table.
    The table is retained because it provides exact numerical values
    and is more suitable for downstream LLM analysis than a graph
    screenshot.
    """

    extracted_tables = []

    for index, table in enumerate(
        main_content.find_all("table"),
        start=1,
    ):

        rows = []

        for tr in table.find_all("tr"):

            cells = tr.find_all(
                ["th", "td"]
            )

            row = [
                _clean_text(
                    cell.get_text(
                        " ",
                        strip=True,
                    )
                )
                for cell in cells
            ]

            if row:
                rows.append(row)

        if not rows:
            continue

        first_row_tag = table.find("tr")

        has_header = (
            first_row_tag is not None
            and first_row_tag.find("th") is not None
        )

        if has_header:

            columns = rows[0]
            data_rows = rows[1:]

        else:

            columns = []
            data_rows = rows

        extracted_tables.append(
            {
                "table_id": f"table_{index:02d}",
                "title": _find_table_title(table),
                "columns": columns,
                "rows": data_rows,
            }
        )

    return extracted_tables

# Image helpers
def _find_image_caption(
    image: Tag,
) -> str | None:
    """
    Find a figure caption associated with an image.
    """

    figure = image.find_parent("figure")

    if not figure:
        return None

    caption = figure.find("figcaption")

    if not caption:
        return None

    text = _clean_text(
        caption.get_text(
            " ",
            strip=True,
        )
    )

    return text or None


def _looks_decorative(
    image_url: str,
    alt_text: str,
    caption: str | None,
) -> bool:
    """
    Identify obvious website/decorative images.

    This is intentionally conservative: if an image has useful alt text
    or a caption, it is retained.
    """

    if alt_text or caption:
        return False

    lower_url = image_url.lower()

    decorative_terms = (
        "logo",
        "icon",
        "sprite",
        "favicon",
        "chevron",
        "arrow",
        "search",
        "menu",
    )

    return any(
        term in lower_url
        for term in decorative_terms
    )


def _image_belongs_to_chart(
    image: Tag,
) -> bool:
    """
    Try to identify images that belong to interactive chart components.

    If the surrounding figure/component also contains a table, the image
    does not need to be downloaded because the table is the preferred
    representation.
    """

    figure = image.find_parent("figure")

    if figure and figure.find("table"):
        return True

    # Search a few parent levels for an associated table.
    parent = image.parent

    for _ in range(4):

        if not isinstance(parent, Tag):
            break

        if parent.find("table"):
            return True

        classes = " ".join(
            parent.get("class", [])
        ).lower()

        parent_id = str(
            parent.get("id", "")
        ).lower()

        chart_terms = (
            "chart",
            "graph",
            "visualisation",
            "visualization",
        )

        if any(
            term in classes or term in parent_id
            for term in chart_terms
        ):
            return True

        parent = parent.parent

    return False

# Image extension
def _determine_image_extension(
    image_url: str,
    content_type: str | None,
) -> str:
    """
    Determine an appropriate image file extension.
    """

    if content_type:

        content_type = content_type.split(
            ";",
            1,
        )[0].strip()

        guessed = mimetypes.guess_extension(
            content_type
        )

        if guessed:

            if guessed == ".jpe":
                return ".jpg"

            return guessed

    path_suffix = Path(
        urlparse(image_url).path
    ).suffix.lower()

    if path_suffix in {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".gif",
        ".svg",
    }:
        return path_suffix

    return ".img"

# Download one image
def _download_image(
    image_url: str,
    image_folder: Path,
    image_number: int,
) -> Path | None:
    """
    Download a meaningful ABS article image.

    Returns the local image path or None if downloading fails.
    """

    try:

        response = requests.get(
            image_url,
            headers={
                "User-Agent": USER_AGENT,
            },
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

    except requests.RequestException as exc:

        logger.warning(
            "Could not download image %s: %s",
            image_url,
            exc,
        )

        return None

    content_type = response.headers.get(
        "Content-Type"
    )

    # Avoid accidentally saving an HTML page as an image.
    if (
        content_type
        and not content_type.lower().startswith("image/")
    ):

        logger.warning(
            "Skipping non-image URL %s (Content-Type: %s)",
            image_url,
            content_type,
        )

        return None

    extension = _determine_image_extension(
        image_url,
        content_type,
    )

    image_folder.mkdir(
        parents=True,
        exist_ok=True,
    )

    filename = (
        f"image_{image_number:02d}"
        f"{extension}"
    )

    output_path = (
        image_folder
        / filename
    )

    output_path.write_bytes(
        response.content
    )

    return output_path



# Extract and download meaningful images


def _extract_and_download_images(
    main_content: Tag,
    page_url: str,
    article_id: str,
) -> list[dict]:
    """
    Identify and download meaningful non-chart article images.

    Interactive graph images are skipped where a table is available
    or where the image appears to belong to a chart component.
    """

    image_folder = (
        OUTPUT_DIR
        / f"{article_id}_images"
    )

    extracted_images = []

    seen_urls = set()

    for image in main_content.find_all("img"):

        src = (
            image.get("src")
            or image.get("data-src")
            or image.get("data-lazy-src")
        )

        image_url = _absolute_url(
            src,
            page_url,
        )

        if not image_url:
            continue

        if image_url in seen_urls:
            continue

        seen_urls.add(image_url)

        alt_text = _clean_text(
            image.get(
                "alt",
                "",
            )
        )

        caption = _find_image_caption(
            image
        )

        # Prefer table data over chart screenshots.
        if _image_belongs_to_chart(image):

            logger.info(
                "Skipping graph/chart image because structured "
                "table data is preferred: %s",
                image_url,
            )

            continue

        if _looks_decorative(
            image_url,
            alt_text,
            caption,
        ):

            continue

        image_number = (
            len(extracted_images) + 1
        )

        local_path = _download_image(
            image_url,
            image_folder,
            image_number,
        )

        if local_path is None:
            continue

        extracted_images.append(
            {
                "image_id": (
                    f"image_{image_number:02d}"
                ),
                "source_url": image_url,
                "local_path": local_path,
                "alt_text": (
                    alt_text or None
                ),
                "caption": caption,
            }
        )

    return extracted_images

# Fetch complete ABS article
def fetch_article(
    source: dict,
) -> dict:
    """
    Download and extract one ABS article.

    Returns a structured Python dictionary. The dictionary is
    subsequently formatted as Markdown rather than JSON.
    """

    article_id = source["id"]
    url = source["url"]

    logger.info(
        "Fetching ABS article: %s",
        url,
    )

    html = _download_html(url)

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    title = _extract_title(
        soup
    )

    publication_date = (
        _extract_publication_date(
            soup
        )
    )

    main_content = _get_main_content(
        soup
    )

    # Narrative
    narrative = (
        _extract_narrative_with_trafilatura(
            html
        )
    )

    # BeautifulSoup fallback
    if not narrative:

        logger.warning(
            "Trafilatura could not extract narrative "
            "content. Using BeautifulSoup fallback."
        )

        narrative = (
            _extract_narrative_fallback(
                main_content
            )
        )
    # Tables
    

    tables = _extract_tables(
        main_content
    )

    # Images

    images = (
        _extract_and_download_images(
            main_content,
            url,
            article_id,
        )
    )

    return {
        "id": article_id,
        "source": "ABS",
        "source_name": source.get(
            "name"
        ),
        "url": url,
        "title": title,
        "publication_date": publication_date,
        "fetch_date": datetime.now(
            timezone.utc
        ).isoformat(),
        "narrative": narrative,
        "tables": tables,
        "images": images,
    }

# Markdown table formatting

def _table_to_markdown(
    table: dict,
) -> str:
    """
    Convert one extracted HTML table into Markdown.
    """

    columns = table.get(
        "columns",
        []
    )

    rows = table.get(
        "rows",
        []
    )

    if not columns and not rows:
        return ""

    # If there is no detected header, create generic columns.
    if not columns:

        max_columns = max(
            len(row)
            for row in rows
        )

        columns = [
            f"Column {index}"
            for index in range(
                1,
                max_columns + 1
            )
        ]

    column_count = len(columns)

    normalised_rows = []

    for row in rows:

        row = list(row)

        if len(row) < column_count:

            row.extend(
                [""] * (
                    column_count
                    - len(row)
                )
            )

        elif len(row) > column_count:

            row = row[
                :column_count
            ]

        normalised_rows.append(row)

    header = (
        "| "
        + " | ".join(
            _escape_markdown_cell(
                column
            )
            for column in columns
        )
        + " |"
    )

    separator = (
        "| "
        + " | ".join(
            "---"
            for _ in columns
        )
        + " |"
    )

    markdown_rows = []

    for row in normalised_rows:

        markdown_rows.append(
            "| "
            + " | ".join(
                _escape_markdown_cell(
                    cell
                )
                for cell in row
            )
            + " |"
        )

    return "\n".join(
        [
            header,
            separator,
            *markdown_rows,
        ]
    )

# Complete Markdown formatting
def format_article_as_markdown(
    article: dict,
) -> str:
    """
    Convert an extracted ABS article into a clean Markdown document.
    """

    lines = []
    # Article title
    title = (
        article.get("title")
        or article.get("source_name")
        or article["id"]
    )

    lines.append(
        f"# {title}"
    )

    lines.append("")
    # Metadata
    lines.append(
        "**Source:** Australian Bureau of Statistics (ABS)"
    )

    if article.get(
        "publication_date"
    ):

        lines.append(
            f"**Publication date:** "
            f"{article['publication_date']}"
        )

    lines.append(
        f"**Source URL:** {article['url']}"
    )

    lines.append(
        f"**Retrieved:** {article['fetch_date']}"
    )

    lines.append("")

    lines.append("---")

    lines.append("")
    # Narrative
    lines.append(
        "## Article content"
    )

    lines.append("")

    narrative = article.get(
        "narrative",
        ""
    ).strip()

    if narrative:

        lines.append(
            narrative
        )

    else:

        lines.append(
            "_No narrative text was extracted._"
        )
    # Tables
    tables = article.get(
        "tables",
        []
    )

    if tables:

        lines.append("")

        lines.append("---")

        lines.append("")

        lines.append(
            "## Tables and graph data"
        )

        lines.append("")

        lines.append(
            "The following tables were extracted directly "
            "from the ABS article. Where an interactive graph "
            "has an associated HTML table, the table is used "
            "as the structured representation of the graph data."
        )

        for index, table in enumerate(
            tables,
            start=1,
        ):

            lines.append("")

            title = (
                table.get("title")
                or f"Table {index}"
            )

            lines.append(
                f"### {title}"
            )

            lines.append("")

            table_markdown = (
                _table_to_markdown(
                    table
                )
            )

            if table_markdown:

                lines.append(
                    table_markdown
                )
    # Images

    images = article.get(
        "images",
        []
    )

    if images:

        lines.append("")

        lines.append("---")

        lines.append("")

        lines.append(
            "## Article images"
        )

        lines.append("")

        for index, image in enumerate(
            images,
            start=1,
        ):

            lines.append(
                f"### Image {index}"
            )

            lines.append("")

            local_path = Path(
                image["local_path"]
            )

            # The .md file is saved directly inside OUTPUT_DIR.
            # Therefore the image path can be relative to OUTPUT_DIR.

            relative_path = (
                local_path.relative_to(
                    OUTPUT_DIR
                )
            )

            # Markdown expects forward slashes.
            markdown_path = (
                relative_path
                .as_posix()
            )

            alt_text = (
                image.get("alt_text")
                or image.get("caption")
                or f"ABS article image {index}"
            )

            lines.append(
                f"![{alt_text}]"
                f"({markdown_path})"
            )

            lines.append("")

            if image.get(
                "caption"
            ):

                lines.append(
                    f"**Caption:** "
                    f"{image['caption']}"
                )

                lines.append("")

            if image.get(
                "alt_text"
            ):

                lines.append(
                    f"**Alt text:** "
                    f"{image['alt_text']}"
                )

                lines.append("")

            lines.append(
                f"**Original image source:** "
                f"{image['source_url']}"
            )

            lines.append("")

    return "\n".join(
        lines
    ).strip() + "\n"

# Save Markdown
def save_article(
    article: dict,
) -> Path:
    """
    Save the extracted ABS article as a Markdown file.
    """

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_file = (
        OUTPUT_DIR
        / f"{article['id']}.md"
    )

    markdown = (
        format_article_as_markdown(
            article
        )
    )

    output_file.write_text(
        markdown,
        encoding="utf-8",
    )

    return output_file
# Main program

def main() -> None:
    """
    Run the ABS article ingestion pipeline.
    """

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    try:

        abs_sources = (
            load_abs_sources()
        )

        if not abs_sources:

            raise FetchError(
                "No enabled ABS article sources "
                "were found in config/sources.yaml."
            )

        print(
            f"Found {len(abs_sources)} "
            f"ABS article source(s)."
        )

        successful = 0

        for source in abs_sources:

            print()
            print(
                f"Processing: "
                f"{source.get('name', source['id'])}"
            )

            try:

                article = (
                    fetch_article(
                        source
                    )
                )

                markdown_file = (
                    save_article(
                        article
                    )
                )

            except Exception as exc:
                # One bad article should not prevent other
                # configured ABS articles from being processed.

                logger.error(
                    "Failed to process ABS source '%s': %s",
                    source.get(
                        "id",
                        "unknown",
                    ),
                    exc,
                )

                continue

            successful += 1

            print(
                "ABS article ingestion "
                "completed successfully."
            )

            print(
                "Title:",
                article["title"],
            )

            print(
                "Publication date:",
                article[
                    "publication_date"
                ],
            )

            print(
                "Tables extracted:",
                len(
                    article["tables"]
                ),
            )

            print(
                "Images downloaded:",
                len(
                    article["images"]
                ),
            )

            print(
                "Markdown saved to:",
                markdown_file,
            )

        print()

        print(
            f"Successfully processed "
            f"{successful} of "
            f"{len(abs_sources)} "
            f"ABS article source(s)."
        )

    except FetchError as exc:

        logger.error(
            "%s",
            exc,
        )
# Execute
if __name__ == "__main__":
    main()