import argparse
import json
from pathlib import Path
from typing import Any, Dict


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def aggregate_assessed_insights(
    article_input: Dict[str, Any],
    assessment_results: Dict[str, Any],
    priority_assessment_version: str = "v0.4.3_article",
) -> Dict[str, Any]:
    insights = article_input.get("insights", [])
    assessments = assessment_results.get("assessments", [])

    assessment_by_id = {a["insight_id"]: a for a in assessments}
    assessed_insights = []

    for insight in insights:
        insight_id = insight["insight_id"]
        if insight_id not in assessment_by_id:
            raise ValueError(f"Missing validated assessment for {insight_id}")
        assessment = assessment_by_id[insight_id]

        assessed = dict(insight)
        assessed.update(
            {
                "relevance": assessment["relevance"],
                "criteria": assessment["criteria"],
                "priority": assessment["priority"],
                "priority_rationale": assessment["priority_rationale"],
            }
        )
        assessed_insights.append(assessed)

    return {
        "source": article_input.get("source"),
        "summary": article_input.get("summary"),
        "priority_assessment_version": priority_assessment_version,
        "assessed_insights": assessed_insights,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Join Priority Assessment assessments back to source-grounded insight records."
    )
    parser.add_argument("input_json", type=Path)
    parser.add_argument("results_json", type=Path)
    parser.add_argument("--output", type=Path, default=Path("assessed_insights.json"))
    parser.add_argument("--priority-assessment-version", default="v0.4.3_article")
    args = parser.parse_args()

    aggregated = aggregate_assessed_insights(
        load_json(args.input_json),
        load_json(args.results_json),
        args.priority_assessment_version,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(aggregated, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
