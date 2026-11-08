"""Schema v5: derived, recoverable project-wide candidate-key cache.

This index is NOT a publication identity or an authoritative deduplication
decision. It can be discarded and rebuilt from original source retrievals.
SQL executes inside the caller's verified project transaction; no executescript.
"""

V5_TABLES = (
    "candidate_index_keys", "candidate_index_records", "candidate_index_state",
)
V5_TRIGGERS = (
    "candidate_index_source_insert", "candidate_index_source_update",
    "candidate_index_source_delete",
)

V5_STATEMENTS = (
    """CREATE TABLE candidate_index_state (
        singleton_id INTEGER PRIMARY KEY CHECK(singleton_id=1)
            REFERENCES project_metadata(singleton_id) ON DELETE RESTRICT,
        status TEXT NOT NULL CHECK(status IN ('empty','building','ready','stale')),
        source_epoch INTEGER NOT NULL DEFAULT 0 CHECK(source_epoch >= 0),
        generation_id TEXT,
        baseline_epoch INTEGER CHECK(baseline_epoch IS NULL OR baseline_epoch >= 0),
        cursor_retrieval_id TEXT,
        processed_records INTEGER NOT NULL DEFAULT 0 CHECK(processed_records >= 0),
        indexed_keys INTEGER NOT NULL DEFAULT 0 CHECK(indexed_keys >= 0),
        unsupported_records INTEGER NOT NULL DEFAULT 0 CHECK(unsupported_records >= 0),
        running_sha256 TEXT,
        started_at_utc TEXT,
        updated_at_utc TEXT
    )""",
    """INSERT INTO candidate_index_state(singleton_id,status)
        VALUES(1,'empty')""",
    """CREATE TABLE candidate_index_records (
        retrieval_id TEXT PRIMARY KEY REFERENCES source_retrievals(retrieval_id)
            ON DELETE CASCADE,
        generation_id TEXT NOT NULL,
        run_id TEXT NOT NULL REFERENCES search_runs(run_id) ON DELETE RESTRICT,
        source_sha256 TEXT NOT NULL,
        supported INTEGER NOT NULL CHECK(supported IN (0,1))
    )""",
    """CREATE INDEX candidate_index_records_by_run
        ON candidate_index_records(run_id,retrieval_id)""",
    """CREATE TABLE candidate_index_keys (
        retrieval_id TEXT NOT NULL REFERENCES candidate_index_records(retrieval_id)
            ON DELETE CASCADE,
        field TEXT NOT NULL CHECK(field IN ('doi','pmid','accession','title')),
        value_sha256 TEXT NOT NULL CHECK(length(value_sha256)=64),
        PRIMARY KEY(retrieval_id,field)
    )""",
    """CREATE INDEX candidate_index_keys_by_field
        ON candidate_index_keys(field,value_sha256,retrieval_id)""",
    # A changed source can NEVER silently retain a 'ready' original-metadata
    # index. Invalidation occurs in the SAME transaction as the source change.
    # Link/identity decisions do not invalidate keys; they are always read
    # from original current identity evidence when candidates are reviewed.
    """CREATE TRIGGER candidate_index_source_insert
        AFTER INSERT ON source_retrievals
        BEGIN
            UPDATE candidate_index_state SET
                source_epoch=source_epoch+1,
                status=CASE WHEN status IN ('building','ready') THEN 'stale'
                            ELSE status END
            WHERE singleton_id=1;
        END""",
    """CREATE TRIGGER candidate_index_source_update
        AFTER UPDATE ON source_retrievals
        BEGIN
            UPDATE candidate_index_state SET
                source_epoch=source_epoch+1,
                status=CASE WHEN status IN ('building','ready') THEN 'stale'
                            ELSE status END
            WHERE singleton_id=1;
        END""",
    """CREATE TRIGGER candidate_index_source_delete
        AFTER DELETE ON source_retrievals
        BEGIN
            UPDATE candidate_index_state SET
                source_epoch=source_epoch+1,
                status=CASE WHEN status IN ('building','ready') THEN 'stale'
                            ELSE status END
            WHERE singleton_id=1;
        END""",
)


def apply_v5_schema(connection) -> None:
    """Add candidate-index tables and atomic source invalidation triggers."""
    for statement in V5_STATEMENTS:
        connection.execute(statement)
