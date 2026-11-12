"""Negative export/recovery tests for the isolated real-project host adapter.

The disk-backed research fixtures remain incomplete. These tests do not claim
source retrieval, production graphical acceptance, or licensed-data coverage.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import inspect
import sqlite3

import pytest

from research_y.projects import create_project
from research_y.storage import ApprovedTerm, StrategyGroup, approve_strategy, create_search_run, plan_source_query
from tools.gui_feasibility.real_project_flow import ProjectFlowError, RealProjectFlow
from tools.gui_feasibility.real_project_app import run


def sample(tmp_path):
    project = create_project(tmp_path, 'Failure-recovery fixture')
    strategy = approve_strategy(project, theme='Right ventricular failure',
        approved_by='Fixture', approval_confirmed=True,
        groups=(StrategyGroup('rv', 'Right heart',
            (ApprovedTerm('right ventricle', 'researcher', True),)),))
    run_record = create_search_run(project, strategy.strategy_version_id)
    plan_source_query(project, run_id=run_record.run_id, group_id='rv',
        source_name='pubmed', exact_query='"right ventricle"[All Fields]')
    return project, run_record.run_id


def count_receipts(project):
    with closing(sqlite3.connect(project.database_path)) as db:
        return db.execute("SELECT COUNT(*) FROM audit_events "
            "WHERE event_type LIKE 'workbook_export_v1:%'").fetchone()[0]


def open_flow(project, run_id, parent):
    flow = RealProjectFlow(selected_root=project.root, selected_parent=parent)
    flow.open_selected()
    flow.select_run(run_id)
    return flow


def test_prepare_conflict_has_no_ghost_identity_and_never_overwrites(tmp_path):
    project, run_id = sample(tmp_path)
    output = project.root / 'exports' / ('strategy-summary-' + run_id + '.xlsx')
    output.write_bytes(b'Unrelated existing file; never overwrite')
    flow = open_flow(project, run_id, tmp_path)
    try:
        with pytest.raises(ProjectFlowError, match='^destination_conflict$'):
            flow.prepare()
        state = flow.state()
        assert state['selected_export_id'] is None
        assert state['export_reconciliation_required'] is False
        assert not state['exports'] and state['observation'] is None
        assert count_receipts(project) == 0
        assert output.read_bytes() == b'Unrelated existing file; never overwrite'
        output.unlink()
        prepared = flow.prepare()
        assert prepared['selected_export_id']
        assert not prepared['export_reconciliation_required']
        assert len(prepared['exports']) == 1 and count_receipts(project) == 1
        assert prepared['exports'][0]['recorded_state'] == 'prepared'
    finally:
        flow.close()


def test_lost_prepare_reply_reconciles_committed_original_uuid(tmp_path, monkeypatch):
    project, run_id = sample(tmp_path)
    flow = open_flow(project, run_id, tmp_path)
    original = flow._operation
    interrupted = {'done': False, 'export_id': None}

    def lose_reply(operation, **kwargs):
        result = original(operation, **kwargs)
        if operation == 'prepare_export' and not interrupted['done']:
            interrupted['done'] = True
            interrupted['export_id'] = kwargs['export_id']
            raise ProjectFlowError('worker_interrupted')
        return result

    monkeypatch.setattr(flow, '_operation', lose_reply)
    try:
        with pytest.raises(ProjectFlowError, match='^worker_interrupted$'):
            flow.prepare()
        state = flow.state()
        assert state['selected_export_id'] == interrupted['export_id']
        assert not state['export_reconciliation_required']
        assert state['exports'][0]['recorded_state'] == 'prepared'
        before = count_receipts(project)
        retry = flow.prepare()
        assert retry['selected_export_id'] == interrupted['export_id']
        assert count_receipts(project) == before
        flow.resume()
        assert flow.observe()['observation']['audited_success'] is True
    finally:
        flow.close()


def test_uninspectable_prepare_keeps_private_retry_identity(tmp_path, monkeypatch):
    project, run_id = sample(tmp_path)
    flow = open_flow(project, run_id, tmp_path)
    original = flow._operation
    attempted = []

    def interrupted(operation, **kwargs):
        if operation == 'prepare_export':
            attempted.append(kwargs['export_id'])
            raise ProjectFlowError('worker_interrupted')
        if operation == 'inspect':
            raise ProjectFlowError('worker_interrupted')
        return original(operation, **kwargs)

    monkeypatch.setattr(flow, '_operation', interrupted)
    try:
        with pytest.raises(ProjectFlowError, match='^worker_interrupted$'):
            flow.prepare()
        assert flow.state()['selected_export_id'] is None
        assert flow.state()['export_reconciliation_required'] is True
        assert not flow.state()['exports'] and count_receipts(project) == 0
        with pytest.raises(ProjectFlowError, match='^export_reconciliation_required$'):
            flow.select_run(run_id)
        monkeypatch.setattr(flow, '_operation', original)
        prepared = flow.prepare()
        assert prepared['selected_export_id'] == attempted[0]
        assert prepared['export_reconciliation_required'] is False
        assert count_receipts(project) == 1
    finally:
        flow.close()


def test_verified_file_change_and_missing_file_revoke_visible_success(tmp_path):
    project, run_id = sample(tmp_path)
    flow = open_flow(project, run_id, tmp_path)
    try:
        export_id = flow.prepare()['selected_export_id']
        flow.resume()
        assert flow.observe()['observation']['outcome'] == 'published_verified'
        filename = project.root / 'exports' / ('strategy-summary-' + run_id + '.xlsx')
        filename.write_bytes(b'changed independently after verification')
        with pytest.raises(ProjectFlowError, match='^artifact_changed$'):
            flow.resume()
        state = flow.state()
        assert state['observation'] is None
        assert state['selected_export_id'] == export_id
        assert state['exports'][0]['last_error'] == 'artifact_changed'
        assert state['source_retrieval_verified'] is False
        result = flow.observe()['observation']
        assert result['outcome'] == 'destination_changed' and not result['audited_success']
        filename.unlink()
        missing = flow.observe()['observation']
        assert missing['outcome'] == 'published_file_missing'
        assert not missing['audited_success']
        assert flow.state()['selected_export_id'] == export_id
    finally:
        flow.close()


def test_cancelled_request_is_audited_without_deleting_or_recreating(tmp_path):
    project, run_id = sample(tmp_path)
    flow = open_flow(project, run_id, tmp_path)
    try:
        export_id = flow.prepare()['selected_export_id']
        cancelled = flow.cancel()
        assert cancelled['selected_export_id'] == export_id
        assert cancelled['exports'][0]['recorded_state'] == 'cancelled'
        assert cancelled['observation'] is None
        journal = count_receipts(project)
        assert journal == 2
        with pytest.raises(ProjectFlowError, match='^cancelled$'):
            flow.resume()
        assert flow.state()['observation'] is None
        observed = flow.observe()['observation']
        assert observed['outcome'] == 'recorded_cancelled'
        assert observed['audited_success'] is False
        assert not (project.root / 'exports' /
            ('strategy-summary-' + run_id + '.xlsx')).exists()
    finally:
        flow.close()
    reopened = open_flow(project, run_id, tmp_path)
    try:
        selected = reopened.select_export(export_id)
        assert selected['selected_export_id'] == export_id
        assert selected['retained_export_report'] is not None
        assert reopened.observe()['observation']['outcome'] == 'recorded_cancelled'
        assert count_receipts(project) >= journal
        assert len(reopened.state()['exports']) == 1
    finally:
        reopened.close()


def test_two_concurrent_preparations_retain_one_export_request(tmp_path):
    project, run_id = sample(tmp_path)
    flow = open_flow(project, run_id, tmp_path)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = pool.map(lambda _: flow.prepare(), range(2))
            assert first['selected_export_id'] == second['selected_export_id']
            assert len(second['exports']) == 1
            assert count_receipts(project) == 1
    finally:
        flow.close()


def test_failure_controls_have_no_browser_supplied_path_or_export_identity():
    from desktop_source import project_ui_source
    code = project_ui_source()
    assert "if name == 'cancel':" in code
    assert "return flow.cancel()" in code
    assert "data-testid=export-phase" in code
    assert "data-testid=recovery-required" in code
    assert "data-testid=export-error" in code
    assert "data-testid=cancel" in code
    assert "'recorded_state'] not in ('cancelled', 'published')" in code
    assert 'source_retrieval_verified' not in inspect.signature(RealProjectFlow.cancel).parameters
    assert 'directory' not in inspect.signature(RealProjectFlow.cancel).parameters
