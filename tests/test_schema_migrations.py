"""Offline schema-v2 integrity and v1→v2 migration/recovery fixtures.

The metadata tables are storage contracts only; they do not claim that a source
has been searched, a dataset reconciled, or deduplication implemented.
"""

from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3

import pytest

import research_y.projects as project_module
from research_y.projects import (
    Project,
    ProjectFormatError,
    ProjectMigrationError,
    ProjectVersionError,
    create_project,
    open_project,
    read_research_setup,
    update_research_setup,
)
from research_y.schema import SCHEMA_VERSION, V2_STATEMENTS


def _connection(project: Project) -> sqlite3.Connection:
    connection = sqlite3.connect(project.database_path)
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _legacy_v1_fixture(project: Project) -> None:
    """Replace the new database with the actual original v1 schema/identity."""
    project.database_path.unlink()
    with closing(sqlite3.connect(project.database_path)) as connection, connection:
        connection.executescript(
            f"""
            PRAGMA application_id={project_module.SQLITE_APPLICATION_ID};
            PRAGMA user_version=1;
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
            """
        )
        connection.execute(
            "INSERT INTO project_metadata VALUES (1, ?, ?, ?, ?, ?)",
            (str(project.identifier), project.name, project.created_at_utc,
             "Pre-existing research theme", "Retain these objectives"),
        )
        connection.execute(
            "INSERT INTO audit_events (occurred_at_utc, event_type, details_json) "
            "VALUES (?, ?, ?)",
            (project.created_at_utc, "legacy_note", '{"legacy":true}'),
        )


def test_new_projects_start_on_v2_and_have_distinct_entities(tmp_path: Path) -> None:
    project = create_project(tmp_path, "New schema")
    expected = {
        "project_metadata", "audit_events", "strategy_versions", "strategy_groups",
        "search_runs", "source_queries", "source_retrievals", "query_retrievals",
        "publications", "publication_retrievals", "containers", "publication_containers",
        "organisations", "publication_organisations", "classifications", "documents",
    }
    with closing(_connection(project)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 3
        tables = {
            row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert expected <= tables
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_cross_source_group_membership_and_one_publication(tmp_path: Path) -> None:
    """One publication can occur in both sources and multiple OR groups."""
    project = create_project(tmp_path, "Bibliography relationships")
    with closing(_connection(project)) as db, db:
        db.execute(
            "INSERT INTO strategy_versions VALUES (?, ?, ?, ?)",
            ("s1", 1, "2026-10-24T08:00:00+00:00", '{"terms":["ventricle"]}'),
        )
        db.executemany(
            "INSERT INTO strategy_groups VALUES (?, ?, ?, ?)",
            [("s1", "g1", "Right heart", 0), ("s1", "g2", "Extracorporeal", 1)],
        )
        db.execute(
            "INSERT INTO search_runs (run_id, strategy_version_id, created_at_utc) "
            "VALUES ('run1', 's1', '2026-10-24T08:01:00+00:00')"
        )
        db.executemany(
            "INSERT INTO source_queries "
            "(query_id, run_id, strategy_version_id, group_id, source_name, exact_query) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("q1", "run1", "s1", "g1", "pubmed", "ventricle[All Fields]"),
                ("q2", "run1", "s1", "g2", "pubmed", "ECMO[All Fields]"),
                ("q3", "run1", "s1", "g2", "wos", "TS=(ECMO)"),
            ],
        )
        db.executemany(
            "INSERT INTO source_retrievals VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("r1", "run1", "pubmed", "1234", "2026-10-24T08:02:00+00:00", '{"pmid":"1234"}'),
                ("r2", "run1", "wos", "WOS:1234", "2026-10-24T08:03:00+00:00", '{"uid":"WOS:1234"}'),
            ],
        )
        db.executemany(
            "INSERT INTO query_retrievals VALUES (?, ?, ?, ?)",
            [
                ("q1", "r1", "run1", "pubmed"),
                ("q2", "r1", "run1", "pubmed"),
                ("q3", "r2", "run1", "wos"),
            ],
        )
        db.execute("INSERT INTO publications VALUES ('p1', '2026-10-24T08:04:00+00:00', '{}')")
        db.executemany(
            "INSERT INTO publication_retrievals VALUES (?, ?, ?)",
            [("r1", "p1", '{"rule":"doi"}'), ("r2", "p1", '{"rule":"doi"}')],
        )
        assert db.execute("SELECT COUNT(*) FROM publications").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM source_retrievals").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM query_retrievals").fetchone()[0] == 3
        assert db.execute("SELECT COUNT(DISTINCT group_id) FROM source_queries").fetchone()[0] == 2
        assert db.execute("SELECT reported_matches FROM source_queries WHERE query_id='q1'").fetchone()[0] is None
        with pytest.raises(sqlite3.IntegrityError):
            # A WoS retrieval cannot be attached to a PubMed query.
            db.execute("INSERT INTO query_retrievals VALUES ('q1','r2','run1','pubmed')")
        with pytest.raises(sqlite3.IntegrityError):
            # A query cannot reference a group of a different strategy version.
            db.execute(
                "INSERT INTO source_queries (query_id,run_id,strategy_version_id,group_id,source_name,exact_query) "
                "VALUES ('bad','run1','s1','unknown','pubmed','x')"
            )
    assert open_project(project.root).identifier == project.identifier


def test_strategy_snapshot_and_existing_audit_events_are_immutable(tmp_path: Path) -> None:
    project = create_project(tmp_path, "Audit")
    with closing(_connection(project)) as db, db:
        db.execute("INSERT INTO strategy_versions VALUES ('s1',1,'2026-10-24T08:00Z','{}')")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("UPDATE strategy_versions SET snapshot_json='[]' WHERE strategy_version_id='s1'")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("DELETE FROM strategy_versions WHERE strategy_version_id='s1'")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute("DELETE FROM audit_events")
    update_research_setup(project, theme="Audited change")
    assert read_research_setup(project).theme == "Audited change"


def test_v1_upgrades_with_pre_migration_snapshot_and_preserves_data(tmp_path: Path) -> None:
    project = create_project(tmp_path, "Existing version one")
    _legacy_v1_fixture(project)
    reopened = open_project(project.root)
    assert reopened.identifier == project.identifier
    setup = read_research_setup(reopened)
    assert (setup.theme, setup.objectives) == (
        "Pre-existing research theme", "Retain these objectives",
    )
    backups = list((project.root / "backups").glob("researchy-before-v2-*.sqlite3"))
    assert len(backups) == 1
    with closing(_connection(project)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 3
        assert db.execute("SELECT event_type FROM audit_events ORDER BY event_id").fetchall() == [
            ("legacy_note",), ("schema_migrated",)
        ]
        details = json.loads(db.execute(
            "SELECT details_json FROM audit_events WHERE event_type='schema_migrated'"
        ).fetchone()[0])
        assert details == {"from_version": 1, "to_version": 3, "backup": backups[0].name}
    with closing(sqlite3.connect(backups[0])) as snapshot:
        assert snapshot.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert snapshot.execute("PRAGMA user_version").fetchone()[0] == 1
        assert snapshot.execute("SELECT theme FROM project_metadata").fetchone()[0] == (
            "Pre-existing research theme"
        )
        assert "strategy_versions" not in {
            x[0] for x in snapshot.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }


def test_migration_runs_once_and_never_repeats_backup(tmp_path: Path) -> None:
    project = create_project(tmp_path, "Legacy")
    _legacy_v1_fixture(project)
    for _ in range(3):
        reopened = open_project(project.root)
        assert read_research_setup(reopened).theme == "Pre-existing research theme"
    assert len(list((project.root / "backups").glob("researchy-before-v2-*.sqlite3"))) == 1
    with closing(_connection(project)) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM audit_events WHERE event_type='schema_migrated'"
        ).fetchone()[0] == 1


def test_failed_migration_rolls_back_schema_and_preserves_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(tmp_path, "Migration rollback")
    _legacy_v1_fixture(project)
    original_schema = project_module.apply_v2_schema

    def fail_after_first_table(connection: sqlite3.Connection) -> None:
        connection.execute(V2_STATEMENTS[0])
        raise RuntimeError("simulated migration interruption")

    with monkeypatch.context() as m:
        m.setattr(project_module, "apply_v2_schema", fail_after_first_table)
        with pytest.raises(ProjectMigrationError, match="snapshot preserved"):
            open_project(project.root)
    backups = list((project.root / "backups").glob("researchy-before-v2-*.sqlite3"))
    assert len(backups) == 1
    with closing(_connection(project)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert db.execute("SELECT theme FROM project_metadata").fetchone()[0] == (
            "Pre-existing research theme"
        )
        assert db.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 1
        assert "strategy_versions" not in {
            x[0] for x in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    with closing(sqlite3.connect(backups[0])) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert project_module.apply_v2_schema is original_schema
    assert open_project(project.root).identifier == project.identifier


def test_mismatched_identity_cannot_trigger_schema_migration(tmp_path: Path) -> None:
    project = create_project(tmp_path, "Legacy mismatch")
    _legacy_v1_fixture(project)
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute("UPDATE project_metadata SET project_uuid='wrong' WHERE singleton_id=1")
    with pytest.raises(ProjectFormatError, match="identity"):
        open_project(project.root)
    assert not list((project.root / "backups").iterdir())
    with closing(sqlite3.connect(project.database_path)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1


def test_unknown_future_schema_is_not_migrated_or_overwritten(tmp_path: Path) -> None:
    project = create_project(tmp_path, "Future")
    with closing(_connection(project)) as db, db:
        db.execute("PRAGMA user_version=99")
    with pytest.raises(ProjectVersionError, match="Unsupported database schema"):
        open_project(project.root)
    assert not list((project.root / "backups").iterdir())


def test_failed_snapshot_prevents_all_schema_modifications(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(tmp_path, "No snapshot")
    _legacy_v1_fixture(project)

    def reject_snapshot(*_args: object) -> None:
        raise ProjectMigrationError("simulated backup failure")

    with monkeypatch.context() as m:
        m.setattr(project_module, "_snapshot_before_upgrade", reject_snapshot)
        with pytest.raises(ProjectMigrationError, match="simulated backup failure"):
            open_project(project.root)
    with closing(_connection(project)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 1
    assert not list((project.root / "backups").iterdir())



def _simulate_existing_v2(project: project_module.Project) -> None:
    """Construct an unmodified schema-v2 database, preserving its source data."""
    with closing(sqlite3.connect(project.database_path)) as db:
        db.execute("PRAGMA foreign_keys=OFF")
        for name in (
            "immutable_pubmed_checkpoint_pages_update",
            "immutable_pubmed_checkpoint_pages_delete",
            "immutable_pubmed_checkpoint_ids_update",
            "immutable_pubmed_checkpoint_ids_delete",
        ):
            db.execute(f"DROP TRIGGER {name}")
        db.execute("DROP TABLE pubmed_checkpoint_ids")
        db.execute("DROP TABLE pubmed_checkpoint_pages")
        db.execute("DROP TABLE pubmed_checkpoint_runs")
        db.execute("PRAGMA user_version=2")


def test_v2_to_v3_migration_creates_independent_verified_snapshot(tmp_path: Path) -> None:
    project = create_project(tmp_path, "Upgrading original v2")
    _simulate_existing_v2(project)
    reopened = open_project(project.root)
    assert reopened.identifier == project.identifier
    backups = list((project.root / "backups").glob("researchy-before-v3-*.sqlite3"))
    assert len(backups) == 1
    with closing(sqlite3.connect(backups[0])) as snapshot:
        assert snapshot.execute("PRAGMA user_version").fetchone()[0] == 2
        assert snapshot.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert snapshot.execute(
            "SELECT name FROM sqlite_master WHERE name='pubmed_checkpoint_pages'"
        ).fetchone() is None
    with closing(sqlite3.connect(project.database_path)) as upgraded:
        assert upgraded.execute("PRAGMA user_version").fetchone()[0] == 3
        assert upgraded.execute(
            "SELECT name FROM sqlite_master WHERE name='pubmed_checkpoint_pages'"
        ).fetchone() == ("pubmed_checkpoint_pages",)
        payload = upgraded.execute(
            "SELECT details_json FROM audit_events WHERE event_type='schema_migrated' "
            "ORDER BY event_id DESC LIMIT 1"
        ).fetchone()[0]
        assert json.loads(payload)["from_version"] == 2
        assert json.loads(payload)["to_version"] == 3
    assert open_project(project.root).identifier == project.identifier
    assert len(list((project.root / "backups").glob("researchy-before-v3-*.sqlite3"))) == 1


def test_interrupted_v2_to_v3_migration_rolls_back_and_preserves_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from research_y.checkpoint_schema import V3_STATEMENTS

    project = create_project(tmp_path, "Interrupted v3 migration")
    _simulate_existing_v2(project)
    original = project_module.apply_v3_schema

    def fail_after_first_table(db: sqlite3.Connection) -> None:
        db.execute(V3_STATEMENTS[0])
        raise RuntimeError("simulated interruption")

    with monkeypatch.context() as patch:
        patch.setattr(project_module, "apply_v3_schema", fail_after_first_table)
        with pytest.raises(ProjectMigrationError, match="snapshot preserved"):
            open_project(project.root)
    with closing(sqlite3.connect(project.database_path)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
        assert db.execute(
            "SELECT name FROM sqlite_master WHERE name='pubmed_checkpoint_runs'"
        ).fetchone() is None
    backups = list((project.root / "backups").glob("researchy-before-v3-*.sqlite3"))
    assert len(backups) == 1
    assert project_module.apply_v3_schema is original
    assert open_project(project.root).identifier == project.identifier
