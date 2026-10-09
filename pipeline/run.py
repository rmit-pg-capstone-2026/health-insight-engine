#!/usr/bin/env python3
"""
Runs the pipeline stage by stage, with the database in between.

For each stage this script does three things, and only these three:
    1. query the database for the work that is waiting
    2. build the stage's input and call the stage (pipeline/stages.py)
    3. save what the stage returns, and move the document to the next status

    collect  every active source               -> new documents       (status: new)
    extract  documents with status 'new'       -> insights            (status: extracted)
    assess   documents with status 'extracted' -> priorities          (status: assessed)
    brief    assessed insights not yet briefed -> PDF + briefings row

After extract, each insight is compared with the insights already stored for
earlier versions of the same page. One whose evidence quote matches an existing
one is dropped, so only new insights go on to be assessed and briefed.

Files and the database live in the data folder (storage.py). When
PIPELINE_S3_BUCKET is set, the database is downloaded from S3 at the start and
uploaded again after every document, and each file is pushed to / pulled from
S3 as it is needed - that is how it runs on Lambda (lambda_handler.py).

Usage:
    python pipeline/run.py                    # collect, extract, assess
    python pipeline/run.py extract            # one stage only
    python pipeline/run.py extract --limit 1  # at most one document this run
    python pipeline/run.py brief --preview    # PDF only, nothing marked as briefed
    python pipeline/run.py brief              # PDF, and mark its insights as briefed
"""

import argparse
import json
from datetime import date
from pathlib import Path

import db
import stages
import storage
from consolidate_insights import consolidate_insights  # on the path via stages
from extract import normalise  # on the path via stages

SOURCES_FILE = Path(__file__).resolve().parent / "sources.json"
STAGES = ("collect", "extract", "assess", "brief")


def fail(conn, doc_id: int, stage: str, exc: Exception) -> None:
    """Log the model call if there was one, then count the failure."""
    if isinstance(exc, stages.StageError) and exc.llm:
        db.log_llm_call(conn, doc_id, stage, **exc.llm, output=exc.output)
    after = db.record_failure(conn, doc_id, f"{stage}: {exc}")
    db.checkpoint(conn)
    print(f"    FAILED: {exc}" + ("  (gave up after %d tries)" % db.MAX_ATTEMPTS
                                  if after == "failed" else "  (will retry next run)"))


# ----------------------------------------------------------------- collect

def run_collect(conn, limit=None) -> dict:
    counts = {"new": 0, "unchanged": 0, "errors": 0}
    sources = conn.execute("SELECT id, agency, url FROM sources WHERE active = 1 "
                           "ORDER BY id").fetchall()
    for src in sources:
        print(f"  {src['agency']}  {src['url']}")
        known = [r["content_hash"] for r in conn.execute(
            "SELECT content_hash FROM documents WHERE source_id = ?", (src["id"],))]
        try:
            out = stages.collect({"agency": src["agency"], "url": src["url"],
                                  "known_hashes": known})
        except Exception as exc:  # one bad page must not stop the rest
            print(f"    skipped: {exc}")
            conn.execute("UPDATE sources SET last_checked_at = ?, last_error = ? WHERE id = ?",
                         (db.now(), str(exc)[:2000], src["id"]))
            db.checkpoint(conn)
            counts["errors"] += 1
            continue

        conn.execute("UPDATE sources SET last_checked_at = ?, last_error = NULL WHERE id = ?",
                     (db.now(), src["id"]))
        if not out["changed"]:
            db.checkpoint(conn)
            print("    unchanged")
            counts["unchanged"] += 1
            continue

        # The file goes up first, so the database never points at a file
        # that is not in S3.
        storage.upload(out["markdown_path"])

        # An older version still waiting for stage 2 is out of date now.
        # Skip it rather than pay to extract text that has already changed.
        conn.execute("UPDATE documents SET status = 'superseded' "
                     "WHERE source_id = ? AND status = 'new'", (src["id"],))
        cur = conn.execute(
            "INSERT INTO documents (source_id, content_hash, fetched_at, title, markdown_path) "
            "VALUES (?, ?, ?, ?, ?)",
            (src["id"], out["content_hash"], out["fetched_at"], out["title"],
             out["markdown_path"]))
        db.checkpoint(conn)
        print(f"    NEW -> document #{cur.lastrowid}: {out['title']}")
        counts["new"] += 1
    return counts


# ----------------------------------------------------------------- extract

def drop_duplicates(conn, doc, insights: list) -> tuple[list, int]:
    """Keep only insights whose evidence has not been seen before for this
    page - in an earlier version of it, or earlier in this same response."""
    seen = {normalise(r["evidence"] or "") for r in conn.execute(
        "SELECT i.evidence FROM insights i JOIN documents d ON d.id = i.document_id "
        "WHERE d.source_id = ? AND d.id != ?", (doc["source_id"], doc["id"]))}
    kept = []
    for ins in insights:
        key = normalise(ins["evidence"] or "")
        if key and key in seen:
            continue
        seen.add(key)
        kept.append(ins)
    return kept, len(insights) - len(kept)


def waiting(conn, status: str, limit) -> list:
    """Documents with this status, oldest first - at most `limit` of them."""
    docs = conn.execute("SELECT d.*, s.url FROM documents d JOIN sources s ON s.id = d.source_id "
                        "WHERE d.status = ? ORDER BY d.id", (status,)).fetchall()
    return docs[:limit] if limit else docs


def summary(conn, counts: dict, status: str) -> dict:
    counts["still_waiting"] = conn.execute(
        "SELECT COUNT(*) FROM documents WHERE status = ?", (status,)).fetchone()[0]
    return counts


def run_extract(conn, limit=None) -> dict:
    counts = {"done": 0, "failed": 0}
    docs = waiting(conn, "new", limit)
    for i, doc in enumerate(docs, 1):
        print(f"  [{i}/{len(docs)}] #{doc['id']} {doc['title']}")
        try:
            if not storage.download(doc["markdown_path"]):
                raise FileNotFoundError(f"document file is missing: {doc['markdown_path']}")
            out = stages.extract({"markdown_path": doc["markdown_path"],
                                  "retrieval_date": doc["fetched_at"][:10]})
        except Exception as exc:
            fail(conn, doc["id"], "extract", exc)
            counts["failed"] += 1
            continue
        db.log_llm_call(conn, doc["id"], "extract", **out["llm"], output=out["record"])

        insights, dropped = drop_duplicates(conn, doc, out["insights"])
        meta = out["document"]
        with conn:  # all or nothing
            conn.execute("DELETE FROM insights WHERE document_id = ?", (doc["id"],))
            for ins in insights:
                ok = ins["evidence_found"]
                conn.execute(
                    "INSERT INTO insights (document_id, position, insight_type, finding, "
                    "evidence, evidence_location, target_population, caveat, reasoning, "
                    "evidence_found, held_back, held_back_reason) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (doc["id"], ins["position"], ins["insight_type"], ins["finding"],
                     ins["evidence"], ins["evidence_location"], ins["target_population"],
                     ins["caveat"], ins["reasoning"], int(ok), int(not ok),
                     None if ok else "evidence quote not found in the source document"))
            conn.execute(
                "UPDATE documents SET publisher = ?, publication_date = ?, period_covered = ?, "
                "summary = ?, document_scope = ?, duplicates_dropped = ?, status = ?, "
                "attempts = 0, last_error = NULL WHERE id = ?",
                (meta["publisher"], meta["publication_date"], meta["period_covered"],
                 meta["summary"], meta["document_scope"], dropped,
                 "extracted" if insights else "no_insights", doc["id"]))
        db.checkpoint(conn)
        counts["done"] += 1

        held = sum(1 for ins in insights if not ins["evidence_found"])
        cost = out["llm"].get("cost_usd")
        print(f"    {len(out['insights'])} found, {dropped} already seen, {len(insights)} new "
              f"({held} held back: quote not found)" + (f", ${cost:.4f}" if cost else ""))
    return summary(conn, counts, "new")


# ------------------------------------------------------------------ assess

def assessment_input(conn, doc) -> dict:
    """Stage 3's input, built from the database - the same shape
    prepare_assessment_input.py builds from a stage 2 JSON file."""
    from prepare_assessment_input import HANDOFF_REQUIRED_FIELDS
    rows = conn.execute("SELECT * FROM insights WHERE document_id = ? AND held_back = 0 "
                        "ORDER BY position", (doc["id"],)).fetchall()
    insights = []
    for r in rows:
        insight_id = "INSIGHT_%03d" % r["position"]
        missing = [f for f in HANDOFF_REQUIRED_FIELDS if r[f] in (None, "")]
        if missing:
            raise ValueError(f"{insight_id} is missing required handoff fields: {missing}")
        insights.append({"insight_id": insight_id, "insight_type": r["insight_type"],
                         "finding": r["finding"], "evidence": r["evidence"],
                         "evidence_location": r["evidence_location"],
                         "target_population": r["target_population"], "caveat": r["caveat"]})
    return {
        "source": {"publisher": doc["publisher"], "title": doc["title"], "url": doc["url"],
                   "publication_date": doc["publication_date"],
                   "retrieval_date": doc["fetched_at"][:10]},
        "summary": doc["summary"],
        "insights": insights,
    }


def run_assess(conn, limit=None) -> dict:
    counts = {"done": 0, "failed": 0}
    docs = waiting(conn, "extracted", limit)
    for i, doc in enumerate(docs, 1):
        print(f"  [{i}/{len(docs)}] #{doc['id']} {doc['title']}")
        try:
            article = assessment_input(conn, doc)
            if article["insights"]:
                out = stages.assess(article)
            else:
                out = None
                print("    nothing to assess (every new insight was held back)")
        except Exception as exc:
            fail(conn, doc["id"], "assess", exc)
            counts["failed"] += 1
            continue

        with conn:
            if out:
                db.log_llm_call(conn, doc["id"], "assess", **out["llm"],
                                output={"assessments": out["assessments"]})
                for a in out["assessments"]:
                    conn.execute(
                        "UPDATE insights SET relevance = ?, priority = ?, priority_rationale = ?, "
                        "criteria = ? WHERE document_id = ? AND position = ?",
                        (a["relevance"], a["priority"], a["priority_rationale"],
                         json.dumps(a["criteria"]), doc["id"], int(a["insight_id"][-3:])))
                print(f"    {len(out['assessments'])} assessed in {out['llm']['seconds']}s")
            conn.execute("UPDATE documents SET status = 'assessed', attempts = 0, "
                         "last_error = NULL WHERE id = ?", (doc["id"],))
        db.checkpoint(conn)
        counts["done"] += 1
    return summary(conn, counts, "extracted")


# ------------------------------------------------------------------- brief

BRIEFABLE = """
SELECT i.*, d.source_id, d.title, d.publisher, d.publication_date, d.fetched_at,
       d.summary, s.url AS source_url
FROM insights i
JOIN documents d ON d.id = i.document_id
JOIN sources s   ON s.id = d.source_id
WHERE d.status = 'assessed'
  AND i.held_back = 0
  AND i.briefing_id IS NULL
  AND i.priority IS NOT NULL
  AND i.relevance != 'Not relevant'
  AND i.priority != 'Not Applicable'
ORDER BY d.id, i.position
"""


def briefing_input(rows) -> list:
    """One dict per page, consolidated exactly as stage 3's script does.

    Grouped by source, not document, so two versions of the same page show up
    as one source in the PDF, described by its latest version. Ids are
    document-position, because INSIGHT_003 can exist in both versions."""
    by_source = {}
    for r in rows:  # ordered by document id, so later versions come last
        page = by_source.setdefault(r["source_id"], {"priority_assessment_version": "v0.3_article",
                                                     "assessed_insights": []})
        page["source"] = {"publisher": r["publisher"], "title": r["title"],
                          "url": r["source_url"], "publication_date": r["publication_date"],
                          "retrieval_date": r["fetched_at"][:10]}
        page["summary"] = r["summary"]
        page["assessed_insights"].append({
            "insight_id": f"{r['document_id']}-{r['position']}",
            "insight_type": r["insight_type"],
            "finding": r["finding"], "evidence": r["evidence"],
            "evidence_location": r["evidence_location"],
            "target_population": r["target_population"], "caveat": r["caveat"],
            "relevance": r["relevance"], "criteria": json.loads(r["criteria"] or "{}"),
            "priority": r["priority"], "priority_rationale": r["priority_rationale"],
        })
    return [consolidate_insights(page) for page in by_source.values()]


def next_pdf_path(preview: bool) -> str:
    """briefing-paper/briefing_2026-10-02.pdf, or _2, _3 ... if one already
    exists that day (here or in S3), so an earlier PDF is never overwritten.
    A preview always reuses the same name."""
    stem = f"briefing-paper/briefing_{date.today():%Y-%m-%d}" + ("_preview" if preview else "")
    rel, n = f"{stem}.pdf", 1
    while not preview and storage.exists(rel):
        n += 1
        rel = f"{stem}_{n}.pdf"
    return rel


def run_brief(conn, preview: bool = False) -> dict:
    rows = conn.execute(BRIEFABLE).fetchall()
    if not rows:
        print("  nothing new to brief - no PDF made")
        return {"pdf": None, "insights": 0}

    rel = next_pdf_path(preview)
    out = stages.brief(briefing_input(rows), storage.local(rel))
    storage.upload(rel)
    print(f"  created {rel}: {out['insight_count']} insight(s) "
          f"from {out['source_count']} source(s)")
    result = {"pdf": rel, "insights": out["insight_count"], "sources": out["source_count"],
              "preview": preview}
    if preview:
        print("  preview only - nothing marked as briefed")
        return result

    with conn:
        cur = conn.execute(
            "INSERT INTO briefings (created_at, pdf_path, source_count, insight_count) "
            "VALUES (?, ?, ?, ?)",
            (db.now(), rel, out["source_count"], out["insight_count"]))
        conn.executemany("UPDATE insights SET briefing_id = ? WHERE id = ?",
                         [(cur.lastrowid, r["id"]) for r in rows])
    db.checkpoint(conn)
    print(f"  recorded as briefing #{cur.lastrowid}; {len(rows)} insight(s) marked as briefed")
    result["briefing_id"] = cur.lastrowid
    return result


# -------------------------------------------------------------------- main

def run_stage(stage: str, limit=None, preview: bool = False) -> dict:
    """Run one stage end to end: open the database (from S3 when set), do
    the work, and return a short summary. Used by main() and by Lambda."""
    conn = db.open_db()
    try:
        db.sync_sources(conn, json.loads(SOURCES_FILE.read_text(encoding="utf-8")))
        db.checkpoint(conn)
        print(f"\n== {stage} ==")
        if stage == "collect":
            result = run_collect(conn)
        elif stage == "extract":
            result = run_extract(conn, limit)
        elif stage == "assess":
            result = run_assess(conn, limit)
        elif stage == "brief":
            result = run_brief(conn, preview)
        else:
            raise ValueError(f"unknown stage {stage!r}; expected one of {STAGES}")
        db.checkpoint(conn)
        return {"stage": stage, **result}
    finally:
        conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the pipeline through the database.")
    ap.add_argument("stage", nargs="?", default="all", choices=("all",) + STAGES,
                    help="'all' runs collect, extract and assess (default)")
    ap.add_argument("--limit", type=int,
                    help="extract/assess: handle at most this many documents this run")
    ap.add_argument("--preview", action="store_true",
                    help="brief only: make the PDF without marking anything as briefed")
    args = ap.parse_args()

    steps = ["collect", "extract", "assess"] if args.stage == "all" else [args.stage]
    for step in steps:
        print(run_stage(step, args.limit, args.preview))
    print("\nSee everything with: python pipeline/db.py")


if __name__ == "__main__":
    main()
