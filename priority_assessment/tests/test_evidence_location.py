import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from prepare_assessment_input import build_assessment_article_input


def main():
    fixture = {
        "schema_errors": [],
        "result": {
            "source": {
                "publisher": "AIHW",
                "title": "Evidence location regression test",
                "url": "https://example.test/article",
                "publication_date": "2026-01-01",
                "retrieval_date": "2026-01-02",
            },
            "summary": "Regression-test fixture.",
            "insights": [
                {
                    "insight_id": "INSIGHT_001",
                    "insight_type": "Clinical",
                    "finding": "Valid location.",
                    "evidence": "Evidence one.",
                    "evidence_location": "Section 1",
                    "target_population": None,
                    "caveat": None,
                },
                {
                    "insight_id": "INSIGHT_002",
                    "insight_type": "Clinical",
                    "finding": "Null location.",
                    "evidence": "Evidence two.",
                    "evidence_location": None,
                    "target_population": None,
                    "caveat": None,
                },
                {
                    "insight_id": "INSIGHT_003",
                    "insight_type": "Clinical",
                    "finding": "Empty location.",
                    "evidence": "Evidence three.",
                    "evidence_location": "",
                    "target_population": None,
                    "caveat": None,
                },
                {
                    "insight_id": "INSIGHT_004",
                    "insight_type": "Clinical",
                    "finding": "Whitespace location.",
                    "evidence": "Evidence four.",
                    "evidence_location": "   ",
                    "target_population": None,
                    "caveat": None,
                },
                {
                    "insight_id": "INSIGHT_005",
                    "insight_type": "Clinical",
                    "finding": "Quote failure.",
                    "evidence": "Evidence five.",
                    "evidence_location": None,
                    "target_population": None,
                    "caveat": None,
                },
            ],
        },
        "quote_checks": [
            {"index": 0, "found_in_source": True},
            {"index": 1, "found_in_source": True},
            {"index": 2, "found_in_source": True},
            {"index": 3, "found_in_source": True},
            {
                "index": 4,
                "found_in_source": False,
                "fragments_missing": ["Evidence five."],
            },
        ],
    }

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "fixture.json"
        path.write_text(json.dumps(fixture), encoding="utf-8")

        article, review = build_assessment_article_input(path)

    assert [x["insight_id"] for x in article["insights"]] == [
        "INSIGHT_001"
    ]

    assert [x["insight_id"] for x in review] == [
        "INSIGHT_002",
        "INSIGHT_003",
        "INSIGHT_004",
        "INSIGHT_005",
    ]

    assert all(
        x["reason"] == "Missing or blank evidence_location"
        for x in review[:3]
    )

    assert (
        review[3]["reason"]
        == "Prompt 1 quote check: found_in_source = false"
    )

    print("Evidence-location regression passed")


if __name__ == "__main__":
    main()