from contextlib import closing
from hashlib import sha256
import json
import sqlite3
from uuid import uuid4
from zipfile import ZipFile

import pytest

from research_y import project_archive as transfer
from research_y.projects import create_project, read_research_setup, update_research_setup
from research_y.run_execution_board import read_run_execution_board
from test_reviewed_master import populated, decide


def table_data(project):
    with closing(sqlite3.connect(project.database_path)) as db:
        tables = db.execute("SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name").fetchall()
        return {name:db.execute(f'SELECT * FROM "{name}" ORDER BY rowid').fetchall() for name, in tables}


def test_reviewed_project_archive_restores_all_tables_and_selected_files(tmp_path):
    project, run, _, ids = populated(tmp_path)
    decide(project,ids["111"],ids["WOS:000000001"],"confirmed_match")
    decide(project,ids["111"],ids["222"],"rejected_match")
    attachment = "documents/Reports/Résumé [1].pdf"
    (project.root/attachment).parent.mkdir()
    (project.root/attachment).write_bytes(b"original synthetic supporting material")
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute("INSERT INTO documents(document_id,relative_path,provenance_json) VALUES(?,?,?)",
                   (str(uuid4()),attachment,'{"source":"researcher"}'))
    export = "exports/Reviewed.xlsx"
    (project.root/export).write_bytes(b"synthetic export bytes")
    (project.root/"logs"/"local.txt").write_text("machine-local diagnostic")
    baseline = table_data(project)
    path = tmp_path/"Transfer.researchy"
    with pytest.raises(transfer.ArchiveError):
        transfer.export_archive(project,path)
    with pytest.raises(transfer.ArchiveError,match="linked"):
        transfer.export_archive(project,path,transfer_confirmed=True)
    assert not path.exists()
    result = transfer.export_archive(project,path,supporting_files=[attachment,export],transfer_confirmed=True)
    assert result["files"]==4
    with ZipFile(path) as bundle:
        assert set(bundle.namelist()) == {transfer.INDEX,transfer.DATABASE,transfer.MANIFEST_FILENAME,attachment,export}
    moved = tmp_path/"Transfer destination"
    moved.mkdir()
    restored = transfer.import_archive(path,moved)
    assert restored.identifier==project.identifier and table_data(restored)==baseline
    assert (restored.root/attachment).read_bytes()==(project.root/attachment).read_bytes()
    assert (restored.root/export).read_bytes()==(project.root/export).read_bytes()
    assert list((restored.root/"logs").iterdir())==[]
    assert read_run_execution_board(restored,run)["reconciled_primary_run_unique_publications"]==2
    with pytest.raises(FileExistsError):
        transfer.import_archive(path,moved)
    with pytest.raises(FileExistsError):
        transfer.export_archive(project,path,transfer_confirmed=True)
    assert table_data(restored)==baseline


def test_wal_snapshot_preserves_committed_state_and_excludes_uncommitted_edit(tmp_path):
    project = create_project(tmp_path,"Concurrent research")
    update_research_setup(project,theme="Committed")
    path = tmp_path/"Concurrent.researchy"
    with closing(sqlite3.connect(project.database_path)) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("UPDATE project_metadata SET theme='In progress'")
        transfer.export_archive(project,path,transfer_confirmed=True)
        writer.rollback()
    restored = transfer.import_archive(path,tmp_path,directory_name="Second")
    assert read_research_setup(restored).theme=="Committed"


@pytest.mark.parametrize("change",["version","checksum","size","missing","unknown","different_identity"])
def test_invalid_inventory_does_not_publish_a_project(tmp_path,change):
    project = create_project(tmp_path,"Source")
    good = tmp_path/"Original.researchy"
    transfer.export_archive(project,good,transfer_confirmed=True)
    with ZipFile(good) as bundle:
        members = {n:bundle.read(n) for n in bundle.namelist()}
    index = json.loads(members.pop(transfer.INDEX))
    if change=="version":
        index["version"] = 17
    elif change=="checksum":
        index["files"][transfer.DATABASE]["sha256"] = sha256(b"other").hexdigest()
    elif change=="size":
        index["files"][transfer.DATABASE]["size"] += 1
    elif change=="missing":
        del members[transfer.MANIFEST_FILENAME]
    elif change=="unknown":
        members["unlisted.txt"] = b"extra"
    else:
        index["project_id"] = str(uuid4())
    bad = tmp_path/"Changed.researchy"
    with ZipFile(bad,"x") as output:
        for name,data in members.items():
            output.writestr(name,data)
        output.writestr(transfer.INDEX,json.dumps(index))
    with pytest.raises(ValueError):
        transfer.import_archive(bad,tmp_path,directory_name="Restored")
    assert not (tmp_path/"Restored").exists()


def test_portable_name_validation_and_collisions():
    with pytest.raises(transfer.ArchiveError):
        transfer._component("..")
    for names in (["documents/Study.pdf","documents/STUDY.pdf"],
                  ["documents/Note","documents/Note/file.txt"],["logs/local.txt"]):
        with pytest.raises(transfer.ArchiveError):
            transfer._check_names(names)


def test_windows_host_actions_restore_project_after_close(tmp_path):
    from research_y.desktop.flow import RealProjectFlow
    project = create_project(tmp_path,"Desktop archive")
    update_research_setup(project,theme="Recorded theme",objectives="Recorded objectives")
    with closing(RealProjectFlow()) as flow:
        flow.open_native_folder(project.root)
        state = flow.export_native_archive(tmp_path,basename="Reviewed",supporting_files=[],transfer_confirmed=True)
        assert state["archive_receipt"]["filename"] == "Reviewed.researchy"
    with closing(RealProjectFlow()) as flow:
        state = flow.import_native_archive(tmp_path/"Reviewed.researchy",tmp_path,directory_name="Restored")
        assert state["project"]["project_id"] == str(project.identifier)
        assert flow.project.root == tmp_path/"Restored"
        assert read_research_setup(flow.project).objectives == "Recorded objectives"


def test_interrupted_restore_can_be_retried_without_partial_publication(tmp_path,monkeypatch):
    project = create_project(tmp_path,"Original")
    path = tmp_path/"Saved.researchy"
    transfer.export_archive(project,path,transfer_confirmed=True)
    with monkeypatch.context() as patch:
        def interrupt(*args):
            raise OSError("Simulated interruption before publication")
        patch.setattr(transfer,"_publish_folder",interrupt)
        with pytest.raises(OSError):
            transfer.import_archive(path,tmp_path,directory_name="Destination")
    assert not (tmp_path/"Destination").exists()
    assert transfer.import_archive(path,tmp_path,directory_name="Destination").identifier == project.identifier
