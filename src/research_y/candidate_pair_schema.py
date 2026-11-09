"""Schema v6: source-backed, explicitly incomplete candidate-pair checkpoints.

A cached pair is an *exact-key review hint*, not a publication identity or an
automatic deduplication decision. All original provider/source/audit records
remain authoritative; these derived rows are safely disposable.
"""
V6_TABLES = ("candidate_pair_hints", "candidate_pair_builds")
V6_TRIGGERS = (
    "candidate_pairs_source_insert", "candidate_pairs_source_update",
    "candidate_pairs_source_delete", "candidate_pairs_link_insert",
    "candidate_pairs_link_update", "candidate_pairs_link_delete",
    "candidate_pairs_new_review_decision",
)

V6_STATEMENTS = (
    """CREATE TABLE candidate_pair_builds (
        run_id TEXT PRIMARY KEY REFERENCES search_runs(run_id) ON DELETE RESTRICT,
        generation_id TEXT NOT NULL,
        source_index_generation TEXT NOT NULL,
        source_index_epoch INTEGER NOT NULL CHECK(source_index_epoch>=0),
        status TEXT NOT NULL CHECK(status IN ('building','ready_keys_only','stale')),
        cursor_retrieval_id TEXT,
        cursor_field TEXT,
        cursor_other_id TEXT,
        processed_source_keys INTEGER NOT NULL DEFAULT 0 CHECK(processed_source_keys>=0),
        emitted_hints INTEGER NOT NULL DEFAULT 0 CHECK(emitted_hints>=0),
        unique_pairs INTEGER NOT NULL DEFAULT 0 CHECK(unique_pairs>=0),
        running_sha256 TEXT NOT NULL,
        started_at_utc TEXT NOT NULL,
        updated_at_utc TEXT NOT NULL,
        CHECK((cursor_retrieval_id IS NULL AND cursor_field IS NULL
                   AND cursor_other_id IS NULL) OR
              (cursor_retrieval_id IS NOT NULL AND
               cursor_field IN ('doi','pmid','accession','title')))
    )""",
    """CREATE TABLE candidate_pair_hints (
        run_id TEXT NOT NULL REFERENCES candidate_pair_builds(run_id)
            ON DELETE CASCADE,
        generation_id TEXT NOT NULL,
        left_retrieval_id TEXT NOT NULL
            REFERENCES source_retrievals(retrieval_id) ON DELETE CASCADE,
        right_retrieval_id TEXT NOT NULL
            REFERENCES source_retrievals(retrieval_id) ON DELETE CASCADE,
        fields_mask INTEGER NOT NULL CHECK(fields_mask BETWEEN 1 AND 15),
        PRIMARY KEY(run_id,left_retrieval_id,right_retrieval_id),
        CHECK(left_retrieval_id<right_retrieval_id)
    )""",
    """CREATE INDEX candidate_pair_hints_by_run
        ON candidate_pair_hints(run_id, generation_id,
                                left_retrieval_id, right_retrieval_id)""",
    # All source, link or explicit review-decision mutations invalidate any
    # building/ready materialisation in the *same original source transaction*.
    """CREATE TRIGGER candidate_pairs_source_insert
        AFTER INSERT ON source_retrievals BEGIN
          UPDATE candidate_pair_builds SET status='stale'
          WHERE status IN ('building','ready_keys_only'); END""",
    """CREATE TRIGGER candidate_pairs_source_update
        AFTER UPDATE ON source_retrievals BEGIN
          UPDATE candidate_pair_builds SET status='stale'
          WHERE status IN ('building','ready_keys_only'); END""",
    """CREATE TRIGGER candidate_pairs_source_delete
        AFTER DELETE ON source_retrievals BEGIN
          UPDATE candidate_pair_builds SET status='stale'
          WHERE status IN ('building','ready_keys_only'); END""",
    """CREATE TRIGGER candidate_pairs_link_insert
        AFTER INSERT ON publication_retrievals BEGIN
          UPDATE candidate_pair_builds SET status='stale'
          WHERE status IN ('building','ready_keys_only'); END""",
    """CREATE TRIGGER candidate_pairs_link_update
        AFTER UPDATE ON publication_retrievals BEGIN
          UPDATE candidate_pair_builds SET status='stale'
          WHERE status IN ('building','ready_keys_only'); END""",
    """CREATE TRIGGER candidate_pairs_link_delete
        AFTER DELETE ON publication_retrievals BEGIN
          UPDATE candidate_pair_builds SET status='stale'
          WHERE status IN ('building','ready_keys_only'); END""",
    """CREATE TRIGGER candidate_pairs_new_review_decision
        AFTER INSERT ON audit_events
        WHEN NEW.event_type='publication_candidate_decision_v1'
        BEGIN
          UPDATE candidate_pair_builds SET status='stale'
          WHERE status IN ('building','ready_keys_only');
        END""",
)


def apply_v6_schema(connection) -> None:
    """Apply all DDL in the caller's existing atomic migration transaction."""
    for statement in V6_STATEMENTS:
        connection.execute(statement)
