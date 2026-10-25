"""Version 3 additive tables for transactional PubMed identifier checkpoints.

Each page has a unique partition/offset and a globally unique PMID per source
query. Operations and audit events are committed in one SQLite transaction.
"""

V3_STATEMENTS = (
    """CREATE TABLE pubmed_checkpoint_runs (
        query_id TEXT PRIMARY KEY,
        root_query TEXT NOT NULL,
        root_count INTEGER NOT NULL CHECK (root_count >= 0),
        plan_json TEXT NOT NULL,
        plan_sha256 TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'incomplete'
            CHECK (status IN ('incomplete', 'paused', 'identifiers_reconciled_metadata_pending')),
        created_at_utc TEXT NOT NULL,
        updated_at_utc TEXT NOT NULL,
        FOREIGN KEY (query_id) REFERENCES source_queries(query_id) ON DELETE RESTRICT
    )""",
    """CREATE TABLE pubmed_checkpoint_pages (
        query_id TEXT NOT NULL,
        partition_index INTEGER NOT NULL,
        retstart INTEGER NOT NULL CHECK (retstart >= 0),
        retmax INTEGER NOT NULL CHECK (retmax BETWEEN 1 AND 1000),
        page_json TEXT NOT NULL,
        page_sha256 TEXT NOT NULL,
        retrieved_at_utc TEXT NOT NULL,
        PRIMARY KEY (query_id, partition_index, retstart),
        FOREIGN KEY (query_id) REFERENCES pubmed_checkpoint_runs(query_id) ON DELETE RESTRICT
    )""",
    """CREATE TABLE pubmed_checkpoint_ids (
        query_id TEXT NOT NULL,
        pmid TEXT NOT NULL,
        partition_index INTEGER NOT NULL,
        retstart INTEGER NOT NULL,
        PRIMARY KEY (query_id, pmid),
        FOREIGN KEY (query_id, partition_index, retstart)
            REFERENCES pubmed_checkpoint_pages(query_id, partition_index, retstart)
            ON DELETE RESTRICT
    )""",
    """CREATE INDEX pubmed_checkpoint_ids_by_page
        ON pubmed_checkpoint_ids(query_id, partition_index, retstart)""",
    """CREATE TRIGGER immutable_pubmed_checkpoint_pages_update
        BEFORE UPDATE ON pubmed_checkpoint_pages
        BEGIN SELECT RAISE(ABORT, 'checkpoint pages are immutable'); END""",
    """CREATE TRIGGER immutable_pubmed_checkpoint_pages_delete
        BEFORE DELETE ON pubmed_checkpoint_pages
        BEGIN SELECT RAISE(ABORT, 'checkpoint pages are immutable'); END""",
    """CREATE TRIGGER immutable_pubmed_checkpoint_ids_update
        BEFORE UPDATE ON pubmed_checkpoint_ids
        BEGIN SELECT RAISE(ABORT, 'checkpoint identifiers are immutable'); END""",
    """CREATE TRIGGER immutable_pubmed_checkpoint_ids_delete
        BEFORE DELETE ON pubmed_checkpoint_ids
        BEGIN SELECT RAISE(ABORT, 'checkpoint identifiers are immutable'); END""",
)


def apply_v3_schema(connection) -> None:
    """Apply additive checkpoint tables inside a caller-owned transaction."""
    for statement in V3_STATEMENTS:
        connection.execute(statement)
