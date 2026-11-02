"""Real disk-backed project/workbook acceptance for the isolated trusted GUI host.

The browser cannot pass filesystem paths, run IDs or export IDs to the host
selection methods; all choices are validated against actual stored evidence.
"""
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import inspect
import json
import shutil
import sqlite3
from uuid import uuid4
from zipfile import ZipFile

import pytest

from research_y.projects import create_project, open_project
from research_y.storage import ApprovedTerm, StrategyGroup, approve_strategy, create_search_run, plan_source_query
from research_y.application_inspection import observe_export_request
from tools.gui_feasibility.real_project_flow import ProjectFlowError, RealProjectFlow


def sample(tmp_path):
    p = create_project(tmp_path, 'Clinical <img onerror="alert(1)">')
    strategy = approve_strategy(p, theme='Right ventricular failure', approved_by='Fixture',
        approval_confirmed=True, groups=(StrategyGroup('rv', 'Right heart',
            (ApprovedTerm('right ventricle', 'researcher', True),)),))
    run = create_search_run(p, strategy.strategy_version_id)
    plan_source_query(p, run_id=run.run_id, group_id='rv', source_name='pubmed',
                      exact_query='"right ventricle"[All Fields]')
    return p, run.run_id


def journal_count(p):
    with closing(sqlite3.connect(p.database_path)) as db:
        return db.execute("SELECT COUNT(*) FROM audit_events WHERE event_type LIKE 'workbook_export_v1:%'").fetchone()[0]


def test_interface_snapshot_is_readable_while_worker_lock_is_held(tmp_path):
    flow = RealProjectFlow(selected_root=tmp_path / 'missing', selected_parent=tmp_path)
    try:
        with flow._guard:
            with ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(flow.state).result(timeout=1)
                assert result['project'] is None
                assert result['selected_run_id'] is None
    finally:
        flow.close()


def test_new_project_is_host_selected_and_empty(tmp_path):
    root = tmp_path / 'none'
    flow = RealProjectFlow(selected_root=root, selected_parent=tmp_path)
    try:
        created = flow.create_selected('New local project')
        p = created['project']
        assert p['name'] == 'New local project' and Path(p['location']).is_dir()
        assert created['runs'] == [] and created['report'] is None
        assert created['selected_run_id'] is None and created['selected_export_id'] is None
        assert created['source_retrieval_verified'] is False
        with pytest.raises(ProjectFlowError, match='run_selection_required'):
            flow.prepare()
        assert open_project(p['location']).identifier.hex == p['project_id'].replace('-', '')
    finally:
        flow.close()


def test_trusted_host_requires_existing_valid_project(tmp_path):
    flow = RealProjectFlow(selected_root=tmp_path / 'missing', selected_parent=tmp_path)
    try:
        with pytest.raises(ProjectFlowError, match='invalid_project'):
            flow.open_selected()
        assert flow.state()['project'] is None
    finally:
        flow.close()


def test_genuine_run_export_observation_and_relocation(tmp_path):
    p, run_id = sample(tmp_path)
    flow = RealProjectFlow(selected_root=p.root, selected_parent=tmp_path)
    try:
        opened = flow.open_selected()
        assert opened['selected_run_id'] is None and len(opened['runs']) == 1
        with pytest.raises(ProjectFlowError, match='run_selection_required'):
            flow.prepare()
        with pytest.raises(ProjectFlowError, match='unknown_run'):
            flow.select_run(str(uuid4()))
        selected = flow.select_run(run_id)
        report = selected['report']
        assert report['status'] == 'incomplete'
        assert report['queries'][0]['exact_query'] == '"right ventricle"[All Fields]'
        assert report['queries'][0]['reported_matches'] is None
        assert report['counts']['totals']['global_unique_publications'] is None
        assert not selected['source_retrieval_verified']
        first = flow.prepare()
        eid = first['selected_export_id']
        assert eid and len(first['exports']) == 1
        assert first['exports'][0]['recorded_state'] == 'prepared'
        assert not first['exports'][0]['audited_success']
        count = journal_count(p)
        repeated = flow.prepare()
        assert repeated['selected_export_id'] == eid and journal_count(p) == count
        published = flow.resume()
        assert published['exports'][0]['recorded_state'] == 'published'
        # An inventory receipt alone must still never assert verified workbook success.
        assert not published['exports'][0]['audited_success']
        observed = flow.observe()
        assert observed['observation']['outcome'] == 'published_verified'
        assert observed['observation']['audited_success'] is True
        assert observed['source_retrieval_verified'] is False
        workbook = p.root / 'exports' / ('strategy-summary-' + run_id + '.xlsx')
        with ZipFile(workbook) as archive:
            assert archive.testzip() is None and 'xl/workbook.xml' in archive.namelist()
    finally:
        flow.close()
    prior_count = journal_count(p)
    moved = tmp_path / 'relocated'
    shutil.move(str(p.root), str(moved))
    reopened = open_project(moved)
    assert reopened.identifier == p.identifier
    second = RealProjectFlow(selected_root=moved, selected_parent=tmp_path)
    try:
        result = second.open_selected()
        assert result['selected_run_id'] is None and len(result['exports']) == 1
        second.select_run(run_id)
        second.select_export(eid)
        assert second.observe()['observation']['outcome'] == 'published_verified'
        assert journal_count(reopened) == prior_count
    finally:
        second.close()


def test_export_selection_cannot_mix_two_distinct_run_versions(tmp_path):
    p, first_run = sample(tmp_path)
    first = RealProjectFlow(selected_root=p.root, selected_parent=tmp_path)
    try:
        first.open_selected(); first.select_run(first_run)
        original_export = first.prepare()['selected_export_id']
    finally:
        first.close()
    version = approve_strategy(p, theme='Separate second strategy',
        approved_by='Fixture', approval_confirmed=True,
        groups=(StrategyGroup('other', 'Different', (ApprovedTerm('heart failure', 'researcher', True),)),))
    second_run = create_search_run(p, version.strategy_version_id).run_id
    plan_source_query(p, run_id=second_run, group_id='other', source_name='pubmed',
                      exact_query='"heart failure"[All Fields]')
    before = journal_count(p)
    reopened = RealProjectFlow(selected_root=p.root, selected_parent=tmp_path)
    try:
        snapshot = reopened.open_selected()
        assert len(snapshot['runs']) == 2 and len(snapshot['exports']) == 1
        reopened.select_run(second_run)
        with pytest.raises(ProjectFlowError, match='export_run_mismatch'):
            reopened.select_export(original_export)
        assert reopened.state()['selected_export_id'] is None
        assert reopened.state()['report']['run']['run_id'] == second_run
        assert journal_count(p) == before
        reopened.select_run(first_run)
        assert reopened.select_export(original_export)['selected_export_id'] == original_export
        assert reopened.state()['report']['run']['run_id'] == first_run
        reopened.select_run(second_run)
        prepared = reopened.prepare()
        second_export = prepared['selected_export_id']
        assert second_export != original_export
        reopened.resume()
        assert reopened.observe()['observation']['outcome'] == 'published_verified'
        first_path = p.root / 'exports' / ('strategy-summary-' + first_run + '.xlsx')
        second_path = p.root / 'exports' / ('strategy-summary-' + second_run + '.xlsx')
        assert first_path != second_path and second_path.is_file()
        # The first was prepared but not published in this fixture.
        assert not first_path.exists()
    finally:
        reopened.close()


def test_retained_export_report_remains_distinct_after_source_count_changes(tmp_path):
    p, run_id = sample(tmp_path)
    first = RealProjectFlow(selected_root=p.root, selected_parent=tmp_path)
    try:
        first.open_selected(); first.select_run(run_id)
        prepared = first.prepare()
        export_id = prepared['selected_export_id']
        assert prepared['retained_export_report']['queries'][0]['reported_matches'] is None
    finally:
        first.close()
    with closing(sqlite3.connect(p.database_path)) as db, db:
        db.execute('UPDATE source_queries SET reported_matches=17,status="failed" WHERE run_id=?',
                   (run_id,))
    second = RealProjectFlow(selected_root=p.root, selected_parent=tmp_path)
    try:
        second.open_selected(); selected = second.select_run(run_id)
        assert selected['report']['queries'][0]['reported_matches'] == 17
        assert selected['retained_export_report'] is None
        chosen = second.select_export(export_id)
        assert chosen['report']['queries'][0]['reported_matches'] == 17
        assert chosen['retained_export_report']['queries'][0]['reported_matches'] is None
        second.resume()
        observed = second.observe()
        assert observed['observation']['outcome'] == 'published_verified'
        assert observed['retained_export_report']['queries'][0]['reported_matches'] is None
        assert observed['source_retrieval_verified'] is False
    finally:
        second.close()


def test_existing_request_requires_explicit_selection_after_restart(tmp_path):
    p, run_id = sample(tmp_path)
    first = RealProjectFlow(selected_root=p.root, selected_parent=tmp_path)
    try:
        first.open_selected(); first.select_run(run_id)
        eid = first.prepare()['selected_export_id']
    finally:
        first.close()
    another = RealProjectFlow(selected_root=p.root, selected_parent=tmp_path)
    try:
        another.open_selected(); another.select_run(run_id)
        with pytest.raises(ProjectFlowError, match='select_existing_request'):
            another.prepare()
        assert another.select_export(eid)['selected_export_id'] == eid
        another.resume()
        assert another.observe()['observation']['outcome'] == 'published_verified'
        assert len(another.state()['exports']) == 1
    finally:
        another.close()


def test_untrusted_bytes_have_no_browser_path_route():
    text = (Path(__file__).parents[1] / 'tools/gui_feasibility/real_project_app.py').read_text()
    assert "os.environ.pop('RESEARCHY_GUI_SELECTED_ROOT')" in text
    assert "os.environ.pop('RESEARCHY_GUI_SELECTED_PARENT')" in text
    assert "app.add_middleware(PrototypeGuard, session=session)" in text
    assert "host='127.0.0.1'" in text
    assert 'create_file_dialog' not in text
    assert not any('path' in str(x) for x in inspect.signature(RealProjectFlow.select_run).parameters)
    assert not any('path' in str(x) for x in inspect.signature(RealProjectFlow.prepare).parameters)
    assert "item['run_id'] != state['selected_run_id']" in text
    assert "data-testid=exact-query" in text
    assert "data-testid=retained-query" in text and "ui.label('Exact query: ' + item['exact_query'])" in text
    assert "'unknown' if count is None else str(count)" in text


def test_rejected_untrusted_project_identity_is_static(tmp_path):
    p, _ = sample(tmp_path)
    manifest = json.loads(p.manifest_path.read_text())
    manifest['project_id'] = str(uuid4())
    p.manifest_path.write_text(json.dumps(manifest))
    flow = RealProjectFlow(selected_root=p.root, selected_parent=tmp_path)
    try:
        with pytest.raises(ProjectFlowError) as exc:
            flow.open_selected()
        assert str(exc.value) == 'invalid_project' and str(p.root) not in str(exc.value)
    finally:
        flow.close()
