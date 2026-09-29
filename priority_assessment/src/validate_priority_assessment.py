import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from jsonschema import Draft202012Validator


class PriorityAssessmentValidationError(ValueError):
    pass


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _format_schema_errors(errors: Iterable[Any]) -> List[str]:
    messages = []
    for error in sorted(errors, key=lambda e: list(e.absolute_path)):
        location = ".".join(str(p) for p in error.absolute_path) or "$"
        messages.append(f"{location}: {error.message}")
    return messages


def validate_priority_assessment_results(
    results: Dict[str, Any],
    expected_ids: List[str],
    item_schema: Dict[str, Any],
) -> None:
    if not isinstance(results, dict):
        raise PriorityAssessmentValidationError("Priority Assessment result must be a JSON object")

    if set(results.keys()) != {"assessments"}:
        raise PriorityAssessmentValidationError(
            "Article-mode output must contain exactly one top-level key: assessments"
        )

    assessments = results.get("assessments")
    if not isinstance(assessments, list):
        raise PriorityAssessmentValidationError("assessments must be a list")

    validator = Draft202012Validator(item_schema)
    schema_messages: List[str] = []
    ids: List[str] = []

    for index, assessment in enumerate(assessments):
        errors = list(validator.iter_errors(assessment))
        for message in _format_schema_errors(errors):
            schema_messages.append(f"assessments[{index}].{message}")
        if isinstance(assessment, dict):
            ids.append(assessment.get("insight_id"))

    if schema_messages:
        raise PriorityAssessmentValidationError(
            "Schema validation failed:\n- " + "\n- ".join(schema_messages)
        )

    duplicates = sorted({x for x in ids if x is not None and ids.count(x) > 1})
    if duplicates:
        raise PriorityAssessmentValidationError(
            f"Duplicate assessment insight_id values: {duplicates}"
        )

    expected_set = set(expected_ids)
    actual_set = set(ids)
    missing = [x for x in expected_ids if x not in actual_set]
    unexpected = [x for x in ids if x not in expected_set]
    if missing or unexpected or len(ids) != len(expected_ids):
        raise PriorityAssessmentValidationError(
            "Assessment ID mismatch. "
            f"Expected {len(expected_ids)}, received {len(ids)}; "
            f"missing={missing}; unexpected={unexpected}"
        )

    # Article mode requires one-for-one output in the same input order.
    if ids != expected_ids:
        raise PriorityAssessmentValidationError(
            "Assessment order must match the input insight order exactly"
        )

    cross_field_errors = []
    for assessment in assessments:
        insight_id = assessment["insight_id"]
        relevance = assessment["relevance"]
        priority = assessment["priority"]

        if relevance == "Not relevant" and priority != "Not Applicable":
            cross_field_errors.append(
                f"{insight_id}: Not relevant requires Not Applicable"
            )
        elif relevance == "Relevant" and priority == "Not Applicable":
            cross_field_errors.append(
                f"{insight_id}: Relevant cannot use Not Applicable"
            )
        elif relevance == "Uncertain" and priority not in {
            "Watchlist",
            "Informational",
        }:
            cross_field_errors.append(
                f"{insight_id}: Uncertain must be Watchlist or Informational"
            )

        if priority == "Not Applicable" and relevance != "Not relevant":
            cross_field_errors.append(
                f"{insight_id}: Not Applicable is only valid when relevance is Not relevant"
            )

    if cross_field_errors:
        raise PriorityAssessmentValidationError(
            "Cross-field validation failed:\n- " + "\n- ".join(cross_field_errors)
        )


def validate_files(
    input_path: Path,
    results_path: Path,
    schema_path: Path,
) -> Dict[str, Any]:
    article_input = load_json(input_path)
    results = load_json(results_path)
    item_schema = load_json(schema_path)

    insights = article_input.get("insights")
    if not isinstance(insights, list):
        raise PriorityAssessmentValidationError("Priority Assessment input is missing insights[]")
    expected_ids = [x.get("insight_id") for x in insights]
    if any(not x for x in expected_ids):
        raise PriorityAssessmentValidationError("Priority Assessment input contains a missing insight_id")

    validate_priority_assessment_results(results, expected_ids, item_schema)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Priority Assessment article-mode output.")
    parser.add_argument("input_json", type=Path, help="Clean article-mode Priority Assessment input")
    parser.add_argument("results_json", type=Path, help="Priority Assessment article-mode results")
    parser.add_argument("schema_json", type=Path, help="Single-assessment schema")
    args = parser.parse_args()

    validate_files(args.input_json, args.results_json, args.schema_json)
    print("Priority Assessment validation passed")


if __name__ == "__main__":
    main()
