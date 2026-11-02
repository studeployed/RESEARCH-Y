"""Real process-death and unreceipted-workbook GUI acceptance.

The subprocess terminates after a valid workbook is linked but before the
publication receipt commits. All records and terminology are synthetic.
"""
from contextlib import closing
from hashlib import sha256
import inspect
import sqlite3

import pytest

from research_y import workbook_exports as exports
from research_y.application_inspection import observe_export_request, read_export_report
from research_y.projects import open_project
from tools.gui_feasibility.real_project_flow import RealProjectFlow, ProjectFlowError
from tools.gui_feasibility.run_real_project import (
    fixture, seed_unreceipted_workbook, transport_steps, run_app,
)
from tools.gui_feasibility.real_project_app import run


def audit_events(project, export_id):
    with closing(sqlite3.connect(project.database_path)) as db:
        return db.execute('SELECT COUNT(*) FROM audit_events WHERE event_type=?',
                          (f'{exports.EVENT}:{export_id}',)).fetchone()[0]


def open_selected(project, run_id, parent):
    flow = RealProjectFlow(selected_root=project.root, selected_parent=parent)
    opened = flow.open_selected()
    assert opened['selected_run_id'] is None
    flow.select_run(run_id)
    return flow


def test_real_crash_linked_file_unreceipted_until_gui_resume(tmp_path):
    project, run_id = fixture(tmp_path)
    export_id, workbook = seed_unreceipted_workbook(project, run_id)
    original_bytes = workbook.read_bytes()
    assert audit_events(project, export_id) == 4
    initial = observe_export_request(project, export_id)
    assert initial.outcome == 'published_receipt_missing'
    assert initial.request.recorded_state == 'publishing'
    assert initial.audited_success is False
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute('UPDATE source_queries SET reported_matches=21,status="failed" '
                   'WHERE run_id=?', (run_id,))
    flow = open_selected(project, run_id, tmp_path)
    try:
        current = flow.state()['report']
        assert current['queries'][0]['reported_matches'] == 21
        selected = flow.select_export(export_id)
        assert selected['retained_export_report']['queries'][0]['reported_matches'] is None
        observed = flow.observe()
        assert observed['observation']['outcome'] == 'published_receipt_missing'
        assert observed['observation']['audited_success'] is False
        assert observed['exports'][0]['recorded_state'] == 'publishing'
        assert observed['source_retrieval_verified'] is False
        assert audit_events(project, export_id) == 4
        assert workbook.read_bytes() == original_bytes
    finally:
        flow.close()

    reopened = open_project(project.root)
    retry = RealProjectFlow(selected_root=reopened.root, selected_parent=tmp_path)
    try:
        retry.open_selected()
        retry.select_run(run_id)
        retry.select_export(export_id)
        resumed = retry.resume()
        assert resumed['observation'] is None
        assert resumed['selected_export_id'] == export_id
        assert resumed['exports'][0]['recorded_state'] == 'published'
        result = retry.observe()
        assert result['observation']['outcome'] == 'published_verified'
        assert result['observation']['audited_success'] is True
        assert result['source_retrieval_verified'] is False
        assert len(result['exports']) == 1
        assert audit_events(reopened, export_id) == 5
        assert sha256(workbook.read_bytes()).hexdigest() == sha256(original_bytes).hexdigest()
        # The original report remains immutable despite the changed source counts.
        assert read_export_report(reopened, export_id).as_dict()['queries'][0]['reported_matches'] is None
        retry.resume()
        assert audit_events(reopened, export_id) == 5
    finally:
        retry.close()


def test_unreceipted_file_tampering_cannot_be_reconciled_or_overwritten(tmp_path):
    project, run_id = fixture(tmp_path)
    export_id, workbook = seed_unreceipted_workbook(project, run_id)
    workbook.write_bytes(b'externally modified after process death')
    original_modified = workbook.read_bytes()
    flow = open_selected(project, run_id, tmp_path)
    try:
        flow.select_export(export_id)
        observed = flow.observe()
        assert observed['observation']['outcome'] == 'destination_changed'
        assert observed['observation']['audited_success'] is False
        with pytest.raises(ProjectFlowError, match='^artifact_changed$'):
            flow.resume()
        state = flow.state()
        assert state['observation'] is None
        assert state['selected_export_id'] == export_id
        assert state['exports'][0]['recorded_state'] == 'publishing'
        assert state['exports'][0]['last_error'] == 'artifact_changed'
        assert state['source_retrieval_verified'] is False
        assert workbook.read_bytes() == original_modified
        assert audit_events(project, export_id) == 5  # failure receipt only, no success
    finally:
        flow.close()


def test_recovery_notice_and_real_transport_native_sequences_not_fake_success():
    source = inspect.getsource(run)
    driver = inspect.getsource(transport_steps)
    host = inspect.getsource(run_app)
    assert "if observed['outcome'] == 'published_receipt_missing':" in source
    assert 'data-testid=receipt-missing' in source
    assert 'RECOVERY REQUIRED' in source and 'This is not verified.' in source
    assert "args.scenario == 'receipt_missing'" in source
    assert 'receipt: Boolean(document.querySelector' in source
    assert "'receipt_recovered'" in source and "'receipt_missing'" in source
    assert "'published_receipt_missing' if scenario == 'receipt_missing'" in driver
    assert 'expected_outcome == \'published_verified\'' in host
    assert 'RESEARCHY_GUI_EXPECTED_EXPORT_ID=expected_export' in host
    assert 'directory' not in inspect.signature(RealProjectFlow.resume).parameters
