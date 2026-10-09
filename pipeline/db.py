"""
The pipeline's state database (SQLite): data/pipeline.db.

    sources     the pages we watch (synced from pipeline/sources.json)
    documents   one row per version of a page; points at its markdown file
    insights    one row per new insight found in a document
    briefings   one row per PDF produced
    llm_calls   every model call, for cost and debugging

A document moves through these statuses:

    new -> extracted -> assessed          the normal path
    no_insights                           stage 2 found nothing new to report
    superseded                            a newer version arrived before this one was extracted,
                                          so it is skipped
    failed                                gave up after MAX_ATTEMPTS tries at one stage

Run this file directly to see what is in the database:
    python pipeline/db.py
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import storage

DB_FILE = "pipeline.db"                 # relative to the data folder, and its S3 key
DB_PATH = storage.local(DB_FILE)
MAX_ATTEMPTS = 3
SCHEMA_VERSION = 3                      # bump when the tables or stored paths change

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id              INTEGER PRIMARY KEY,
    url             TEXT NOT NULL UNIQUE,
    agency          TEXT NOT NULL,              -- AIHW or ABS
    active          INTEGER NOT NULL DEFAULT 1, -- 0 once removed from sources.json
    last_checked_at TEXT,
    last_error      TEXT
);

CREATE TABLE IF NOT EXISTS documents (
    id               INTEGER PRIMARY KEY,
    source_id        INTEGER NOT NULL REFERENCES sources(id),
    content_hash     TEXT NOT NULL,
    fetched_at       TEXT NOT NULL,
    title            TEXT,
    markdown_path    TEXT NOT NULL,             -- this version's file, relative to the data folder
    -- filled in by stage 2
    publisher        TEXT,
    publication_date TEXT,
    period_covered   TEXT,
    summary          TEXT,
    document_scope   TEXT,
    duplicates_dropped INTEGER,                 -- insights skipped as already seen
    -- progress
    status           TEXT NOT NULL DEFAULT 'new',
    attempts         INTEGER NOT NULL DEFAULT 0, -- failed tries at the current stage
    last_error       TEXT,
    UNIQUE (source_id, content_hash)
);

CREATE TABLE IF NOT EXISTS briefings (
    id            INTEGER PRIMARY KEY,
    created_at    TEXT NOT NULL,
    pdf_path      TEXT NOT NULL,                -- relative to the data folder
    source_count  INTEGER NOT NULL,
    insight_count INTEGER NOT NULL,
    sent_at       TEXT                          -- set once emailing exists
);

CREATE TABLE IF NOT EXISTS insights (
    id                 INTEGER PRIMARY KEY,
    document_id        INTEGER NOT NULL REFERENCES documents(id),
    position           INTEGER NOT NULL,        -- the model's order: 3 = INSIGHT_003
    insight_type       TEXT,
    finding            TEXT,
    evidence           TEXT,
    evidence_location  TEXT,
    target_population  TEXT,
    caveat             TEXT,
    reasoning          TEXT,
    evidence_found     INTEGER,                 -- 1 if the quote is really in the document
    held_back          INTEGER NOT NULL DEFAULT 0,
    held_back_reason   TEXT,
    -- filled in by stage 3
    relevance          TEXT,
    priority           TEXT,
    priority_rationale TEXT,
    criteria           TEXT,                    -- JSON object of the 10 factors
    -- filled in by the briefing job
    briefing_id        INTEGER REFERENCES briefings(id),
    UNIQUE (document_id, position)
);

CREATE TABLE IF NOT EXISTS llm_calls (
    id                INTEGER PRIMARY KEY,
    document_id       INTEGER REFERENCES documents(id),
    stage             TEXT NOT NULL,            -- extract or assess
    model             TEXT,
    provider          TEXT,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    cost_usd          REAL,
    seconds           REAL,
    error             TEXT,
    output            TEXT,                     -- the full response, as JSON
    created_at        TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    """Open the database, creating the file and tables on first use."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    existing = conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'documents'").fetchone()
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if existing and version != SCHEMA_VERSION:
        raise SystemExit(f"{path} was made by an older version of the pipeline. "
                         "Delete it and run again.")
    conn.executescript(SCHEMA)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    return conn


def open_db() -> sqlite3.Connection:
    """Open the latest database. With an S3 bucket set, the copy in S3 is
    downloaded first; if S3 has none yet, start from an empty one rather
    than from whatever an earlier run left in the local folder."""
    if storage.BUCKET and not storage.download(DB_FILE):
        DB_PATH.unlink(missing_ok=True)
    return connect()


def checkpoint(conn: sqlite3.Connection) -> None:
    """Commit, and push the database to S3 (when a bucket is set). Called
    after every document, so a run that dies halfway keeps what it finished."""
    conn.commit()
    storage.upload(DB_FILE)


def sync_sources(conn: sqlite3.Connection, entries: list[dict]) -> None:
    """Make the sources table match sources.json: add new URLs, reactivate
    ones that came back, and deactivate ones that were removed. Rows are never
    deleted, because documents still point at them."""
    listed = {e["url"]: e["agency"].upper() for e in entries}
    for url, agency in listed.items():
        conn.execute(
            "INSERT INTO sources (url, agency) VALUES (?, ?) "
            "ON CONFLICT(url) DO UPDATE SET agency = excluded.agency, active = 1",
            (url, agency),
        )
    for row in conn.execute("SELECT id, url FROM sources WHERE active = 1").fetchall():
        if row["url"] not in listed:
            conn.execute("UPDATE sources SET active = 0 WHERE id = ?", (row["id"],))
    conn.commit()


def record_failure(conn: sqlite3.Connection, doc_id: int, error: str) -> str:
    """Count a failed try. After MAX_ATTEMPTS the document is marked failed
    and left alone. Returns the document's status afterwards."""
    conn.execute(
        "UPDATE documents SET attempts = attempts + 1, last_error = ? WHERE id = ?",
        (error[:2000], doc_id),
    )
    conn.execute(
        "UPDATE documents SET status = 'failed' WHERE id = ? AND attempts >= ?",
        (doc_id, MAX_ATTEMPTS),
    )
    conn.commit()
    return conn.execute("SELECT status FROM documents WHERE id = ?", (doc_id,)).fetchone()[0]


def log_llm_call(conn: sqlite3.Connection, document_id: int, stage: str, *, model=None,
                 provider=None, prompt_tokens=None, completion_tokens=None, cost_usd=None,
                 seconds=None, error=None, output=None) -> None:
    conn.execute(
        "INSERT INTO llm_calls (document_id, stage, model, provider, prompt_tokens, "
        "completion_tokens, cost_usd, seconds, error, output, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (document_id, stage, model, provider, prompt_tokens, completion_tokens, cost_usd,
         seconds, error, json.dumps(output, ensure_ascii=False) if output is not None else None,
         now()),
    )
    conn.commit()


def print_status(conn: sqlite3.Connection) -> None:
    print(f"Database: {DB_PATH}\n")

    print("Documents")
    rows = conn.execute(
        "SELECT d.id, s.agency, d.status, d.attempts, d.title, d.last_error "
        "FROM documents d JOIN sources s ON s.id = d.source_id ORDER BY d.id"
    ).fetchall()
    if not rows:
        print("  (none yet)")
    for r in rows:
        err = f"  last error: {r['last_error'][:80]}" if r["last_error"] else ""
        print(f"  #{r['id']:<3} {r['agency']:<5} {r['status']:<12} tries={r['attempts']}  "
              f"{(r['title'] or '')[:55]}{err}")

    broken = conn.execute("SELECT agency, url, last_error FROM sources "
                          "WHERE active = 1 AND last_error IS NOT NULL").fetchall()
    for r in broken:
        print(f"  ! could not fetch {r['agency']} {r['url']}: {r['last_error'][:80]}")

    print("\nInsights")
    rows = conn.execute(
        "SELECT CASE WHEN held_back THEN 'held back' "
        "            WHEN briefing_id IS NOT NULL THEN 'briefed' "
        "            WHEN priority IS NULL THEN 'waiting for assessment' "
        "            ELSE 'ready for briefing: ' || priority END AS state, COUNT(*) AS n "
        "FROM insights GROUP BY state ORDER BY state"
    ).fetchall()
    if not rows:
        print("  (none yet)")
    for r in rows:
        print(f"  {r['n']:>4}  {r['state']}")

    print("\nBriefings")
    rows = conn.execute("SELECT * FROM briefings ORDER BY id").fetchall()
    if not rows:
        print("  (none yet)")
    for r in rows:
        print(f"  #{r['id']:<3} {r['created_at'][:10]}  {r['insight_count']} insight(s) from "
              f"{r['source_count']} source(s)  {r['pdf_path']}")

    cost = conn.execute("SELECT COALESCE(SUM(cost_usd), 0), COUNT(*) FROM llm_calls").fetchone()
    print(f"\nModel calls: {cost[1]}, known cost ${cost[0]:.4f}")


if __name__ == "__main__":
    print_status(open_db())
