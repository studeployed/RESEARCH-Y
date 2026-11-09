"""Schema-v5 to v6 source-pair checkpoint migrations and recovery gates."""
from __future__ import annotations

from contextlib import closing
import json
import sqlite3

import pytest

from research_y import projects
from research_y.candidate_pair_schema import (
    V6_STATEMENTS,V6_TABLES,V6_TRIGGERS,
)


def historical_v5_project(tmp_path):
    p=projects.create_project(tmp_path,"Historical v5 source index")
    with closing(sqlite3.connect(p.database_path)) as db:
        db.execute("PRAGMA foreign_keys=OFF")
        for name in V6_TRIGGERS:
            db.execute(f"DROP TRIGGER {name}")
        for name in V6_TABLES:
            db.execute(f"DROP TABLE {name}")
        db.execute("PRAGMA user_version=5")
        db.commit()
    return p


def test_new_projects_have_pair_tables_without_premature_pair_decisions(tmp_path):
    p=projects.create_project(tmp_path,"New pair checkpoint schema")
    with closing(sqlite3.connect(p.database_path)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0]==6
        tables={r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        triggers={r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'")}
        assert set(V6_TABLES)<=tables
        assert set(V6_TRIGGERS)<=triggers
        assert db.execute("PRAGMA foreign_key_check").fetchall()==[]
        assert db.execute("SELECT COUNT(*) FROM candidate_pair_builds").fetchone()==(0,)
        assert db.execute("SELECT COUNT(*) FROM candidate_pair_hints").fetchone()==(0,)


def test_v5_upgrade_has_verified_snapshot_and_preserves_original_audit(tmp_path):
    p=historical_v5_project(tmp_path)
    with closing(sqlite3.connect(p.database_path)) as db:
        original=db.execute(
            "SELECT * FROM audit_events ORDER BY event_id").fetchall()
    assert projects.open_project(p.root)==p
    snapshots=list((p.root/"backups").glob("researchy-before-v6-*.sqlite3"))
    assert len(snapshots)==1
    with closing(sqlite3.connect(snapshots[0])) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0]==5
        assert db.execute("PRAGMA integrity_check").fetchone()==("ok",)
        assert db.execute(
            "SELECT name FROM sqlite_master WHERE name='candidate_pair_builds'"
        ).fetchone() is None
        assert db.execute("SELECT * FROM audit_events ORDER BY event_id").fetchall()==original
    with closing(sqlite3.connect(p.database_path)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0]==6
        assert db.execute("PRAGMA foreign_key_check").fetchall()==[]
        events=db.execute("SELECT * FROM audit_events ORDER BY event_id").fetchall()
        assert events[:-1]==original
        detail=json.loads(events[-1][3]) if len(events[-1])>3 else json.loads(events[-1][-1])
        assert detail=={"from_version":5,"to_version":6,"backup":snapshots[0].name}
    assert projects.open_project(p.root)==p
    assert len(list((p.root/"backups").glob("researchy-before-v6-*.sqlite3")))==1


def test_injected_partial_v6_ddl_preserves_original_v5_on_retry(tmp_path,monkeypatch):
    p=historical_v5_project(tmp_path)
    before=sqlite3.connect(p.database_path)
    before.close()
    def fail(db):
        db.execute(V6_STATEMENTS[0])
        raise RuntimeError("injected pair-index migration failure")
    with monkeypatch.context() as m:
        m.setattr(projects,"apply_v6_schema",fail)
        with pytest.raises(projects.ProjectMigrationError,match="snapshot preserved"):
            projects.open_project(p.root)
    with closing(sqlite3.connect(p.database_path)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0]==5
        assert db.execute(
            "SELECT name FROM sqlite_master WHERE name='candidate_pair_builds'"
        ).fetchone() is None
    assert len(list((p.root/"backups").glob("researchy-before-v6-*.sqlite3")))==1
    assert projects.open_project(p.root)==p


def test_failed_migration_snapshot_blocks_all_pair_tables(tmp_path,monkeypatch):
    p=historical_v5_project(tmp_path)
    def fail(*args,**kwargs):
        raise projects.ProjectMigrationError("snapshot unavailable")
    with monkeypatch.context() as m:
        m.setattr(projects,"_snapshot_before_upgrade",fail)
        with pytest.raises(projects.ProjectMigrationError,match="snapshot unavailable"):
            projects.open_project(p.root)
    with closing(sqlite3.connect(p.database_path)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0]==5
        assert db.execute(
            "SELECT name FROM sqlite_master WHERE name='candidate_pair_builds'"
        ).fetchone() is None
    assert list((p.root/"backups").iterdir())==[]


def test_mismatched_manifest_prevents_v5_upgrade_without_snapshot(tmp_path):
    p=historical_v5_project(tmp_path)
    with closing(sqlite3.connect(p.database_path)) as db,db:
        db.execute("UPDATE project_metadata SET project_uuid='not-original'")
    with pytest.raises(projects.ProjectFormatError,match="identity"):
        projects.open_project(p.root)
    assert list((p.root/"backups").iterdir())==[]
