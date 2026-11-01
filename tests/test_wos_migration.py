"""Version-3 project migration, consistent snapshots and failure rollback."""
from contextlib import closing
import json
import sqlite3
import pytest
import research_y.projects as projects
from research_y.storage import ApprovedTerm, StrategyGroup, approve_strategy, create_search_run, plan_source_query
from research_y.wos_checkpoint_schema import WOS_TABLES, V4_STATEMENTS
from research_y.wos_checkpoint_store import create_wos_checkpoint


def v3_project(tmp_path):
    p=projects.create_project(tmp_path,'Legacy three')
    version=approve_strategy(p,theme='ECMO',groups=(StrategyGroup('g','ECMO',(ApprovedTerm('ECMO','researcher',True),)),),approved_by='R',approval_confirmed=True)
    run=create_search_run(p,version.strategy_version_id)
    q=plan_source_query(p,run_id=run.run_id,group_id='g',source_name='wos',exact_query='TS=("ECMO")')
    with closing(sqlite3.connect(p.database_path)) as db:
        db.execute('PRAGMA foreign_keys=OFF')
        db.execute('DROP TRIGGER immutable_wos_query_identity')
        for name in WOS_TABLES:db.execute(f'DROP TABLE {name}')
        db.execute('PRAGMA user_version=3')
        db.commit()
    return p,q


def test_v3_migration_once_preserves_original_query_and_consistent_snapshot(tmp_path):
    p,q=v3_project(tmp_path)
    with closing(sqlite3.connect(p.database_path)) as db:
        old_audit=db.execute('SELECT * FROM audit_events ORDER BY event_id').fetchall()
    for _ in range(3):assert projects.open_project(p.root).identifier==p.identifier
    backups=list((p.root/'backups').glob('researchy-before-v4-*.sqlite3'))
    assert len(backups)==1
    with closing(sqlite3.connect(backups[0])) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]==3
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert db.execute('SELECT * FROM audit_events ORDER BY event_id').fetchall()==old_audit
        assert db.execute("SELECT name FROM sqlite_master WHERE name='wos_checkpoint_jobs'").fetchone() is None
    with closing(sqlite3.connect(p.database_path)) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]==4
        assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
        assert db.execute('SELECT * FROM audit_events ORDER BY event_id').fetchall()[:-1]==old_audit
        event=json.loads(db.execute('SELECT details_json FROM audit_events ORDER BY event_id DESC LIMIT 1').fetchone()[0])
        assert event=={'from_version':3,'to_version':4,'backup':backups[0].name}
    create_wos_checkpoint(p,q.query_id,retention_authorized=True)


def test_partial_v4_ddl_failure_rolls_back_and_retry_uses_preserved_v3(tmp_path,monkeypatch):
    p,q=v3_project(tmp_path)
    def broken(db):
        db.execute(V4_STATEMENTS[0])
        raise RuntimeError('injected migration failure')
    with monkeypatch.context() as m:
        m.setattr(projects,'apply_v4_schema',broken)
        with pytest.raises(projects.ProjectMigrationError,match='snapshot preserved'):projects.open_project(p.root)
    with closing(sqlite3.connect(p.database_path)) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]==3
        assert db.execute("SELECT name FROM sqlite_master WHERE name='wos_checkpoint_jobs'").fetchone() is None
        assert db.execute('SELECT exact_query FROM source_queries WHERE query_id=?',(q.query_id,)).fetchone()[0]=='TS=("ECMO")'
    assert projects.open_project(p.root).identifier==p.identifier


def test_failed_v4_backup_blocks_all_new_tables(tmp_path,monkeypatch):
    p,_=v3_project(tmp_path)
    def fail(*args,**kwargs):raise projects.ProjectMigrationError('backup unavailable')
    monkeypatch.setattr(projects,'_snapshot_before_upgrade',fail)
    with pytest.raises(projects.ProjectMigrationError,match='backup unavailable'):projects.open_project(p.root)
    with closing(sqlite3.connect(p.database_path)) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]==3
        assert db.execute("SELECT name FROM sqlite_master WHERE name='wos_checkpoint_jobs'").fetchone() is None


def test_mismatched_project_identity_cannot_start_v4_migration(tmp_path):
    p,_=v3_project(tmp_path)
    with closing(sqlite3.connect(p.database_path)) as db,db:
        db.execute("UPDATE project_metadata SET project_uuid='wrong'")
    with pytest.raises(projects.ProjectFormatError,match='identity'):projects.open_project(p.root)
    assert list((p.root/'backups').iterdir())==[]
