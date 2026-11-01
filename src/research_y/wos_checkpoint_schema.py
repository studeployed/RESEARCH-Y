"""Schema v4: additive, transactional Web of Science retrieval checkpoints.

Raw licensed payloads remain local; public diagnostics must use aggregates.
No SQL in this module commits the caller's migration transaction.
"""

WOS_TABLES = (
    "wos_checkpoint_verifications", "wos_checkpoint_ids", "wos_checkpoint_pages",
    "wos_checkpoint_observations", "wos_checkpoint_attempts", "wos_checkpoint_jobs",
)

V4_STATEMENTS = (
    """CREATE TABLE wos_checkpoint_jobs (
        query_id TEXT PRIMARY KEY REFERENCES source_queries(query_id) ON DELETE RESTRICT,
        plan_json TEXT NOT NULL,
        plan_sha256 TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending'
          CHECK(status IN ('pending','running','paused','incomplete','cancelled','completed_with_warnings')),
        stage TEXT NOT NULL DEFAULT 'acquire' CHECK(stage IN ('acquire','verify','final','done')),
        baseline_count INTEGER CHECK(baseline_count IS NULL OR baseline_count >= 0),
        next_page INTEGER NOT NULL DEFAULT 1 CHECK(next_page >= 1),
        verify_page INTEGER NOT NULL DEFAULT 1 CHECK(verify_page >= 1),
        verify_epoch INTEGER NOT NULL DEFAULT 0 CHECK(verify_epoch >= 0),
        failures INTEGER NOT NULL DEFAULT 0 CHECK(failures >= 0),
        reason_code TEXT NOT NULL DEFAULT 'not_started',
        quota_json TEXT NOT NULL DEFAULT '{}',
        not_before_utc TEXT,
        owner_token TEXT,
        created_at_utc TEXT NOT NULL,
        updated_at_utc TEXT NOT NULL
    )""",
    """CREATE UNIQUE INDEX one_wos_worker_per_project
        ON wos_checkpoint_jobs((1)) WHERE owner_token IS NOT NULL""",
    """CREATE TABLE wos_checkpoint_attempts (
        attempt_id TEXT PRIMARY KEY,
        query_id TEXT NOT NULL REFERENCES wos_checkpoint_jobs(query_id) ON DELETE RESTRICT,
        owner_token TEXT NOT NULL,
        purpose TEXT NOT NULL CHECK(purpose IN ('probe','acquire','verify','final')),
        page_number INTEGER NOT NULL CHECK(page_number > 0),
        page_size INTEGER NOT NULL CHECK(page_size BETWEEN 1 AND 50),
        started_at_utc TEXT NOT NULL,
        finished_at_utc TEXT,
        outcome TEXT NOT NULL DEFAULT 'started' CHECK(outcome IN ('started','success','error','abandoned')),
        reason_code TEXT,
        http_status INTEGER,
        sent INTEGER CHECK(sent IS NULL OR sent IN (0,1)),
        quota_json TEXT NOT NULL DEFAULT '{}'
    )""",
    """CREATE UNIQUE INDEX one_wos_request_in_flight
        ON wos_checkpoint_attempts(query_id) WHERE outcome='started'""",
    """CREATE TABLE wos_checkpoint_observations (
        attempt_id TEXT PRIMARY KEY REFERENCES wos_checkpoint_attempts(attempt_id) ON DELETE RESTRICT,
        response_json TEXT NOT NULL,
        response_sha256 TEXT NOT NULL,
        descriptor_json TEXT NOT NULL,
        descriptor_sha256 TEXT NOT NULL
    )""",
    """CREATE TABLE wos_checkpoint_pages (
        query_id TEXT NOT NULL REFERENCES wos_checkpoint_jobs(query_id) ON DELETE RESTRICT,
        page_number INTEGER NOT NULL CHECK(page_number > 0),
        attempt_id TEXT NOT NULL UNIQUE REFERENCES wos_checkpoint_observations(attempt_id) ON DELETE RESTRICT,
        uid_sha256 TEXT NOT NULL,
        PRIMARY KEY(query_id, page_number)
    )""",
    """CREATE TABLE wos_checkpoint_ids (
        query_id TEXT NOT NULL,
        uid TEXT NOT NULL,
        page_number INTEGER NOT NULL,
        ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
        retrieval_id TEXT NOT NULL REFERENCES source_retrievals(retrieval_id) ON DELETE RESTRICT,
        record_sha256 TEXT NOT NULL,
        PRIMARY KEY(query_id, uid),
        UNIQUE(query_id, page_number, ordinal),
        FOREIGN KEY(query_id,page_number) REFERENCES wos_checkpoint_pages(query_id,page_number) ON DELETE RESTRICT
    )""",
    """CREATE TABLE wos_checkpoint_verifications (
        query_id TEXT NOT NULL,
        epoch INTEGER NOT NULL CHECK(epoch > 0),
        page_number INTEGER NOT NULL,
        attempt_id TEXT NOT NULL UNIQUE REFERENCES wos_checkpoint_observations(attempt_id) ON DELETE RESTRICT,
        PRIMARY KEY(query_id,epoch,page_number),
        FOREIGN KEY(query_id,page_number) REFERENCES wos_checkpoint_pages(query_id,page_number) ON DELETE RESTRICT
    )""",
    """CREATE INDEX wos_attempts_by_query ON wos_checkpoint_attempts(query_id,started_at_utc)""",
    """CREATE TRIGGER immutable_wos_plan
        BEFORE UPDATE OF plan_json,plan_sha256,query_id,created_at_utc ON wos_checkpoint_jobs
        BEGIN SELECT RAISE(ABORT,'WoS plan is immutable'); END""",
    """CREATE TRIGGER immutable_wos_baseline
        BEFORE UPDATE OF baseline_count ON wos_checkpoint_jobs
        WHEN OLD.baseline_count IS NOT NULL AND NEW.baseline_count IS NOT OLD.baseline_count
        BEGIN SELECT RAISE(ABORT,'WoS baseline is immutable'); END""",
    """CREATE TRIGGER immutable_wos_query_identity
        BEFORE UPDATE OF query_id,run_id,strategy_version_id,group_id,source_name,exact_query,parameters_json
        ON source_queries WHEN EXISTS(SELECT 1 FROM wos_checkpoint_jobs WHERE query_id=OLD.query_id)
        BEGIN SELECT RAISE(ABORT,'checkpointed WoS query is immutable'); END""",
    """CREATE TRIGGER immutable_wos_finished_attempt
        BEFORE UPDATE ON wos_checkpoint_attempts WHEN OLD.outcome != 'started'
        BEGIN SELECT RAISE(ABORT,'finished WoS attempt is immutable'); END""",
    """CREATE TRIGGER immutable_wos_attempt_identity
        BEFORE UPDATE OF attempt_id,query_id,owner_token,purpose,page_number,page_size,started_at_utc
        ON wos_checkpoint_attempts
        BEGIN SELECT RAISE(ABORT,'WoS attempt identity is immutable'); END""",
)


def apply_v4_schema(connection) -> None:
    for statement in V4_STATEMENTS:
        connection.execute(statement)
    for table in WOS_TABLES:
        connection.execute(f"""CREATE TRIGGER immutable_{table}_delete
            BEFORE DELETE ON {table}
            BEGIN SELECT RAISE(ABORT,'WoS history is immutable'); END""")
        if table not in ('wos_checkpoint_jobs', 'wos_checkpoint_attempts'):
            connection.execute(f"""CREATE TRIGGER immutable_{table}_update
                BEFORE UPDATE ON {table}
                BEGIN SELECT RAISE(ABORT,'WoS history is immutable'); END""")
