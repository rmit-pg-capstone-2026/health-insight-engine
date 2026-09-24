from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

CASE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
VERSION = "0.2.1"


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, data: dict):
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("case_id")
    p.add_argument("--cases-root", default="cases")
    args = p.parse_args()

    if (
        not CASE_ID_RE.fullmatch(args.case_id)
        or ".." in args.case_id
        or "/" in args.case_id
        or "\\" in args.case_id
    ):
        print("ERROR: invalid case_id", file=sys.stderr)
        return 1

    case = Path(args.cases_root) / args.case_id
    if case.exists():
        print(f"ERROR: case already exists: {case}", file=sys.stderr)
        return 1

    for d in ("source", "frozen", "human_reference", "raw_outputs", "generated"):
        (case / d).mkdir(parents=True, exist_ok=False)

    write_json(
        case / "case_manifest.json",
        {
            "case_id": args.case_id,
            "case_status": "SETUP",
            "created_at": now_utc(),
            "source_status": "NOT_CAPTURED",
            "frozen_source_version": None,
            "frozen_source_manifest": None,
            "source_automation_version": VERSION,
        },
    )

    write_json(
        case / "source" / "source_metadata.json",
        {
            "case_id": args.case_id,
            "title": "",
            "organisation": "",
            "source_url": "",
            "retrieval_date": "",
            "retrieved_at": "",
            "publication_date": None,
            "last_updated_date": None,
            "visible_version_date": None,
            "visible_version": None,
            "reference_period": None,
            "source_version": "v1",
            "capture_method": "",
            "capture_script_version": "",
            "raw_source_filename": "",
            "test_input_draft_filename": "",
            "human_verified": False,
            "interactive_content": {
                "detected": False,
                "capture_required": False,
                "status": "NOT_CAPTURED",
                "human_review_required": False,
            },
            "notes": "",
        },
    )

    print("CASE CREATED SUCCESSFULLY")
    print(f"Source automation version: {VERSION}")
    print(case.resolve())
    print(f'Next: py capture_source.py "{case}" --url "PASTE_OFFICIAL_URL_HERE"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
