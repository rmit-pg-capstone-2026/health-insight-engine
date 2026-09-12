"""
ABS article ingestion module for the RMIT x Medibank Health Insight Engine.

1. Downloads an ABS article webpage.
2. Extracts article metadata.
3. Extracts clean narrative sections.
4. Extracts HTML tables as structured data.
5. Extracts image metadata.
6. Saves everything into a structured JSON file.

"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag


# ============================================================
# Configuration
# ============================================================

ARTICLE_URL = (
    "https://www.abs.gov.au/articles/"
    "childrens-physical-activity-screen-time-and-sleep"
)

USER_AGENT = (
    "health-insight-engine/0.1 "
    "(RMIT x Medibank capstone; research use)"
)

REQUEST_TIMEOUT = 30

OUTPUT_DIR = Path("data") / "raw" / "abs"


# ============================================================
# Logging
# ============================================================

logger = logging.getLogger(__name__)


# ============================================================
# Custom error
# ============================================================

class FetchError(RuntimeError):
    """Raised when an ABS article cannot be downloaded or extracted."""


# ============================================================
# Helper functions
# ============================================================

def _clean_text(text: str) -> str:
    """
    Clean unnecessary whitespace from extracted text.
    """

    text = text.replace("\xa0", " ")

    text = re.sub(
        r"[ \t]+",
        " ",
        text
    )

    text = re.sub(
        r"\n\s*\n+",
        "\n",
        text
    )

    return text.strip()


def _make_absolute_url(
    url: str | None,
    base_url: str
) -> str | None:
    """
    Convert relative ABS URLs into complete URLs.
    """

    if not url:
        return None

    return urljoin(base_url, url)


# ============================================================
# Download HTML
# ============================================================

def _download_html(url: str) -> str:
    """
    Download the raw HTML for an ABS article.
    """

    headers = {
        "User-Agent": USER_AGENT
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()

    except requests.RequestException as exc:
        raise FetchError(
            f"Failed to download ABS article: {url}"
        ) from exc

    return response.text


# ============================================================
# Metadata extraction
# ============================================================

def _extract_title(
    soup: BeautifulSoup
) -> str | None:
    """
    Extract the ABS article title.
    """

    heading = soup.find("h1")

    if heading:
        return _clean_text(
            heading.get_text(" ", strip=True)
        )

    if soup.title:
        return _clean_text(
            soup.title.get_text(" ", strip=True)
        )

    return None


def _extract_publication_date(
    soup: BeautifulSoup
) -> str | None:
    """
    Extract the publication/release date.

    ABS commonly displays dates in a form such as:
    Released 30/06/2026
    """

    # First try a <time> element
    time_element = soup.find("time")

    if time_element:

        datetime_value = time_element.get("datetime")

        if datetime_value:
            return datetime_value.strip()

        text = time_element.get_text(
            " ",
            strip=True
        )

        if text:
            return _clean_text(text)

    # Fallback: search visible page text
    page_text = soup.get_text(
        " ",
        strip=True
    )

    match = re.search(
        r"Released\s+(\d{1,2}/\d{1,2}/\d{4})",
        page_text,
        flags=re.IGNORECASE
    )

    if match:
        return match.group(1)

    return None


# ============================================================
# Main article container
# ============================================================

def _get_main_content(
    soup: BeautifulSoup
) -> Tag:
    """
    Locate the main article content on the ABS webpage.
    """

    main_content = soup.find("main")

    if main_content is None:
        main_content = soup.find("article")

    if main_content is None:
        raise FetchError(
            "Could not locate the main ABS article content."
        )

    return main_content


# ============================================================
# Remove unwanted webpage elements
# ============================================================

def _remove_unwanted_elements(
    main_content: Tag
) -> None:
    """
    Remove webpage elements that are not useful
    for later LLM analysis.
    """

    unwanted_tags = [
        "script",
        "style",
        "noscript",
        "nav",
        "footer",
        "form",
        "button"
    ]

    for tag_name in unwanted_tags:

        for element in main_content.find_all(tag_name):
            element.decompose()


# ============================================================
# Narrative section extraction
# ============================================================

def _extract_sections(
    main_content: Tag
) -> list[dict]:
    """
    Extract narrative content grouped under headings.

    Each section contains:
    - heading
    - text
    """

    sections = []

    current_heading = "Introduction"
    current_text = []

    # Text that comes from ABS webpage controls rather than
    # meaningful article content
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
        "Back to top of the page"
    }

    useful_tags = main_content.find_all(
        [
            "h2",
            "h3",
            "h4",
            "p",
            "li"
        ]
    )

    for element in useful_tags:

        text = _clean_text(
            element.get_text(
                " ",
                strip=True
            )
        )

        if not text:
            continue

        if text in ignored_exact_text:
            continue

        # Ignore download-related webpage controls
        if text.lower().startswith(
            "download graph"
        ):
            continue

        if text.lower().startswith(
            "download table"
        ):
            continue

        # New section heading
        if element.name in {
            "h2",
            "h3",
            "h4"
        }:

            # Save previous section first
            if current_text:

                section_text = "\n".join(
                    current_text
                ).strip()

                if section_text:
                    sections.append(
                        {
                            "heading": current_heading,
                            "text": section_text
                        }
                    )

            current_heading = text
            current_text = []

        else:

            # Prevent duplicate nested list text
            if (
                current_text
                and text == current_text[-1]
            ):
                continue

            current_text.append(text)

    # Save final section
    if current_text:

        section_text = "\n".join(
            current_text
        ).strip()

        if section_text:

            sections.append(
                {
                    "heading": current_heading,
                    "text": section_text
                }
            )

    return sections


# ============================================================
# Table extraction
# ============================================================

def _find_table_title(
    table: Tag
) -> str | None:
    """
    Attempt to identify a meaningful title
    associated with an HTML table.
    """

    caption = table.find("caption")

    if caption:

        title = _clean_text(
            caption.get_text(
                " ",
                strip=True
            )
        )

        if title:
            return title

    # ABS sometimes places the chart/table title
    # immediately before the table.
    previous = table.find_previous(
        [
            "h2",
            "h3",
            "h4",
            "p"
        ]
    )

    if previous:

        title = _clean_text(
            previous.get_text(
                " ",
                strip=True
            )
        )

        if title:
            return title

    return None


def _extract_tables(
    main_content: Tag
) -> list[dict]:
    """
    Extract HTML tables into structured JSON.

    Each table contains:
    - table_id
    - title
    - columns
    - rows
    """

    extracted_tables = []

    tables = main_content.find_all("table")

    for index, table in enumerate(
        tables,
        start=1
    ):

        table_id = f"table_{index:02d}"

        title = _find_table_title(table)

        rows = []

        for tr in table.find_all("tr"):

            cells = tr.find_all(
                ["th", "td"]
            )

            row = [
                _clean_text(
                    cell.get_text(
                        " ",
                        strip=True
                    )
                )
                for cell in cells
            ]

            if row:
                rows.append(row)

        if not rows:
            continue

        # Try to use the first row as columns if
        # it contains table headings.
        first_row = table.find("tr")

        has_header = (
            first_row is not None
            and first_row.find("th") is not None
        )

        if has_header:

            columns = rows[0]
            data_rows = rows[1:]

        else:

            columns = []
            data_rows = rows

        extracted_tables.append(
            {
                "table_id": table_id,
                "title": title,
                "columns": columns,
                "rows": data_rows
            }
        )

    return extracted_tables


# ============================================================
# Image extraction
# ============================================================

def _find_image_caption(
    image: Tag
) -> str | None:
    """
    Try to identify a caption associated with an image.
    """

    figure = image.find_parent("figure")

    if figure:

        figcaption = figure.find(
            "figcaption"
        )

        if figcaption:

            caption = _clean_text(
                figcaption.get_text(
                    " ",
                    strip=True
                )
            )

            if caption:
                return caption

    return None


def _extract_images(
    main_content: Tag,
    page_url: str
) -> list[dict]:
    """
    Extract useful metadata for images.

    Images are not downloaded in this version.

    Each image contains:
    - image_id
    - url
    - alt_text
    - caption
    """

    extracted_images = []

    seen_urls = set()

    images = main_content.find_all("img")

    for image in images:

        src = (
            image.get("src")
            or image.get("data-src")
            or image.get("data-lazy-src")
        )

        image_url = _make_absolute_url(
            src,
            page_url
        )

        if not image_url:
            continue

        # Avoid storing duplicate images
        if image_url in seen_urls:
            continue

        seen_urls.add(image_url)

        alt_text = _clean_text(
            image.get(
                "alt",
                ""
            )
        )

        caption = _find_image_caption(
            image
        )

        # Skip obvious decorative images when there is
        # no useful descriptive information.
        if not alt_text and not caption:

            lower_url = image_url.lower()

            decorative_terms = [
                "logo",
                "icon",
                "sprite"
            ]

            if any(
                term in lower_url
                for term in decorative_terms
            ):
                continue

        image_id = (
            f"image_{len(extracted_images) + 1:02d}"
        )

        extracted_images.append(
            {
                "image_id": image_id,
                "url": image_url,
                "alt_text": alt_text or None,
                "caption": caption
            }
        )

    return extracted_images


# ============================================================
# Extract one complete ABS article
# ============================================================

def fetch_article(
    url: str
) -> dict:
    """
    Download and extract one ABS article.

    Returns structured content suitable
    for later processing by an LLM pipeline.
    """

    logger.info(
        "Fetching ABS article: %s",
        url
    )

    html = _download_html(url)

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    title = _extract_title(soup)

    publication_date = (
        _extract_publication_date(soup)
    )

    main_content = _get_main_content(
        soup
    )

    _remove_unwanted_elements(
        main_content
    )

    sections = _extract_sections(
        main_content
    )

    tables = _extract_tables(
        main_content
    )

    images = _extract_images(
        main_content,
        url
    )

    article = {
        "source": "ABS",
        "url": url,
        "title": title,
        "publication_date": publication_date,
        "fetch_date": datetime.now(
            timezone.utc
        ).isoformat(),
        "content": {
            "sections": sections,
            "tables": tables,
            "images": images
        },
        "extraction_summary": {
            "number_of_sections": len(
                sections
            ),
            "number_of_tables": len(
                tables
            ),
            "number_of_images": len(
                images
            )
        }
    }

    return article

# ============================================================
# Save structured JSON
# ============================================================

def save_article(
    article: dict,
    filename: str
) -> Path:
    """
    Save the structured article as JSON.
    """

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    output_file = (
        OUTPUT_DIR
        / f"{filename}.json"
    )

    with output_file.open(
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            article,
            file,
            indent=2,
            ensure_ascii=False
        )

    return output_file


# ============================================================
# Main program
# ============================================================

def main() -> None:
    """
    Run the ABS article ingestion pipeline.
    """

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s"
    )

    filename = (
        "childrens-physical-activity-"
        "screen-time-and-sleep"
    )

    try:

        article = fetch_article(
            ARTICLE_URL
        )

        json_file = save_article(
            article,
            filename
        )

        print()
        print(
            "ABS article ingestion completed successfully."
        )

        print(
            "Title:",
            article["title"]
        )

        print(
            "Publication date:",
            article["publication_date"]
        )

        print(
            "Sections extracted:",
            article[
                "extraction_summary"
            ]["number_of_sections"]
        )

        print(
            "Tables extracted:",
            article[
                "extraction_summary"
            ]["number_of_tables"]
        )

        print(
            "Images identified:",
            article[
                "extraction_summary"
            ]["number_of_images"]
        )

        print(
            "JSON saved to:",
            json_file
        )
    except FetchError as exc:

        logger.error(
            "%s",
            exc
        )


# ============================================================
# Execute
# ============================================================

if __name__ == "__main__":
    main()