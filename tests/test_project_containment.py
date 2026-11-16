"""Project-relative storage checks using disposable ordinary projects."""
from contextlib import closing
import os
import sqlite3

import pytest

from research_y import projects
from research_y.result_count_ledger import CountIntegrityError
from research_y.result_counts import _read_connection


def _link_directory(link, target):
    if os.name == "nt":
        from _winapi import CreateJunction
        CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


def _metadata_and_audit(project):
    with closing(sqlite3.connect(project.database_path.as_uri() + "?mode=ro", uri=True)) as db:
        return (db.execute("SELECT * FROM project_metadata").fetchall(),
                db.execute("SELECT * FROM audit_events ORDER BY event_id").fetchall())


def test_redirected_data_refused_before_sqlite_and_external_project_unchanged(tmp_path, monkeypatch):
    selected = projects.create_project(tmp_path, "Selected")
    external = projects.create_project(tmp_path, "Other")
    projects.update_research_setup(external, theme="Independent project")
    before = _metadata_and_audit(external)
    data = selected.root / "data"
    data.rename(selected.root / "ordinary-data")
    # An empty external folder is sufficient to test rejection at the directory boundary.
    _link_directory(data, external.root / "exports")
    if os.name == "nt":
        assert data.is_junction()
    with monkeypatch.context() as patch:
        patch.setattr(projects, "_sqlite_connection", lambda *_: pytest.fail("Opened SQLite"))
        for choice in (selected.root, selected.manifest_path):
            with pytest.raises(projects.ProjectFormatError, match="'data'"):
                projects.open_project(choice)
        with pytest.raises(projects.ProjectFormatError, match="'data'"):
            projects.update_research_setup(selected, theme="Declined")
        with pytest.raises(CountIntegrityError):
            with _read_connection(selected):
                pytest.fail("Opened the count database")
    assert _metadata_and_audit(external) == before
    assert list((external.root / "exports").iterdir()) == []


@pytest.mark.parametrize("suffix", ["-journal", "-wal", "-shm"])
def test_nonordinary_sidecar_rejected_before_recovery(tmp_path, monkeypatch, suffix):
    project = projects.create_project(tmp_path, "Local")
    sidecar = project.database_path.with_name(project.database_path.name + suffix)
    sidecar.mkdir()
    monkeypatch.setattr(projects, "_sqlite_connection", lambda *_: pytest.fail("Opened SQLite"))
    with pytest.raises(projects.ProjectFormatError, match="SQLite journal"):
        projects.open_project(project.root)


def test_migration_checks_backup_directory_before_writing_snapshot(tmp_path):
    project = projects.create_project(tmp_path, "Local")
    external = tmp_path / "empty"
    external.mkdir()
    backups = project.root / "backups"
    backups.rmdir()
    _link_directory(backups, external)
    with closing(sqlite3.connect(project.database_path)) as db:
        with pytest.raises(projects.ProjectFormatError, match="'backups'"):
            projects._snapshot_before_upgrade(project, db)
    assert list(external.iterdir()) == []
