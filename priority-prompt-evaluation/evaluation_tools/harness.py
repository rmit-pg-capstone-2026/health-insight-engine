#!/usr/bin/env python3
"""
Medibank Evaluation Harness v0.1

Deterministic file-check, JSON/schema validation, SHA-256 integrity,
and blinded anonymisation only. Does NOT perform LLM scoring.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import secrets
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

HARNESS_VERSION = "0.1.0"

FROZEN_FILES = [
    "Prompt_v1_Evaluation_Rubric_v1.md",
    "Prompt_v1_Acceptance_Criteria_v0.md",
    "Medibank_LLM_Relevance_Priority_Schema_v1_corrected.json",
    "ABS_Acute_Respiratory_2026_07_Reference_Answer_v1.md",
    "abs_acute_respiratory_2026_07_Test_Input_v1.md",
]

RAW_OUTPUT_FILES = [
    "Case2_A1_Claude_Opus5_Medium.md",
    "Case2_A2_Claude_Opus5_Medium.md",
    "Case2_A3_Claude_Opus5_Medium.md",
    "Case2_B1_GPT6_Astra_Medium.md",
    "Case2_B2_GPT6_Astra_Medium.md",
    "Case2_B3_GPT6_Astra_Medium.md",
]

SCHEMA_FILENAME = "Medibank_LLM_Relevance_Priority_Schema_v1_corrected.json"

GENERATED_ARTIFACTS = [
    "private_mapping.json",
    "validation_report.md",
    "blinded_scoring_package",
] + [f"Output_{i:02d}.md" for i in range(1, 7)]


def check_required_files(case_dir: Path) -> list[str]:
    """Return a list of missing required file paths (relative to case_dir)."""
    missing: list[str] = []
    frozen_dir = case_dir / "frozen"
    raw_dir = case_dir / "raw_outputs"

    for name in FROZEN_FILES:
        path = frozen_dir / name
        if not path.is_file():
            missing.append(str(path.relative_to(case_dir)))

    for name in RAW_OUTPUT_FILES:
        path = raw_dir / name
        if not path.is_file():
            missing.append(str(path.relative_to(case_dir)))

    return missing


def sha256_file(path: Path) -> str:
    """Return the SHA-256 hex digest of a file's exact bytes."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _find_fenced_json_blocks(text: str) -> list[str]:
    """Return contents of ```json ... ``` fenced blocks (conservative)."""
    blocks: list[str] = []
    lines = text.splitlines(keepends=True)
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped.startswith("```") and stripped[3:].strip().lower().startswith("json"):
            i += 1
            body: list[str] = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                body.append(lines[i])
                i += 1
            if i < len(lines) and lines[i].strip().startswith("```"):
                blocks.append("".join(body).strip())
                i += 1
                continue
            # Unclosed fence — ignore this attempt
            break
        i += 1
    return blocks


def _decode_top_level_objects(text: str) -> list[Any]:
    """
    Find top-level JSON objects using JSONDecoder.raw_decode.

    Scans for '{' and attempts decode. Collects distinct successful objects.
    Fails later if more than one plausible object is found.
    """
    decoder = json.JSONDecoder()
    objects: list[Any] = []
    starts: list[int] = []
    idx = 0
    while idx < len(text):
        if text[idx] == "{":
            try:
                obj, end = decoder.raw_decode(text, idx)
            except json.JSONDecodeError:
                idx += 1
                continue
            if isinstance(obj, dict):
                objects.append(obj)
                starts.append(idx)
            idx = max(end, idx + 1)
        else:
            idx += 1
    return objects


def extract_json(text: str) -> tuple[Any | None, str | None]:
    """
    Conservatively extract one JSON value from raw output text.

    Returns (parsed_object, error_message). error_message is None on success.
    """
    trimmed = text.strip()
    if not trimmed:
        return None, "File is empty; no JSON found."

    # Strategy A: whole file is JSON
    try:
        return json.loads(trimmed), None
    except json.JSONDecodeError:
        pass

    # Strategy B: fenced ```json block
    fenced = _find_fenced_json_blocks(trimmed)
    if len(fenced) == 1:
        try:
            return json.loads(fenced[0]), None
        except json.JSONDecodeError as exc:
            return None, f"Fenced JSON block is malformed: {exc}"
    if len(fenced) > 1:
        return None, (
            f"Found {len(fenced)} fenced ```json blocks; "
            "refusing to guess which one to use."
        )

    # Strategy C: one top-level object via raw_decode
    objects = _decode_top_level_objects(trimmed)
    if len(objects) == 1:
        return objects[0], None
    if len(objects) == 0:
        return None, "No valid JSON object could be extracted."
    return None, (
        f"Found {len(objects)} plausible top-level JSON objects; "
        "refusing to guess which one to use."
    )


def validate_output(
    raw_path: Path,
    schema: dict[str, Any],
) -> dict[str, Any]:
    """Validate one raw output: JSON parse + schema. Never mutates the file."""
    file_hash = sha256_file(raw_path)
    result: dict[str, Any] = {
        "filename": raw_path.name,
        "sha256": file_hash,
        "json_parse": "FAIL",
        "schema_validation": "FAIL",
        "schema_errors": [],
        "parse_error": None,
        "parsed": None,
    }

    try:
        text = raw_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        result["parse_error"] = f"Could not decode file as UTF-8: {exc}"
        return result

    parsed, parse_error = extract_json(text)
    if parse_error is not None:
        result["parse_error"] = parse_error
        return result

    result["json_parse"] = "PASS"
    result["parsed"] = parsed

    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(parsed), key=lambda e: list(e.path))
    if errors:
        for err in errors:
            path = "$"
            if err.absolute_path:
                path = "$." + ".".join(str(p) for p in err.absolute_path)
            result["schema_errors"].append(
                {"path": path, "message": err.message}
            )
        result["schema_validation"] = "FAIL"
        return result

    result["schema_validation"] = "PASS"
    return result


def clear_generated_outputs(generated_dir: Path) -> None:
    """
    Conservatively remove only known harness outputs inside generated/.

    Never touches frozen/ or raw_outputs/.
    """
    generated_dir.mkdir(parents=True, exist_ok=True)

    for name in GENERATED_ARTIFACTS:
        path = generated_dir / name
        if path.is_file():
            path.unlink()
        elif path.is_dir() and name == "blinded_scoring_package":
            shutil.rmtree(path)


def create_anonymous_copies(
    raw_dir: Path,
    generated_dir: Path,
    ordered_sources: list[str],
) -> list[dict[str, Any]]:
    """
    Copy raw outputs byte-for-byte to Output_01.md ... Output_06.md.

    Returns mapping entries with integrity checks.
    """
    entries: list[dict[str, Any]] = []
    for index, source_name in enumerate(ordered_sources, start=1):
        anon_name = f"Output_{index:02d}.md"
        source_path = raw_dir / source_name
        dest_path = generated_dir / anon_name

        source_hash = sha256_file(source_path)
        shutil.copyfile(source_path, dest_path)
        dest_hash = sha256_file(dest_path)

        if dest_hash != source_hash:
            raise RuntimeError(
                f"Integrity failure: {anon_name} SHA-256 differs from "
                f"{source_name} after copy."
            )

        entries.append(
            {
                "anonymous_file": anon_name,
                "source": source_name,
                "sha256": source_hash,
                "sha256_match": True,
            }
        )
    return entries


def write_private_mapping(
    path: Path,
    case_id: str,
    seed: int,
    mapping_entries: list[dict[str, Any]],
    generated_at: str,
) -> None:
    """Write private A/B mapping. Must never enter the blinded package."""
    mapping: dict[str, Any] = {}
    for entry in mapping_entries:
        mapping[entry["anonymous_file"]] = {
            "source": entry["source"],
            "sha256": entry["sha256"],
        }

    payload = {
        "case_id": case_id,
        "seed": seed,
        "generated_at": generated_at,
        "harness_version": HARNESS_VERSION,
        "mapping": mapping,
    }
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def write_validation_report(
    path: Path,
    case_id: str,
    generated_at: str,
    seed: int,
    validation_results: list[dict[str, Any]],
    ready: bool,
    anon_integrity: list[dict[str, Any]] | None = None,
) -> None:
    """Write validation_report.md without any candidate-to-Output mapping."""
    lines: list[str] = [
        "# Evaluation Harness Validation Report",
        "",
        f"**Case ID:** {case_id}",
        f"**Timestamp:** {generated_at}",
        f"**Harness version:** {HARNESS_VERSION}",
        f"**Randomisation seed:** {seed}",
        "",
        "## Raw Output Validation",
        "",
        "| Raw output | JSON parse | Schema validation | SHA-256 |",
        "| --- | --- | --- | --- |",
    ]

    for result in validation_results:
        lines.append(
            f"| {result['filename']} | {result['json_parse']} | "
            f"{result['schema_validation']} | `{result['sha256']}` |"
        )

    # Detail parse/schema failures (no mapping leakage)
    failures = [
        r
        for r in validation_results
        if r["json_parse"] != "PASS" or r["schema_validation"] != "PASS"
    ]
    if failures:
        lines.extend(["", "## Failure Details", ""])
        for result in failures:
            lines.append(f"### {result['filename']}")
            lines.append("")
            if result["parse_error"]:
                lines.append(f"- JSON parse error: {result['parse_error']}")
            for err in result.get("schema_errors", []):
                lines.append(f"- Schema error at `{err['path']}`: {err['message']}")
            lines.append("")

    lines.extend(
        [
            "",
            "## Anonymous Copy Integrity",
            "",
            "| Anonymous file | SHA-256 match |",
            "| --- | --- |",
        ]
    )
    if anon_integrity:
        for entry in anon_integrity:
            match = "PASS" if entry["sha256_match"] else "FAIL"
            lines.append(f"| {entry['anonymous_file']} | {match} |")
    else:
        lines.append("| *(not created)* | N/A |")

    status = (
        "READY FOR BLINDED EVALUATION"
        if ready
        else "NOT READY FOR BLINDED EVALUATION"
    )
    lines.extend(["", "## Final Status", "", status, ""])

    path.write_text("\n".join(lines), encoding="utf-8")


def build_blinded_package(
    case_dir: Path,
    generated_dir: Path,
) -> Path:
    """
    Create blinded_scoring_package with exactly 11 files.

    Excludes private_mapping.json, validation_report.md, and candidate names.
    """
    package_dir = generated_dir / "blinded_scoring_package"
    if package_dir.exists():
        shutil.rmtree(package_dir)
    package_dir.mkdir(parents=True)

    frozen_dir = case_dir / "frozen"
    for name in FROZEN_FILES:
        shutil.copyfile(frozen_dir / name, package_dir / name)

    for index in range(1, 7):
        anon_name = f"Output_{index:02d}.md"
        shutil.copyfile(generated_dir / anon_name, package_dir / anon_name)

    expected = set(FROZEN_FILES) | {f"Output_{i:02d}.md" for i in range(1, 7)}
    actual = {p.name for p in package_dir.iterdir() if p.is_file()}
    if actual != expected:
        raise RuntimeError(
            "Blinded package contents mismatch. "
            f"Expected {sorted(expected)}, got {sorted(actual)}."
        )

    # Safety: ensure no private/candidate leakage
    forbidden_substrings = ("private_mapping", "validation_report", "Candidate_")
    for name in actual:
        if any(s in name for s in forbidden_substrings):
            raise RuntimeError(f"Forbidden file leaked into package: {name}")

    return package_dir


def load_schema(schema_path: Path) -> dict[str, Any]:
    """Load and parse the frozen JSON Schema file."""
    try:
        text = schema_path.read_text(encoding="utf-8")
        schema = json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"ERROR: Schema file is not valid JSON: {schema_path}", file=sys.stderr)
        print(f"  {exc}", file=sys.stderr)
        sys.exit(1)
    except OSError as exc:
        print(f"ERROR: Could not read schema file: {schema_path}", file=sys.stderr)
        print(f"  {exc}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(schema, dict):
        print(
            f"ERROR: Schema root must be a JSON object: {schema_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Confirm the schema itself is usable with Draft 2020-12
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        print(
            f"ERROR: Schema failed Draft202012Validator.check_schema: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    return schema


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Medibank Evaluation Harness v0.1 — validate and anonymise "
            "candidate outputs for blinded evaluation (no LLM scoring)."
        )
    )
    parser.add_argument(
        "case_dir",
        type=Path,
        help=r"Path to case folder, e.g. cases\dementia_v1",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Optional integer seed for reproducible anonymisation shuffle.",
    )
    args = parser.parse_args(argv)

    case_dir = args.case_dir.resolve()
    if not case_dir.is_dir():
        print(f"ERROR: Case directory does not exist: {case_dir}", file=sys.stderr)
        return 1

    case_id = case_dir.name
    frozen_dir = case_dir / "frozen"
    raw_dir = case_dir / "raw_outputs"
    generated_dir = case_dir / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)

    # --- STEP 1: File check ---
    missing = check_required_files(case_dir)
    if missing:
        print("ERROR: Required files are missing. Scoring package not created.", file=sys.stderr)
        print("Missing files:", file=sys.stderr)
        for item in missing:
            print(f"  - {item}", file=sys.stderr)
        return 1

    # --- STEP 2: Load schema ---
    schema_path = frozen_dir / SCHEMA_FILENAME
    schema = load_schema(schema_path)

    # Seed selection (used in report even if we later fail the safety gate)
    if args.seed is not None:
        seed = args.seed
    else:
        seed = secrets.randbelow(2**31 - 1) + 1

    generated_at = datetime.now(timezone.utc).isoformat()

    # --- STEPS 3–5: Extract, validate, hash ---
    validation_results: list[dict[str, Any]] = []
    for name in RAW_OUTPUT_FILES:
        result = validate_output(raw_dir / name, schema)
        validation_results.append(result)

    all_pass = all(
        r["json_parse"] == "PASS" and r["schema_validation"] == "PASS"
        for r in validation_results
    )

    # Clear previous generated outputs before writing new ones
    clear_generated_outputs(generated_dir)

    # --- STEP 6: Safety gate ---
    if not all_pass:
        write_validation_report(
            path=generated_dir / "validation_report.md",
            case_id=case_id,
            generated_at=generated_at,
            seed=seed,
            validation_results=validation_results,
            ready=False,
            anon_integrity=None,
        )
        print("NOT READY FOR BLINDED EVALUATION")
        print(f"Validation report written to: {generated_dir / 'validation_report.md'}")
        print("Anonymous copies and blinded scoring package were NOT created.")
        return 1

    # --- STEPS 7–8: Anonymise + private mapping ---
    rng = random.Random(seed)
    ordered_sources = list(RAW_OUTPUT_FILES)
    rng.shuffle(ordered_sources)

    try:
        mapping_entries = create_anonymous_copies(
            raw_dir=raw_dir,
            generated_dir=generated_dir,
            ordered_sources=ordered_sources,
        )
    except RuntimeError as exc:
        write_validation_report(
            path=generated_dir / "validation_report.md",
            case_id=case_id,
            generated_at=generated_at,
            seed=seed,
            validation_results=validation_results,
            ready=False,
            anon_integrity=None,
        )
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    write_private_mapping(
        path=generated_dir / "private_mapping.json",
        case_id=case_id,
        seed=seed,
        mapping_entries=mapping_entries,
        generated_at=generated_at,
    )

    # --- STEP 9: Validation report ---
    write_validation_report(
        path=generated_dir / "validation_report.md",
        case_id=case_id,
        generated_at=generated_at,
        seed=seed,
        validation_results=validation_results,
        ready=True,
        anon_integrity=mapping_entries,
    )

    # --- STEP 10: Blinded scoring package ---
    try:
        package_dir = build_blinded_package(case_dir, generated_dir)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print("READY FOR BLINDED EVALUATION")
    print(f"Seed: {seed}")
    print(f"Validation report: {generated_dir / 'validation_report.md'}")
    print(f"Private mapping:   {generated_dir / 'private_mapping.json'}")
    print(f"Blinded package:   {package_dir}")
    print("WARNING: Do NOT share private_mapping.json with blinded evaluators.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
