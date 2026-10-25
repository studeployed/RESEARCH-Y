"""SQLite schema v2: durable research-record identities and provenance links.

All SQL statements are constant and run inside the caller's transaction. This
module defines storage only: provider retrieval, deduplication and the interface
are separate future increments. A reported hit count cannot be inferred from
these tables.
"""

SCHEMA_VERSION = 3

RUN_STATUSES = (
    "pending", "running", "paused", "completed_verified",
    "completed_with_warnings", "incomplete", "failed", "cancelled",
)

# Entries execute in the declared order; do not use executescript during a
# migration, because sqlite3.executescript() implicitly commits beforehand.
V2_STATEMENTS = (
    """CREATE TABLE strategy_versions (
        strategy_version_id TEXT PRIMARY KEY,
        version_number INTEGER NOT NULL UNIQUE CHECK (version_number > 0),
        approved_at_utc TEXT NOT NULL,
        snapshot_json TEXT NOT NULL
    )""",
    """CREATE TABLE strategy_groups (
        strategy_version_id TEXT NOT NULL,
        group_id TEXT NOT NULL,
        label TEXT NOT NULL,
        group_order INTEGER NOT NULL CHECK (group_order >= 0),
        PRIMARY KEY (strategy_version_id, group_id),
        UNIQUE (strategy_version_id, group_order),
        FOREIGN KEY (strategy_version_id) REFERENCES strategy_versions(strategy_version_id)
            ON DELETE RESTRICT
    )""",
    """CREATE TABLE search_runs (
        run_id TEXT PRIMARY KEY,
        strategy_version_id TEXT NOT NULL,
        created_at_utc TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending', 'running', 'paused', 'completed_verified',
                'completed_with_warnings', 'incomplete', 'failed', 'cancelled')),
        completed_at_utc TEXT,
        UNIQUE (run_id, strategy_version_id),
        FOREIGN KEY (strategy_version_id) REFERENCES strategy_versions(strategy_version_id)
            ON DELETE RESTRICT
    )""",
    """CREATE TABLE source_queries (
        query_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        strategy_version_id TEXT NOT NULL,
        group_id TEXT NOT NULL,
        source_name TEXT NOT NULL,
        exact_query TEXT NOT NULL,
        parameters_json TEXT NOT NULL DEFAULT '{}',
        reported_matches INTEGER CHECK (reported_matches IS NULL OR reported_matches >= 0),
        status TEXT NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending', 'running', 'paused', 'completed_verified',
                'completed_with_warnings', 'incomplete', 'failed', 'cancelled')),
        executed_at_utc TEXT,
        UNIQUE (query_id, run_id, source_name),
        FOREIGN KEY (run_id, strategy_version_id)
            REFERENCES search_runs(run_id, strategy_version_id) ON DELETE RESTRICT,
        FOREIGN KEY (strategy_version_id, group_id)
            REFERENCES strategy_groups(strategy_version_id, group_id) ON DELETE RESTRICT
    )""",
    """CREATE TABLE source_retrievals (
        retrieval_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        source_name TEXT NOT NULL,
        source_record_id TEXT NOT NULL,
        retrieved_at_utc TEXT NOT NULL,
        original_metadata_json TEXT NOT NULL,
        UNIQUE (run_id, source_name, source_record_id),
        UNIQUE (retrieval_id, run_id, source_name),
        FOREIGN KEY (run_id) REFERENCES search_runs(run_id) ON DELETE RESTRICT
    )""",
    """CREATE TABLE query_retrievals (
        query_id TEXT NOT NULL,
        retrieval_id TEXT NOT NULL,
        run_id TEXT NOT NULL,
        source_name TEXT NOT NULL,
        PRIMARY KEY (query_id, retrieval_id),
        FOREIGN KEY (query_id, run_id, source_name)
            REFERENCES source_queries(query_id, run_id, source_name) ON DELETE RESTRICT,
        FOREIGN KEY (retrieval_id, run_id, source_name)
            REFERENCES source_retrievals(retrieval_id, run_id, source_name) ON DELETE RESTRICT
    )""",
    """CREATE TABLE publications (
        publication_id TEXT PRIMARY KEY,
        created_at_utc TEXT NOT NULL,
        chosen_metadata_json TEXT NOT NULL DEFAULT '{}'
    )""",
    """CREATE TABLE publication_retrievals (
        retrieval_id TEXT PRIMARY KEY,
        publication_id TEXT NOT NULL,
        decision_provenance_json TEXT NOT NULL,
        FOREIGN KEY (retrieval_id) REFERENCES source_retrievals(retrieval_id)
            ON DELETE RESTRICT,
        FOREIGN KEY (publication_id) REFERENCES publications(publication_id)
            ON DELETE RESTRICT
    )""",
    """CREATE TABLE containers (
        container_id TEXT PRIMARY KEY,
        metadata_json TEXT NOT NULL
    )""",
    """CREATE TABLE publication_containers (
        publication_id TEXT NOT NULL,
        container_id TEXT NOT NULL,
        PRIMARY KEY (publication_id, container_id),
        FOREIGN KEY (publication_id) REFERENCES publications(publication_id)
            ON DELETE RESTRICT,
        FOREIGN KEY (container_id) REFERENCES containers(container_id)
            ON DELETE RESTRICT
    )""",
    """CREATE TABLE organisations (
        organisation_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        metadata_json TEXT NOT NULL DEFAULT '{}'
    )""",
    """CREATE TABLE publication_organisations (
        publication_id TEXT NOT NULL,
        organisation_id TEXT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('issuing', 'collaborating', 'endorsing')),
        PRIMARY KEY (publication_id, organisation_id, role),
        FOREIGN KEY (publication_id) REFERENCES publications(publication_id)
            ON DELETE RESTRICT,
        FOREIGN KEY (organisation_id) REFERENCES organisations(organisation_id)
            ON DELETE RESTRICT
    )""",
    """CREATE TABLE classifications (
        classification_id TEXT PRIMARY KEY,
        publication_id TEXT NOT NULL,
        dimension TEXT NOT NULL,
        label TEXT NOT NULL,
        review_status TEXT NOT NULL,
        provenance_json TEXT NOT NULL,
        classified_at_utc TEXT NOT NULL,
        FOREIGN KEY (publication_id) REFERENCES publications(publication_id)
            ON DELETE RESTRICT
    )""",
    """CREATE TABLE documents (
        document_id TEXT PRIMARY KEY,
        publication_id TEXT,
        container_id TEXT,
        relative_path TEXT,
        external_url TEXT,
        provenance_json TEXT NOT NULL,
        CHECK (relative_path IS NOT NULL OR external_url IS NOT NULL),
        FOREIGN KEY (publication_id) REFERENCES publications(publication_id)
            ON DELETE RESTRICT,
        FOREIGN KEY (container_id) REFERENCES containers(container_id)
            ON DELETE RESTRICT
    )""",
    """CREATE INDEX source_retrievals_by_source
        ON source_retrievals(run_id, source_name)""",
    """CREATE INDEX query_retrievals_by_retrieval
        ON query_retrievals(retrieval_id)""",
    """CREATE INDEX publication_retrievals_by_publication
        ON publication_retrievals(publication_id)""",
    """CREATE INDEX classifications_by_publication
        ON classifications(publication_id)""",
    """CREATE TRIGGER immutable_strategy_versions_update
        BEFORE UPDATE ON strategy_versions
        BEGIN SELECT RAISE(ABORT, 'approved strategy versions are immutable'); END""",
    """CREATE TRIGGER immutable_strategy_versions_delete
        BEFORE DELETE ON strategy_versions
        BEGIN SELECT RAISE(ABORT, 'approved strategy versions are immutable'); END""",
    """CREATE TRIGGER immutable_strategy_groups_update
        BEFORE UPDATE ON strategy_groups
        BEGIN SELECT RAISE(ABORT, 'approved strategy groups are immutable'); END""",
    """CREATE TRIGGER immutable_strategy_groups_delete
        BEFORE DELETE ON strategy_groups
        BEGIN SELECT RAISE(ABORT, 'approved strategy groups are immutable'); END""",
    """CREATE TRIGGER immutable_audit_events_update
        BEFORE UPDATE ON audit_events
        BEGIN SELECT RAISE(ABORT, 'audit history is append-only'); END""",
    """CREATE TRIGGER immutable_audit_events_delete
        BEFORE DELETE ON audit_events
        BEGIN SELECT RAISE(ABORT, 'audit history is append-only'); END""",
)


def apply_v2_schema(connection) -> None:
    """Create the v2 tables in an existing caller-owned SQLite transaction."""
    for sql in V2_STATEMENTS:
        connection.execute(sql)
