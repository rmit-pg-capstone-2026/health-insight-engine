import json
import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aggregate_assessed_insights import aggregate_assessed_insights
from consolidate_insights import consolidate_insights
from prepare_assessment_input import build_assessment_article_input
from validate_priority_assessment import validate_priority_assessment_results


def make_assessment(insight_id, priority="Informational", relevance="Relevant"):
    return {
        "insight_id": insight_id,
        "relevance": relevance,
        "criteria": {
            "clinical_significance": "Unclear",
            "utilisation_demand": "Unclear",
            "population_affected": "Unclear",
            "magnitude_of_change": "Unclear",
            "cost_implications": "Unclear",
            "private_health_relevance": "Unclear",
            "trend_continuity": "Unclear",
            "emerging_treatment_or_technology": "Unclear",
            "evidence_strength": "High",
            "actionability": "Low",
        },
        "priority": priority,
        "priority_rationale": "Structural smoke-test fixture only.",
    }


def main():
    prompt1 = ROOT / "data" / "raw" / "deepseek_prompt1_output.json"
    schema = json.loads((ROOT / "schemas" / "priority_assessment_schema_v0.1.json").read_text())

    article_input, review = build_assessment_article_input(prompt1)
    assert len(article_input["insights"]) == 9
    assert [x["insight_id"] for x in review] == ["INSIGHT_008"]
    assert all("reasoning" not in x for x in article_input["insights"])

    results = {
        "assessments": [
            make_assessment(x["insight_id"]) for x in article_input["insights"]
        ]
    }
    expected_ids = [x["insight_id"] for x in article_input["insights"]]
    validate_priority_assessment_results(results, expected_ids, schema)

    assessed = aggregate_assessed_insights(article_input, results)
    briefing = consolidate_insights(assessed)
    assert len(briefing["insights"]) == 9
    assert "INSIGHT_001" in briefing["section_index"]["pharmaceutical"]
    assert "INSIGHT_002" in briefing["section_index"]["clinical"]
    print("Smoke test passed: preprocessing, validation, aggregation and consolidation")


if __name__ == "__main__":
    main()
