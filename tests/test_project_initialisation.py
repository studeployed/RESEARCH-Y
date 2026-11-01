"""New-project transaction boundaries: PROJ-04, partial AT-01/09/21.

Use real disk-backed SQLite. No timing threshold, durability override, provider
request or reuse of a shared test database substitutes for the transaction gate.
"""
from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from uuid import UUID

import pytest

import research_y.projects as projects


def _project(tmp_path: Path) -> projects.Project:
    root = tmp_path / "creation"
    (root / "data").mkdir(parents=True)
    return projects.Project(
        root, UUID("12345678-1234-4123-8123-123456789000"),
        "Synthetic project", "2026-11-01T00:00:00+00:00",
    )


def _assert_empty_database(path: Path) -> None:
    # Reopening also asks SQLite to recover any hot rollback journal.
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert db.execute("SELECT name FROM sqlite_master").fetchall() == []
        assert db.execute("PRAGMA application_id").fetchone() == (0,)
        assert db.execute("PRAGMA user_version").fetchone() == (0,)


def test_all_creation_writes_share_one_transaction(tmp_path, monkeypatch):
    project = _project(tmp_path)
    connect = sqlite3.connect
    events = []
    settings = []

    def traced_connect(*args, **kwargs):
        db = connect(*args, **kwargs)
        before = tuple(db.execute(f"PRAGMA {p}").fetchone()[0]
                       for p in ("journal_mode", "synchronous"))
        settings.append(before)
        db.set_trace_callback(lambda sql: events.append(
            (" ".join(sql.upper().split()).rstrip(";"), db.in_transaction)
        ))
        return db

    monkeypatch.setattr(projects.sqlite3, "connect", traced_connect)
    projects._create_database(project.database_path, project)
    writes = [(sql, active) for sql, active in events if sql.startswith(
        ("CREATE ", "INSERT ", "PRAGMA APPLICATION_ID=", "PRAGMA USER_VERSION=")
    )]
    assert writes and all(active for _, active in writes)
    assert [sql for sql, _ in events if sql.startswith("BEGIN")] == ["BEGIN IMMEDIATE"]
    assert [sql for sql, _ in events if sql == "COMMIT"] == ["COMMIT"]
    assert not any(sql == "ROLLBACK" for sql, _ in events)
    assert not any(sql.startswith(("PRAGMA SYNCHRONOUS=", "PRAGMA JOURNAL_MODE="))
                   for sql, _ in events)
    with closing(connect(project.database_path)) as db:
        assert tuple(db.execute(f"PRAGMA {p}").fetchone()[0]
                     for p in ("journal_mode", "synchronous")) == settings[0]
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("SELECT COUNT(*) FROM audit_events").fetchone() == (1,)


def _legacy_database(path, project):
    """Reference the pre-fix statement order, not an alternative production API."""
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript(f"""
            PRAGMA application_id={projects.SQLITE_APPLICATION_ID};
            CREATE TABLE project_metadata (
                singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
                project_uuid TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                created_at_utc TEXT NOT NULL,
                theme TEXT NOT NULL DEFAULT '',
                objectives TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE audit_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                occurred_at_utc TEXT NOT NULL,
                event_type TEXT NOT NULL,
                details_json TEXT NOT NULL
            );
            PRAGMA user_version=1;
        """)
        projects.apply_v2_schema(db)
        projects.apply_v3_schema(db)
        projects.apply_v4_schema(db)
        db.execute(f"PRAGMA user_version={projects.SCHEMA_VERSION}")
        db.execute("INSERT INTO project_metadata "
                   "(singleton_id, project_uuid, name, created_at_utc) VALUES (1, ?, ?, ?)",
                   (str(project.identifier), project.name, project.created_at_utc))
        db.execute("INSERT INTO audit_events (occurred_at_utc, event_type, details_json) "
                   "VALUES (?, ?, ?)", (project.created_at_utc, "project_created",
                   json.dumps({"project_uuid": str(project.identifier)}, sort_keys=True)))


def test_logical_schema_and_contents_match_previous_initialiser(tmp_path):
    project = _project(tmp_path)
    legacy = tmp_path / "legacy.sqlite3"
    _legacy_database(legacy, project)
    projects._create_database(project.database_path, project)
    with closing(sqlite3.connect(legacy)) as before, closing(
        sqlite3.connect(project.database_path)
    ) as after:
        assert list(before.iterdump()) == list(after.iterdump())
        for setting in ("application_id", "user_version", "journal_mode", "synchronous"):
            assert before.execute(f"PRAGMA {setting}").fetchone() == after.execute(
                f"PRAGMA {setting}"
            ).fetchone()


@pytest.mark.parametrize("stage", ["apply_v2_schema", "apply_v3_schema", "apply_v4_schema"])
@pytest.mark.parametrize("error_type", [sqlite3.OperationalError, KeyboardInterrupt],
                         ids=["database-error", "interruption"])
def test_schema_stage_failure_rolls_back_all_creation(tmp_path, monkeypatch, stage, error_type):
    project = _project(tmp_path)
    original = getattr(projects, stage)

    def fail_after_stage(db):
        original(db)
        raise error_type("injected initialisation failure")

    monkeypatch.setattr(projects, stage, fail_after_stage)
    with pytest.raises(error_type):
        projects._create_database(project.database_path, project)
    _assert_empty_database(project.database_path)


@pytest.mark.parametrize("table", ["project_metadata", "audit_events"])
def test_insert_failure_rolls_back_schema_headers_and_identity(tmp_path, monkeypatch, table):
    project = _project(tmp_path)
    original = projects.apply_v4_schema

    def reject_insert(db):
        original(db)
        db.execute(f"CREATE TRIGGER reject_creation BEFORE INSERT ON {table} "
                   "BEGIN SELECT RAISE(ABORT, 'injected insertion failure'); END")

    monkeypatch.setattr(projects, "apply_v4_schema", reject_insert)
    with pytest.raises(sqlite3.IntegrityError, match="injected insertion failure"):
        projects._create_database(project.database_path, project)
    _assert_empty_database(project.database_path)


@pytest.mark.parametrize("failure", ["base-table", "schema-version", "commit"])
def test_base_header_or_commit_failure_is_atomic(tmp_path, monkeypatch, failure):
    project = _project(tmp_path)
    connect = sqlite3.connect

    def failing_connect(*args, **kwargs):
        db = connect(*args, **kwargs)

        def authorize(action, arg1, arg2, database, trigger):
            reject = (
                (failure == "base-table" and action == sqlite3.SQLITE_CREATE_TABLE
                 and arg1 == "audit_events")
                or (failure == "schema-version" and action == sqlite3.SQLITE_PRAGMA
                    and arg1 == "user_version" and arg2 == str(projects.SCHEMA_VERSION))
                or (failure == "commit" and action == sqlite3.SQLITE_TRANSACTION
                    and arg1 == "COMMIT")
            )
            return sqlite3.SQLITE_DENY if reject else sqlite3.SQLITE_OK

        db.set_authorizer(authorize)
        return db

    with monkeypatch.context() as patch:
        patch.setattr(projects.sqlite3, "connect", failing_connect)
        with pytest.raises(sqlite3.DatabaseError):
            projects._create_database(project.database_path, project)
    _assert_empty_database(project.database_path)


@pytest.mark.parametrize("error_type", [sqlite3.OperationalError, KeyboardInterrupt],
                         ids=["database-error", "interruption"])
def test_failed_public_creation_preserves_other_project_and_can_retry(
    tmp_path, monkeypatch, error_type,
):
    existing = projects.create_project(tmp_path, "Keep")
    projects.update_research_setup(existing, theme="Prior committed data")
    before = existing.database_path.read_bytes()
    original = projects.apply_v4_schema

    def fail(db):
        original(db)
        raise error_type("injected creation failure")

    with monkeypatch.context() as patch:
        patch.setattr(projects, "apply_v4_schema", fail)
        with pytest.raises(error_type):
            projects.create_project(tmp_path, "Retry")
    assert not (tmp_path / "Retry").exists()
    assert existing.database_path.read_bytes() == before
    retried = projects.create_project(tmp_path, "Retry")
    assert projects.open_project(retried.root) == retried
    assert projects.read_research_setup(existing).theme == "Prior committed data"
    with closing(sqlite3.connect(retried.database_path)) as db:
        assert db.execute("SELECT event_type FROM audit_events").fetchall() == [("project_created",)]


def test_terminated_initialiser_recovers_without_partial_schema(tmp_path):
    project = _project(tmp_path)
    child = """
import os, sys
from pathlib import Path
from uuid import UUID
from research_y import projects
project = projects.Project(Path(sys.argv[1]), UUID(sys.argv[2]), 'Child',
                           '2026-11-01T00:00:00+00:00')
original = projects.apply_v4_schema
def crash(db):
    original(db)
    db.execute('PRAGMA cache_size=2')
    db.execute('CREATE TABLE crash_spill (payload BLOB)')
    db.execute('INSERT INTO crash_spill VALUES (zeroblob(1048576))')
    os._exit(73)
projects.apply_v4_schema = crash
projects._create_database(project.database_path, project)
"""
    result = subprocess.run(
        [sys.executable, "-c", child, str(project.root), str(project.identifier)],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 73, result.stderr
    assert Path(str(project.database_path) + "-journal").exists()
    _assert_empty_database(project.database_path)
    # Recovery does not turn an unfinished directory into a valid project.
    assert not project.manifest_path.exists()
    with pytest.raises(projects.ProjectFormatError):
        projects.open_project(project.root)
