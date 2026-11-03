"""Disk-backed Research Setup: explicit approval, safe draft and real worker.

No provider requests or model inference. All counts remain unknown; verified
workbook publication does not falsely turn research retrieval into completion.
"""
from contextlib import closing
from pathlib import Path
import inspect
import sqlite3

import pytest

from research_y.projects import create_project, open_project
from research_y.storage import get_strategy_snapshot, list_run_queries
from research_y.query_compiler import compile_both
from tools.gui_feasibility.strategy_setup import StrategyDraft, DraftError
from tools.gui_feasibility.real_project_flow import RealProjectFlow, ProjectFlowError
from tools.gui_feasibility.real_project_app import run


def _flow(tmp_path, title='Study'):
    project = create_project(tmp_path, title)
    flow = RealProjectFlow(selected_root=project.root, selected_parent=tmp_path)
    flow.open_selected()
    return project, flow


def _seed(flow):
    flow.edit_setup('heading', {'theme': 'RV and ECMO', 'approved_by': 'Researcher'})
    flow.edit_setup('add_group', {'label': 'Right heart'})
    group_a = flow.state()['strategy_draft']['groups'][0]['group_id']
    flow.edit_setup('add_term', {'group_id': group_a, 'text': 'right ventricle'})
    flow.edit_setup('add_term', {'group_id': group_a, 'text': 'right-ventricle',
                                 'origin': 'deterministic',
                                 'rationale': 'Hyphenation alternative'})
    flow.edit_setup('add_group', {'label': 'Extracorporeal life support'})
    group_b = flow.state()['strategy_draft']['groups'][1]['group_id']
    flow.edit_setup('add_term', {'group_id': group_b, 'text': 'ECMO'})
    return group_a, group_b


def _counts(project):
    with closing(sqlite3.connect(project.database_path)) as db:
        return tuple(db.execute('SELECT COUNT(*) FROM ' + name).fetchone()[0]
                     for name in ('strategy_versions','search_runs',
                                  'source_queries','audit_events'))


def test_real_worker_strategy_approval_to_explicit_run_selection_and_workbook(tmp_path):
    project, flow = _flow(tmp_path)
    try:
        group_a, group_b = _seed(flow)
        before = _counts(project)
        state = flow.preview_setup()
        preview = state['strategy_draft']['preview']
        assert preview['logic'] == 'OR' and preview['active_term_count'] == 3
        assert preview['group_count'] == 2
        assert preview['provider_execution'] == 'not_performed'
        assert preview['provider_counts'] == 'unknown'
        assert len(preview['sources']) == 2
        for source in preview['sources']:
            assert source['name'] in ('pubmed', 'wos')
            assert len(source['groups']) == 2
            assert all(g['execution_status']=='not_executed' and
                       g['reported_matches'] is None for g in source['groups'])
            assert ' OR ' in source['groups'][0]['exact_query']
            assert ' AND ' not in source['union_query']
        assert '[All Fields]' in preview['sources'][0]['union_query']
        assert 'TS=(' in preview['sources'][1]['union_query']
        assert 'full text' in preview['sources'][1]['coverage'].lower() or (
            'narrower' in preview['sources'][1]['coverage'].lower())
        assert _counts(project) == before

        accepted = flow.approve_setup()
        assert accepted['strategy_reconciliation_required'] is False
        assert accepted['strategy_draft']['preview'] is None
        assert accepted['selected_run_id'] is None
        assert accepted['source_retrieval_verified'] is False
        assert len(accepted['runs']) == 1
        receipt = accepted['last_strategy_admission']
        assert receipt['version_number'] == 1 and receipt['query_count'] == 4
        assert _counts(project) == tuple(a+b for a,b in zip(before,(1,1,4,6)))
        approved = get_strategy_snapshot(open_project(project.root),
                                         receipt['strategy_version_id'])
        assert approved['logic'] == 'OR'
        assert [g['group_id'] for g in approved['groups']] == [group_a, group_b]
        assert all(t['approved'] is True for g in approved['groups'] for t in g['terms'])
        compiled = compile_both(approved)
        rows = list_run_queries(project, receipt['run_id'])
        assert len(rows)==4 and all(row.status=='pending' and
                                    row.reported_matches is None for row in rows)
        assert {(row.source_name,row.group_id,row.exact_query) for row in rows} == {
            (source.source_name,g.group_id,g.exact_group_query)
            for source in compiled for g in source.groups}
        selected = flow.select_run(receipt['run_id'])
        assert selected['selected_run_id'] == receipt['run_id']
        assert selected['report']['status'] == 'incomplete'
        prepared = flow.prepare()
        assert prepared['selected_export_id']
        flow.resume()
        verified = flow.observe()
        assert verified['observation']['audited_success'] is True
        assert verified['source_retrieval_verified'] is False
        assert (project.root / 'exports' /
                ('strategy-summary-' + receipt['run_id'] + '.xlsx')).is_file()
    finally:
        flow.close()


def test_edit_after_preview_revokes_approval_and_changes_compiled_queries(tmp_path):
    p, flow = _flow(tmp_path)
    try:
        group, _ = _seed(flow)
        assert flow.preview_setup()['strategy_draft']['preview'] is not None
        term_id = flow.state()['strategy_draft']['groups'][0]['terms'][0]['term_id']
        flow.edit_setup('edit_term', dict(group_id=group, term_id=term_id,
                    text='RV dysfunction', origin='researcher',
                    rationale='', enabled=True))
        assert flow.state()['strategy_draft']['preview'] is None
        with pytest.raises(ProjectFlowError, match='^strategy_preview_required$'):
            flow.approve_setup()
        flow.preview_setup()
        result = flow.approve_setup()['last_strategy_admission']
        source_rows = list_run_queries(p, result['run_id'])
        assert 'RV dysfunction' in ''.join(r.exact_query for r in source_rows)
        assert 'right ventricle' not in ''.join(r.exact_query for r in source_rows)
    finally:
        flow.close()


def test_disabled_reordered_and_removed_terms_never_enter_approved_queries(tmp_path):
    p, flow = _flow(tmp_path)
    try:
        first, second = _seed(flow)
        terms = flow.state()['strategy_draft']['groups'][0]['terms']
        flow.edit_setup('edit_term', dict(group_id=first, term_id=terms[1]['term_id'],
                         text=terms[1]['text'], origin='deterministic',
                         rationale='Hyphenation alternative', enabled=False))
        flow.edit_setup('move_group', {'group_id': second, 'direction': -1})
        flow.edit_setup('add_term', {'group_id': second, 'text': 'venovenous'})
        extra_id = flow.state()['strategy_draft']['groups'][0]['terms'][-1]['term_id']
        flow.edit_setup('remove_term', {'group_id': second, 'term_id': extra_id})
        assert [g['group_id'] for g in flow.state()['strategy_draft']['groups']] == [
            second, first]
        flow.preview_setup()
        admitted = flow.approve_setup()['last_strategy_admission']
        saved = get_strategy_snapshot(p, admitted['strategy_version_id'])
        assert saved['groups'][0]['group_id'] == second
        assert saved['groups'][1]['terms'][1]['enabled'] is False
        plans = ''.join(q.exact_query for q in list_run_queries(p, admitted['run_id']))
        assert 'right-ventricle' not in plans and 'venovenous' not in plans
        assert 'right ventricle' in plans
    finally:
        flow.close()


def test_invalid_draft_and_forged_group_ids_never_write_a_strategy(tmp_path):
    project, flow = _flow(tmp_path)
    try:
        before = _counts(project)
        with pytest.raises(ProjectFlowError, match='strategy_preview_required'):
            flow.approve_setup()
        with pytest.raises(ProjectFlowError, match='strategy_preview_invalid'):
            flow.preview_setup()
        with pytest.raises(ProjectFlowError, match='invalid_setup_input'):
            flow.edit_setup('add_term', {'group_id': 'arbitrary-id', 'text':'text'})
        with pytest.raises(ProjectFlowError, match='invalid_setup_action'):
            flow.edit_setup('__getattribute__', {'name': '_worker'})
        with pytest.raises(ProjectFlowError, match='invalid_setup_input'):
            flow.edit_setup('add_group', {'label':'\x00bad'})
        assert _counts(project)==before
        _seed(flow)
        groups = flow.state()['strategy_draft']['groups']
        before_draft = flow.state()['strategy_draft']
        with pytest.raises(ProjectFlowError, match='invalid_setup_input'):
            flow.edit_setup('heading', {'theme':'will not partially save',
                                         'approved_by':'\x00invalid'})
        assert flow.state()['strategy_draft']==before_draft
        # An unreviewed quote is allowed as draft text, but the existing
        # provider compiler must reject it before any approved mutation.
        flow.edit_setup('add_term', {'group_id':groups[0]['group_id'],
                                     'text':'bad "phrase"'})
        with pytest.raises(ProjectFlowError, match='strategy_preview_invalid'):
            flow.preview_setup()
        assert _counts(project)==before
    finally:
        flow.close()


def test_lost_worker_approval_response_reuses_same_request_and_no_double_version(tmp_path, monkeypatch):
    project, flow = _flow(tmp_path)
    try:
        _seed(flow); flow.preview_setup()
        execute = flow._operation
        request_ids = []
        first = True

        def reply_lost(name, **kwargs):
            nonlocal first
            answer = execute(name, **kwargs)
            if name == 'admit_strategy':
                request_ids.append(kwargs['admission_request_id'])
                if first:
                    first = False
                    raise ProjectFlowError('worker_interrupted')
            return answer

        monkeypatch.setattr(flow, '_operation', reply_lost)
        with pytest.raises(ProjectFlowError, match='worker_interrupted'):
            flow.approve_setup()
        assert flow.state()['strategy_reconciliation_required'] is True
        before = _counts(project)
        with pytest.raises(ProjectFlowError, match='strategy_reconciliation_required'):
            flow.edit_setup('add_group', {'label':'Unsafe retarget'})
        with pytest.raises(ProjectFlowError, match='strategy_reconciliation_required'):
            flow.open_selected()
        accepted = flow.approve_setup()
        assert len(request_ids)==2 and request_ids[0]==request_ids[1]
        assert _counts(project)==before
        assert accepted['strategy_reconciliation_required'] is False
        assert accepted['last_strategy_admission']['query_count']==4
        assert len(accepted['runs'])==1
    finally:
        flow.close()


def test_post_commit_inspection_failure_retains_original_approved_snapshot(tmp_path, monkeypatch):
    project, flow = _flow(tmp_path)
    try:
        _seed(flow); flow.preview_setup()
        original = flow._operation
        failed = False
        observed_ids = []

        def temporary_failure(name, **kwargs):
            nonlocal failed
            if name == 'inspect' and observed_ids and not failed:
                failed = True
                raise ProjectFlowError('worker_unavailable')
            if name == 'admit_strategy':
                observed_ids.append(kwargs['admission_request_id'])
            return original(name, **kwargs)

        monkeypatch.setattr(flow, '_operation', temporary_failure)
        with pytest.raises(ProjectFlowError, match='worker_unavailable'):
            flow.approve_setup()
        assert flow.state()['strategy_reconciliation_required'] is True
        assert len(flow.state()['runs'])==0
        before=_counts(project)
        resumed=flow.approve_setup()
        assert _counts(project)==before
        assert observed_ids[0]==observed_ids[1]
        assert len(resumed['runs'])==1
    finally:
        flow.close()


def test_host_draft_without_optional_gui_dependency_and_no_browser_file_path():
    from tools.gui_feasibility.real_project_app import run
    source = inspect.getsource(run)
    assert "name == 'setup_edit'" in source
    assert "name == 'setup_preview'" in source
    assert "name == 'setup_approve'" in source
    assert "flow.approve_setup()" in source
    assert "'data-testid=setup-approve'" in source
    assert "if draft['preview'] is None:" in source
    assert "'data-testid=setup-preview-locked'" in source
    assert "'data-testid=setup-revise'" in source
    assert "'data-testid=setup-exact-query'" in source
    assert "ui.label('Group '" in source
    assert 'ui.html(' not in source
    assert "ui.run(host='127.0.0.1'" in source
    assert '/_probe/strategy' not in source


def test_revise_preview_must_return_to_edit_mode_without_prior_approval(tmp_path):
    project, flow = _flow(tmp_path)
    try:
        _seed(flow)
        preview = flow.preview_setup()
        assert preview['strategy_draft']['preview'] is not None
        assert _counts(project)[0] == 0
        revised = flow.edit_setup('revise_preview', {})
        assert revised['strategy_draft']['preview'] is None
        with pytest.raises(ProjectFlowError, match='^strategy_preview_required$'):
            flow.approve_setup()
        assert len(flow.state()['strategy_draft']['groups']) == 2
        assert _counts(project)[0] == 0
        flow.preview_setup()
        assert flow.approve_setup()['last_strategy_admission']['query_count'] == 4
    finally:
        flow.close()


def test_approving_new_version_keeps_previous_explicit_run_and_export_view(tmp_path):
    from tools.gui_feasibility.run_real_project import fixture
    project, original_run = fixture(tmp_path)
    flow = RealProjectFlow(selected_root=project.root, selected_parent=tmp_path)
    try:
        flow.open_selected()
        flow.select_run(original_run)
        prepared = flow.prepare()
        old_export = prepared['selected_export_id']
        flow.resume()
        before = flow.observe()
        assert before['report']['run']['run_id'] == original_run
        assert before['observation']['audited_success'] is True
        original_retained = before['retained_export_report']

        _seed(flow)
        flow.preview_setup()
        approved = flow.approve_setup()
        assert len(approved['runs']) == 2
        assert approved['selected_run_id'] == original_run
        assert approved['report'] == before['report'] or (
            approved['report']['run']['run_id'] == original_run and
            approved['report']['queries'] == before['report']['queries'])
        assert approved['selected_export_id'] == old_export
        assert approved['retained_export_report'] == original_retained
        assert approved['observation'] == before['observation']
        new_id = approved['last_strategy_admission']['run_id']
        assert new_id != original_run
        assert approved['report']['run']['run_id'] != new_id
        # The newly approved run is selectable only by a further deliberate
        # action; changing run clears retained export state as before.
        chosen = flow.select_run(new_id)
        assert chosen['selected_run_id'] == new_id
        assert chosen['report']['run']['run_id'] == new_id
        assert chosen['selected_export_id'] is None
        assert chosen['retained_export_report'] is None
        assert chosen['observation'] is None
    finally:
        flow.close()
