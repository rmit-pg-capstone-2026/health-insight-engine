from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

VERSION = "0.2.2"
VERSION_RE = re.compile(r"^v[1-9][0-9]*$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def safe_copy_verify(src: Path, dst: Path) -> str:
    shutil.copyfile(src, dst)
    src_hash = sha256_file(src)
    dst_hash = sha256_file(dst)

    if src_hash != dst_hash:
        try:
            dst.unlink()
        except OSError:
            pass
        raise RuntimeError(f"Hash mismatch after copying {src.name}")

    return src_hash


def validate_metadata(metadata: dict, case_id: str, version: str) -> None:
    if metadata.get("case_id") != case_id:
        raise ValueError(
            f"Metadata case_id {metadata.get('case_id')!r} "
            f"does not match case folder {case_id!r}."
        )

    required = [
        "title",
        "organisation",
        "source_url",
        "retrieval_date",
    ]

    missing = [
        key
        for key in required
        if not str(metadata.get(key) or "").strip()
    ]

    if missing:
        raise ValueError(
            "Complete these source_metadata.json fields before freezing: "
            + ", ".join(missing)
        )

    metadata_version = metadata.get("source_version", "v1")
    if metadata_version != version:
        raise ValueError(
            f"Requested version {version} does not match "
            f"source_metadata.json source_version {metadata_version!r}."
        )


def validate_interactive_capture(metadata: dict, approve_interactive_gaps: bool) -> None:
    """
    v0.2.1 safety gate.

    If capture_source detected interactive evidence that it could not fully
    preserve, a normal --approve is not enough. Either recapture/repair the
    source so the interactive status is COMPLETE, or explicitly acknowledge
    the remaining gap after manual verification.
    """
    interactive = metadata.get("interactive_content") or {}

    if not interactive.get("capture_required"):
        return

    render_status = str(
        interactive.get("render_status")
        or interactive.get("status")
        or "UNRESOLVED"
    ).upper()
    evidence_status = str(
        interactive.get("evidence_status")
        or interactive.get("status")
        or "UNRESOLVED"
    ).upper()

    if evidence_status == "COMPLETE":
        return

    if approve_interactive_gaps:
        return

    raise ValueError(
        "Interactive source evidence requires human verification "
        f"(render_status={render_status}, evidence_status={evidence_status}). "
        "Review/supplement source/Test_Input_draft.md against the rendered "
        "source. If the remaining gap has been manually verified and is "
        "intentionally accepted, rerun with both --approve and "
        "--approve-interactive-gaps."
    )


def extract_publication_content(draft_text: str) -> str:
    start_marker = "## Publication Content"
    end_marker = "## Human Verification Checklist"

    if start_marker not in draft_text:
        raise ValueError(
            "Test_Input_draft.md is missing the '## Publication Content' marker."
        )

    after_start = draft_text.split(start_marker, 1)[1]

    if end_marker in after_start:
        publication_content = after_start.split(end_marker, 1)[0]
    else:
        publication_content = after_start

    publication_content = publication_content.strip()

    if not publication_content:
        raise ValueError(
            "No publication content was found in Test_Input_draft.md."
        )

    return publication_content


def build_clean_test_input(metadata: dict, publication_content: str) -> str:
    """
    Create the controlled experimental Test_Input.

    Keep only source metadata + publication content.
    Exclude capture notes, hashes, script version, draft warnings,
    and the human verification checklist.
    """
    lines = [
        "# Frozen Source Test Input",
        "",
        "## Snapshot metadata",
        "",
        f"- **Source:** {metadata.get('organisation', '')}",
        f"- **Title:** {metadata.get('title', '')}",
        f"- **Original source URL:** {metadata.get('source_url', '')}",
    ]

    reference_period = metadata.get("reference_period")
    if reference_period:
        lines.append(f"- **Reference period:** {reference_period}")

    publication_date = metadata.get("publication_date")
    if publication_date:
        lines.append(f"- **Release date:** {publication_date}")

    last_updated_date = metadata.get("last_updated_date")
    if last_updated_date:
        lines.append(f"- **Last updated date:** {last_updated_date}")

    visible_version_date = metadata.get("visible_version_date")
    if visible_version_date:
        lines.append(f"- **Visible version date:** {visible_version_date}")

    visible_version = metadata.get("visible_version")
    if visible_version:
        lines.append(f"- **Visible version:** {visible_version}")

    lines.append(
        f"- **Snapshot retrieval/capture date:** {metadata.get('retrieval_date', '')}"
    )

    # Scope is intentionally factual and copied from title.
    lines.append(f"- **Scope:** {metadata.get('title', '')}")

    lines.extend(
        [
            "",
            "## Source content",
            "",
            publication_content,
            "",
        ]
    )

    return "\n".join(lines)


def update_case_manifest(case_dir: Path, version: str, manifest_name: str) -> None:
    path = case_dir / "case_manifest.json"
    data = load_json(path)

    data["case_status"] = "SOURCE_FROZEN"
    data["source_status"] = "FROZEN"
    data["frozen_source_version"] = version
    data["frozen_source_manifest"] = f"frozen/{manifest_name}"

    write_json(path, data)


def freeze_normal(
    case_dir: Path,
    version: str,
    approve: bool,
    approve_interactive_gaps: bool,
) -> None:
    if not approve:
        raise ValueError(
            "Human verification is required. Review source/Test_Input_draft.md "
            "against the raw source, then rerun with --approve."
        )

    case_id = case_dir.name
    source_dir = case_dir / "source"
    frozen_dir = case_dir / "frozen"

    metadata_path = source_dir / "source_metadata.json"
    case_manifest_path = case_dir / "case_manifest.json"

    if not metadata_path.is_file():
        raise FileNotFoundError(f"Missing: {metadata_path}")

    if not case_manifest_path.is_file():
        raise FileNotFoundError(f"Missing: {case_manifest_path}")

    metadata = load_json(metadata_path)
    validate_metadata(metadata, case_id, version)
    validate_interactive_capture(metadata, approve_interactive_gaps)

    raw_filename = metadata.get("raw_source_filename")
    draft_filename = metadata.get("test_input_draft_filename")

    if not raw_filename or not draft_filename:
        raise ValueError(
            "Source has not been captured. Run capture_source.py first."
        )

    raw_source = source_dir / raw_filename
    draft_path = source_dir / draft_filename

    if not raw_source.is_file():
        raise FileNotFoundError(f"Raw source missing: {raw_source}")

    if not draft_path.is_file():
        raise FileNotFoundError(f"Test Input draft missing: {draft_path}")

    # Parse the case manifest before writing anything.
    load_json(case_manifest_path)

    # Build a CLEAN experimental Test_Input in memory.
    draft_text = draft_path.read_text(encoding="utf-8")
    publication_content = extract_publication_content(draft_text)
    clean_test_input = build_clean_test_input(metadata, publication_content)

    frozen_dir.mkdir(exist_ok=True)

    frozen_raw = (
        frozen_dir
        / f"raw_source_snapshot_{version}{raw_source.suffix.lower()}"
    )
    frozen_test_input = (
        frozen_dir
        / f"{case_id}_Test_Input_{version}.md"
    )
    manifest_path = (
        frozen_dir
        / f"source_manifest_{version}.json"
    )

    targets = [frozen_raw, frozen_test_input, manifest_path]
    existing = [path for path in targets if path.exists()]

    if existing:
        raise FileExistsError(
            "Frozen versions are immutable. Existing target(s): "
            + ", ".join(str(path) for path in existing)
            + ". Use an explicit new version only if the source/input genuinely changes."
        )

    created = []

    try:
        raw_hash = safe_copy_verify(raw_source, frozen_raw)
        created.append(frozen_raw)

        frozen_test_input.write_text(
            clean_test_input,
            encoding="utf-8",
        )
        created.append(frozen_test_input)

        test_input_hash = sha256_file(frozen_test_input)
        draft_hash = sha256_file(draft_path)

        interactive = metadata.get("interactive_content") or {}

        manifest = {
            "case_id": case_id,
            "title": metadata.get("title"),
            "organisation": metadata.get("organisation"),
            "source_url": metadata.get("source_url"),
            "final_url": metadata.get("final_url"),
            "reference_period": metadata.get("reference_period"),
            "retrieval_date": metadata.get("retrieval_date"),
            "retrieved_at": metadata.get("retrieved_at"),
            "publication_date": metadata.get("publication_date"),
            "last_updated_date": metadata.get("last_updated_date"),
            "visible_version_date": metadata.get("visible_version_date"),
            "visible_version": metadata.get("visible_version"),
            "source_version": version,
            "capture_method": metadata.get("capture_method"),
            "capture_script_version": metadata.get("capture_script_version"),
            "freeze_script_version": VERSION,
            "interactive_content": interactive,
            "interactive_gaps_explicitly_approved": bool(
                approve_interactive_gaps
                and interactive.get("capture_required")
                and str(
                    interactive.get("evidence_status")
                    or interactive.get("status")
                    or ""
                ).upper() != "COMPLETE"
            ),
            "original_raw_source_filename": raw_source.name,
            "frozen_raw_source_filename": frozen_raw.name,
            "raw_source_sha256": raw_hash,
            "original_test_input_draft_filename": draft_path.name,
            "test_input_draft_sha256": draft_hash,
            "frozen_test_input_filename": frozen_test_input.name,
            "test_input_sha256": test_input_hash,
            "test_input_format": "clean_frozen_source_test_input_v2",
            "frozen_at": utc_now(),
            "human_verified": True,
            "freeze_status": "FROZEN",
            "notes": metadata.get("notes", ""),
        }

        write_json(manifest_path, manifest)
        created.append(manifest_path)

        metadata["human_verified"] = True
        metadata["interactive_gaps_explicitly_approved"] = manifest[
            "interactive_gaps_explicitly_approved"
        ]
        write_json(metadata_path, metadata)

        update_case_manifest(
            case_dir,
            version,
            manifest_path.name,
        )

    except Exception:
        # Remove only artifacts created in this failed freeze attempt.
        for path in reversed(created):
            try:
                path.unlink()
            except OSError:
                pass
        raise

    print("SOURCE FROZEN SUCCESSFULLY")
    print(f"Freeze script version: {VERSION}")
    print(f"Case ID: {case_id}")
    print(f"Version: {version}")
    print(f"Frozen raw source: {frozen_raw.resolve()}")
    print(f"Raw source SHA-256: {raw_hash}")
    print(f"Frozen Test_Input: {frozen_test_input.resolve()}")
    print(f"Test_Input SHA-256: {test_input_hash}")
    print(f"Manifest: {manifest_path.resolve()}")
    print()
    print("The final Test_Input contains only:")
    print("  - Snapshot metadata")
    print("  - Source content (including captured interactive evidence, when available)")
    print()
    print("It excludes draft warnings, capture notes, hashes, and the")
    print("human verification checklist.")
    print()
    print("Use the FROZEN Test_Input for all downstream evaluation tasks.")


def freeze_legacy(
    case_dir: Path,
    version: str,
    legacy_input: Path,
    approve: bool,
) -> None:
    """
    Import an already-authoritative legacy Test_Input byte-for-byte.
    Intended for Case 1 (Dementia), which was already used experimentally.
    """
    if not approve:
        raise ValueError("Legacy import requires explicit --approve.")

    if not legacy_input.is_file():
        raise FileNotFoundError(
            f"Legacy Test_Input not found: {legacy_input}"
        )

    frozen_dir = case_dir / "frozen"
    frozen_dir.mkdir(parents=True, exist_ok=True)

    frozen_test_input = (
        frozen_dir
        / f"{case_dir.name}_Test_Input_{version}.md"
    )
    manifest_path = (
        frozen_dir
        / f"source_manifest_{version}.json"
    )

    if frozen_test_input.exists() or manifest_path.exists():
        raise FileExistsError(
            "Frozen legacy target already exists. "
            "Frozen versions are immutable."
        )

    test_hash = safe_copy_verify(
        legacy_input,
        frozen_test_input,
    )

    manifest = {
        "case_id": case_dir.name,
        "source_version": version,
        "legacy_import": True,
        "freeze_script_version": VERSION,
        "original_test_input_filename": legacy_input.name,
        "frozen_test_input_filename": frozen_test_input.name,
        "test_input_sha256": test_hash,
        "frozen_at": utc_now(),
        "human_verified": True,
        "freeze_status": "FROZEN",
        "note": (
            "Existing authoritative experimental Test_Input imported "
            "byte-for-byte. No current webpage was downloaded or substituted."
        ),
    }

    write_json(manifest_path, manifest)

    case_manifest_path = case_dir / "case_manifest.json"
    if case_manifest_path.is_file():
        update_case_manifest(
            case_dir,
            version,
            manifest_path.name,
        )

    print("LEGACY SOURCE FROZEN SUCCESSFULLY")
    print(f"Case ID: {case_dir.name}")
    print(f"Version: {version}")
    print(f"Frozen Test_Input: {frozen_test_input.resolve()}")
    print(f"SHA-256: {test_hash}")
    print(f"Manifest: {manifest_path.resolve()}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            f"Freeze a verified source and generate a clean experimental "
            f"Test_Input (freeze_source v{VERSION})."
        )
    )

    parser.add_argument("case_dir", type=Path)
    parser.add_argument("--version", default="v1")
    parser.add_argument(
        "--approve",
        action="store_true",
        help=(
            "Confirm that a human verified Test_Input_draft.md "
            "against the preserved raw source."
        ),
    )
    parser.add_argument(
        "--approve-interactive-gaps",
        action="store_true",
        help=(
            "Explicitly acknowledge unresolved/partial interactive evidence after "
            "manual verification. Use only together with --approve."
        ),
    )
    parser.add_argument(
        "--legacy-input",
        type=Path,
        help=(
            "Import an existing authoritative Test_Input byte-for-byte "
            "(for Case 1 / legacy support)."
        ),
    )

    args = parser.parse_args()

    if not VERSION_RE.fullmatch(args.version):
        print(
            "ERROR: version must be v1, v2, v3, ...",
            file=sys.stderr,
        )
        return 1

    if args.approve_interactive_gaps and not args.approve:
        print(
            "ERROR: --approve-interactive-gaps requires --approve.",
            file=sys.stderr,
        )
        return 1

    if not args.case_dir.is_dir():
        print(
            f"ERROR: case directory not found: {args.case_dir}",
            file=sys.stderr,
        )
        return 1

    try:
        if args.legacy_input:
            freeze_legacy(
                args.case_dir,
                args.version,
                args.legacy_input,
                args.approve,
            )
        else:
            freeze_normal(
                args.case_dir,
                args.version,
                args.approve,
                args.approve_interactive_gaps,
            )

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
