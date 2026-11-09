"""Version-4 to 5 migration and independently recoverable candidate-cache DDL."""
from __future__ import annotations

from contextlib import closing
import json
import sqlite3

import pytest

from research_y import projects
from research_y.candidate_index_schema import (
    V5_STATEMENTS, V5_TABLES, V5_TRIGGERS,
)
from research_y.candidate_pair_schema import V6_TABLES, V6_TRIGGERS
from research_y.candidate_index_build import preview_candidate_index


def historical_v4_project(tmp_path):
    project=projects.create_project(tmp_path,"Historical v4")
    with closing(sqlite3.connect(project.database_path)) as db:
        db.execute("PRAGMA foreign_keys=OFF")
        for trigger in V6_TRIGGERS:
            db.execute(f"DROP TRIGGER {trigger}")
        for name in V6_TABLES:
            db.execute(f"DROP TABLE {name}")
        for trigger in V5_TRIGGERS:
            db.execute(f"DROP TRIGGER {trigger}")
        for table in V5_TABLES:
            db.execute(f"DROP TABLE {table}")
        db.execute("PRAGMA user_version=4")
        db.commit()
    return project


def test_new_project_starts_with_v5_and_source_change_invalidation(tmp_path):
    p=projects.create_project(tmp_path,"Direct v5")
    with closing(sqlite3.connect(p.database_path)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0]==projects.SCHEMA_VERSION
        names={x[0] for x in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert set(V5_TABLES)<=names
        triggers={x[0] for x in db.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'")}
        assert set(V5_TRIGGERS)<=triggers
        assert db.execute("PRAGMA foreign_key_check").fetchall()==[]
    view=preview_candidate_index(p)
    assert view["status"]=="empty"
    assert view["global_unique_publications"] is None


def test_v4_upgrade_creates_separate_verified_backup_and_retains_original_rows(tmp_path):
    p=historical_v4_project(tmp_path)
    with closing(sqlite3.connect(p.database_path)) as db:
        original=db.execute("SELECT * FROM audit_events ORDER BY event_id").fetchall()
    migrated=projects.open_project(p.root)
    assert migrated==p
    backups=list((p.root/"backups").glob("researchy-before-v5-*.sqlite3"))
    assert len(backups)==1
    with closing(sqlite3.connect(backups[0])) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0]==4
        assert db.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
        assert db.execute("SELECT * FROM audit_events ORDER BY event_id").fetchall()==original
        assert db.execute("SELECT name FROM sqlite_master "
                          "WHERE name='candidate_index_state'").fetchone() is None
    with closing(sqlite3.connect(p.database_path)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0]==projects.SCHEMA_VERSION
        assert db.execute("PRAGMA foreign_key_check").fetchall()==[]
        assert db.execute("SELECT * FROM audit_events ORDER BY event_id").fetchall()[:-1]==original
        event=json.loads(db.execute(
            "SELECT details_json FROM audit_events ORDER BY event_id DESC LIMIT 1"
        ).fetchone()[0])
        assert event=={"from_version":4,"to_version":projects.SCHEMA_VERSION,"backup":backups[0].name}
    assert preview_candidate_index(p)["status"]=="empty"
    for _ in range(2):
        assert projects.open_project(p.root)==p
    assert len(list((p.root/"backups").glob("researchy-before-v5-*.sqlite3")))==1


def test_failed_v5_ddl_rolls_back_and_original_v4_remains_recoverable(tmp_path,monkeypatch):
    p=historical_v4_project(tmp_path)
    with closing(sqlite3.connect(p.database_path)) as db:
        initial=db.execute("SELECT * FROM audit_events ORDER BY event_id").fetchall()
    def fail(db):
        db.execute(V5_STATEMENTS[0])
        raise RuntimeError("Injected candidate index migration interruption")
    with monkeypatch.context() as m:
        m.setattr(projects,"apply_v5_schema",fail)
        with pytest.raises(projects.ProjectMigrationError,match="snapshot preserved"):
            projects.open_project(p.root)
    with closing(sqlite3.connect(p.database_path)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0]==4
        assert db.execute("SELECT name FROM sqlite_master "
                          "WHERE name='candidate_index_state'").fetchone() is None
        assert db.execute("SELECT * FROM audit_events ORDER BY event_id").fetchall()==initial
    assert len(list((p.root/"backups").glob("researchy-before-v5-*.sqlite3")))==1
    assert projects.open_project(p.root)==p


def test_failed_v4_snapshot_prevents_all_index_schema_modification(tmp_path,monkeypatch):
    p=historical_v4_project(tmp_path)
    def fail(*a,**kw):
        raise projects.ProjectMigrationError("backup unavailable")
    with monkeypatch.context() as m:
        m.setattr(projects,"_snapshot_before_upgrade",fail)
        with pytest.raises(projects.ProjectMigrationError,match="backup unavailable"):
            projects.open_project(p.root)
    with closing(sqlite3.connect(p.database_path)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0]==4
        assert db.execute("SELECT name FROM sqlite_master "
                          "WHERE name='candidate_index_state'").fetchone() is None
    assert list((p.root/"backups").iterdir())==[]


def test_project_identity_mismatch_blocks_v4_to_v5_before_snapshot(tmp_path):
    p=historical_v4_project(tmp_path)
    with closing(sqlite3.connect(p.database_path)) as db,db:
        db.execute("UPDATE project_metadata SET project_uuid='untrusted' "
                   "WHERE singleton_id=1")
    with pytest.raises(projects.ProjectFormatError,match="identity"):
        projects.open_project(p.root)
    assert list((p.root/"backups").iterdir())==[]
