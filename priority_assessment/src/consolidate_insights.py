import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


PRIORITY_ORDER = {
    "High Priority": 0,
    "Medium Priority": 1,
    "Watchlist": 2,
    "Informational": 3,
    "Not Applicable": 4,
}

# Prompt 1 provides the three top-level insight domains used by the briefing.
# Watchlist is not an insight_type; it is a separate briefing bucket derived
# from Priority Assessment priority == "Watchlist".
SECTION_KEYS = (
    "clinical",
    "pharmaceutical",
    "medical_technology",
    "watchlist",
)

INSIGHT_TYPE_TO_SECTION = {
    "clinical": "clinical",
    "pharmaceutical": "pharmaceutical",
    "medical technology": "medical_technology",
    "medical_technology": "medical_technology",
}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _section_for_type(insight_type: str) -> str:
    key = str(insight_type).strip().lower()
    if key not in INSIGHT_TYPE_TO_SECTION:
        raise ValueError(
            f"Unsupported insight_type {insight_type!r}; expected clinical, pharmaceutical, or medical technology"
        )
    return INSIGHT_TYPE_TO_SECTION[key]


def consolidate_insights(
    assessed: Dict[str, Any],
    consolidation_version: str = "v0.1",
) -> Dict[str, Any]:
    source_insights = assessed.get("assessed_insights", [])
    if not isinstance(source_insights, list):
        raise ValueError("assessed_insights must be a list")

    kept: List[Dict[str, Any]] = []
    for insight in source_insights:
        if insight.get("relevance") == "Not relevant":
            continue
        if insight.get("priority") == "Not Applicable":
            continue
        kept.append(dict(insight))

    # Python sort is stable, so source order is retained within a priority band.
    kept.sort(key=lambda x: PRIORITY_ORDER[x["priority"]])

    section_index: Dict[str, List[str]] = {key: [] for key in SECTION_KEYS}
    for insight in kept:
        insight_id = insight["insight_id"]

        # Watchlist is determined by Priority Assessment priority, not Prompt 1 insight_type.
        # Route it to the dedicated briefing watchlist rather than duplicating it
        # in its original domain section.
        if insight["priority"] == "Watchlist":
            section_index["watchlist"].append(insight_id)
            continue

        section = _section_for_type(insight["insight_type"])
        section_index[section].append(insight_id)

    return {
        "source": assessed.get("source"),
        "summary": assessed.get("summary"),
        "priority_assessment_version": assessed.get("priority_assessment_version"),
        "consolidation_version": consolidation_version,
        "insights": kept,
        "section_index": section_index,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create deterministic Week 9 briefing-ready JSON."
    )
    parser.add_argument("assessed_json", type=Path)
    parser.add_argument("--output", type=Path, default=Path("briefing_input.json"))
    parser.add_argument("--version", default="v0.1")
    args = parser.parse_args()

    briefing_input = consolidate_insights(load_json(args.assessed_json), args.version)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(briefing_input, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
