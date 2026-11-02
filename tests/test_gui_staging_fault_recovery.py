"""Deterministic interrupted render/stage recovery on genuine local projects.

The injected permission and ENOSPC exceptions occur only in disposable
subprocess fixtures; they do not imply genuine host disk exhaustion or ACL
modification. No external biomedical provider is contacted.
"""
from contextlib import closing
from hashlib import sha256
import inspect
import sqlite3
from zipfile import ZipFile

from research_y import workbook_exports
from research_y.application_inspection import (
    observe_export_request, read_application_snapshot, read_export_report,
)
from research_y.projects import open_project
from tools.gui_feasibility.real_project_app import run
from tools.gui_feasibility.real_project_flow import RealProjectFlow
from tools.gui_feasibility.run_real_project import (
    fixture, run_app, seed_failed_export, transport_steps,
)


def events(project, export_id):
    with closing(sqlite3.connect(project.database_path)) as db:
        return db.execute("SELECT COUNT(*) FROM audit_events WHERE event_type=?",
                          (f"{workbook_exports.EVENT}:{export_id}",)).fetchone()[0]


def selected(project, parent, run_id, export_id):
    flow = RealProjectFlow(selected_root=project.root, selected_parent=parent)
    assert flow.open_selected()['selected_run_id'] is None
    flow.select_run(run_id)
    flow.select_export(export_id)
    return flow


def test_permission_renderer_failure_retries_original_frozen_report(tmp_path):
    project, run_id = fixture(tmp_path)
    export_id, partial = seed_failed_export(project, run_id, "render")
    assert partial is None and events(project, export_id) == 2
    snapshot = read_application_snapshot(project, selected_run_id=run_id).as_dict()
    assert snapshot["exports"][0]["recorded_state"] == "prepared"
    assert snapshot["exports"][0]["last_error"] == "render_failed"
    assert snapshot["source_retrieval_verified"] is False
    assert not (project.root / "exports" / ("strategy-summary-" + run_id + ".xlsx")).exists()

    # The original captured report must never be replaced with later source data.
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute("UPDATE source_queries SET reported_matches=19,status='failed' WHERE run_id=?",
                   (run_id,))
    flow = selected(project, tmp_path, run_id, export_id)
    try:
        state = flow.state()
        assert state["report"]["queries"][0]["reported_matches"] == 19
        assert state["retained_export_report"]["queries"][0]["reported_matches"] is None
        negative = flow.observe()
        assert negative["observation"]["outcome"] == "not_yet_staged"
        assert negative["observation"]["audited_success"] is False
        assert negative["source_retrieval_verified"] is False
        assert events(project, export_id) == 2
    finally:
        flow.close()

    reopened = open_project(project.root)
    recovery = selected(reopened, tmp_path, run_id, export_id)
    try:
        published = recovery.resume()
        assert published["selected_export_id"] == export_id
        assert published["observation"] is None
        assert published["exports"][0]["recorded_state"] == "published"
        assert published["exports"][0]["last_error"] is None
        verified = recovery.observe()
        assert verified["observation"]["outcome"] == "published_verified"
        assert verified["observation"]["audited_success"]
        assert verified["source_retrieval_verified"] is False
        assert events(reopened, export_id) == 6
        assert read_export_report(reopened, export_id).as_dict()["queries"][0]["reported_matches"] is None
        recovery.resume()
        assert events(reopened, export_id) == 6
    finally:
        recovery.close()


def test_injected_disk_full_keeps_partial_stage_and_recovers_without_overwrite(tmp_path):
    project, run_id = fixture(tmp_path)
    export_id, partial = seed_failed_export(project, run_id, "stage")
    assert partial is not None and partial.is_file()
    assert partial.read_bytes() == b"PARTIAL-OWNED-STAGE"
    original_inode = (partial.stat().st_dev, partial.stat().st_ino)
    assert events(project, export_id) == 3

    flow = selected(project, tmp_path, run_id, export_id)
    try:
        before = flow.state()
        assert before["exports"][0]["recorded_state"] == "staging"
        assert before["exports"][0]["last_error"] == "storage_failed"
        bad = flow.observe()
        assert bad["observation"]["outcome"] == "retained_artifact_changed"
        assert bad["observation"]["audited_success"] is False
        assert events(project, export_id) == 3
    finally:
        flow.close()

    recovery = selected(open_project(project.root), tmp_path, run_id, export_id)
    try:
        resumed = recovery.resume()
        assert resumed["selected_export_id"] == export_id
        assert resumed["exports"][0]["recorded_state"] == "published"
        assert resumed["exports"][0]["last_error"] is None
        result = recovery.observe()
        assert result["observation"]["outcome"] == "published_verified"
        assert result["observation"]["audited_success"]
        assert not result["source_retrieval_verified"]
        assert events(project, export_id) == 7
    finally:
        recovery.close()

    # Bad evidence is preserved rather than edited or cleaned up destructively.
    assert partial.is_file() and partial.read_bytes() == b"PARTIAL-OWNED-STAGE"
    assert (partial.stat().st_dev, partial.stat().st_ino) == original_inode
    workbook = project.root / "exports" / ("strategy-summary-" + run_id + ".xlsx")
    with ZipFile(workbook) as z:
        assert z.testzip() is None and "xl/workbook.xml" in z.namelist()
    assert sha256(workbook.read_bytes()).hexdigest() == (
        observe_export_request(project, export_id).request.artifact_sha256)
    assert len(read_application_snapshot(project, selected_run_id=run_id).as_dict()["exports"]) == 1


def test_fault_scenarios_keep_error_and_recovery_actions_inside_trusted_host():
    app = inspect.getsource(run)
    steps = inspect.getsource(transport_steps)
    runner = inspect.getsource(run_app)
    assert "data-testid=stage-recovery" in app
    assert "observed['outcome'] in ('not_yet_staged', 'retained_artifact_changed')" in app
    assert "args.scenario == 'render_fault'" in app
    assert "args.scenario == 'stage_fault'" in app
    assert "'render_failed' not in data['error']" in app
    assert "'storage_failed' not in data['error']" in app
    assert "'not_yet_staged' if scenario == 'render_fault'" in steps
    assert "'retained_artifact_changed' if scenario == 'stage_fault'" in steps
    assert "expected_outcome == 'published_verified'" in runner
    assert 'directory' not in inspect.signature(RealProjectFlow.resume).parameters
    assert 'kind' not in inspect.signature(RealProjectFlow.resume).parameters
