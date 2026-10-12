import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple


HANDOFF_REQUIRED_FIELDS = (
    "insight_type",
    "finding",
    "evidence",
    "evidence_location",
)


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("Prompt 1 output must be a JSON object")
    return data


def build_assessment_article_input(
    input_path: Path,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Convert Prompt 1 output into the agreed article-mode Priority Assessment handoff.

    Upstream QA is consumed before Prompt 1 reasoning/debug fields are stripped.
    Explicit source-grounding failures are quarantined for review.
    """
    raw = _load_json(input_path)
    result = raw.get("result", {})
    if not isinstance(result, dict):
        raise ValueError("Missing or invalid result object")

    schema_errors = raw.get("schema_errors", [])
    if schema_errors:
        raise ValueError(f"Prompt 1 output contains schema errors: {schema_errors}")

    source = result.get("source")
    summary = result.get("summary")
    insights = result.get("insights", [])
    quote_checks = raw.get("quote_checks", [])

    if not isinstance(source, dict):
        raise ValueError("Missing or invalid result.source")
    if summary is not None and not isinstance(summary, str):
        raise ValueError("result.summary must be a string or null")
    if not isinstance(insights, list):
        raise ValueError("Missing or invalid result.insights")
    if not isinstance(quote_checks, list):
        raise ValueError("quote_checks must be a list when present")

    clean_source = {
        "publisher": source.get("publisher"),
        "title": source.get("title"),
        "url": source.get("url"),
        "publication_date": source.get("publication_date"),
        "retrieval_date": source.get("retrieval_date"),
    }

    quote_check_by_index = {
        q.get("index"): q
        for q in quote_checks
        if isinstance(q, dict) and isinstance(q.get("index"), int)
    }

    clean_insights: List[Dict[str, Any]] = []
    review_required: List[Dict[str, Any]] = []
    seen_ids = set()

    for index, insight in enumerate(insights):
        if not isinstance(insight, dict):
            raise ValueError(f"Insight at index {index} must be an object")

        insight_id = insight.get("insight_id")
        if not insight_id:
            raise ValueError(f"Insight at index {index} has no insight_id")
        if insight_id in seen_ids:
            raise ValueError(f"Duplicate insight_id: {insight_id}")
        seen_ids.add(insight_id)

        # Keep the existing hard handoff requirements, but treat a missing
        # evidence locator as reviewable rather than failing the whole article.
        missing = [
            field
            for field in HANDOFF_REQUIRED_FIELDS
            if field != "evidence_location" and insight.get(field) in (None, "")
        ]
        if missing:
            raise ValueError(
                f"{insight_id} is missing required handoff fields: {missing}"
            )

        clean_record = {
            "insight_id": insight_id,
            "insight_type": insight.get("insight_type"),
            "finding": insight.get("finding"),
            "evidence": insight.get("evidence"),
            "evidence_location": insight.get("evidence_location"),
            "target_population": insight.get("target_population"),
            "caveat": insight.get("caveat"),
        }

        quote_check = quote_check_by_index.get(index)
        if quote_check and quote_check.get("found_in_source") is False:
            review_required.append(
                {
                    "insight_id": insight_id,
                    "reason": "Prompt 1 quote check: found_in_source = false",
                    "upstream_qa": {
                        "index": index,
                        "found_in_source": False,
                        "fragments_missing": quote_check.get("fragments_missing", []),
                    },
                    "assessment_input": clean_record,
                }
            )
            continue

        evidence_location = insight.get("evidence_location")
        if not isinstance(evidence_location, str) or not evidence_location.strip():
            review_required.append(
                {
                    "insight_id": insight_id,
                    "reason": "Missing or blank evidence_location",
                    "assessment_input": clean_record,
                }
            )
            continue

        clean_insights.append(clean_record)

    article_input = {
        "source": clean_source,
        "summary": summary,
        "insights": clean_insights,
    }
    return article_input, review_required


def write_outputs(
    input_path: Path,
    output_path: Path,
    review_output_path: Path,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    article_input, review_required = build_assessment_article_input(input_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    review_output_path.parent.mkdir(parents=True, exist_ok=True)

    output_path.write_text(
        json.dumps(article_input, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    review_output_path.write_text(
        json.dumps(review_required, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return article_input, review_required


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare article-mode Priority Assessment input from Prompt 1 JSON."
    )
    parser.add_argument("input_json", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("assessment_input.json"),
    )
    parser.add_argument(
        "--review-output",
        type=Path,
        default=Path("assessment_review_required.json"),
    )
    args = parser.parse_args()

    article_input, review_required = write_outputs(
        args.input_json, args.output, args.review_output
    )

    print(f"Priority Assessment ready: {len(article_input['insights'])} insights")
    print(f"Review required: {len(review_required)} insights")
    print(f"Saved: {args.output}")
    print(f"Saved: {args.review_output}")


if __name__ == "__main__":
    main()
