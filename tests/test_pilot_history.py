"""P1-06f8: source-pilot history across project restarts, with no network.

All events are controlled fixture receipts, not live PubMed or Clarivate calls.
The original journal validators read real disk-backed SQLite through the worker.
"""
from contextlib import closing
from datetime import datetime, timezone
import inspect
import json
import sqlite3
from uuid import uuid4

import pytest

from research_y.application_commands import (
    ApplicationCommand, ApplicationCommandError, execute_command,
)
from research_y.pilot_history import (
    PAGE_SIZE, PilotHistoryError, read_pilot_history,
)
from research_y.projects import create_project, open_project
from research_y.preflight_review import read_preflight
from research_y.storage import _audit, ApprovedTerm, StrategyGroup
from research_y.strategy_admission import commit_approved_strategy
from research_y import pubmed_pilot, wos_starter_pilot
from research_y.wos_checkpoint_store import _provider_hold, _stamp
from tools.gui_feasibility.real_project_flow import RealProjectFlow, ProjectFlowError
from tools.gui_feasibility.real_project_app import run


PRIVATE = 'SECRET-FIXTURE-API-KEY'
PRIVATE_TITLE = 'LICENSED-PRIVATE-TITLE-DO-NOT-SAVE'
STAMP = '2026-11-04T12:00:00.000000+00:00'


def _fixture(tmp_path):
    project = create_project(tmp_path, 'Pilot audit history')
    approved = commit_approved_strategy(
        project, request_id=str(uuid4()), theme='Right ventricle',
        approved_by='Researcher', approval_confirmed=True,
        groups=(StrategyGroup('right', 'Right ventricle',
            (ApprovedTerm('right ventricle','researcher',True),)),),
    )
    preflight = read_preflight(project,approved.run_id)
    queries = {
        row['source_name']:row['queries'][0]
        for row in preflight['sources']
    }
    return project, approved.run_id, preflight['plan_sha256'], queries


def _audit_rows(project):
    with closing(sqlite3.connect(project.database_path)) as db:
        return db.execute(
            'SELECT event_id,event_type,details_json FROM audit_events '
            'ORDER BY event_id'
        ).fetchall()


def _insert_malformed_request(project, pilot_id):
    """Adversarial INSERT only; never disable append-only audit triggers."""
    duplicate_json = (
        '{"pilot_id":"' + pilot_id + '","pilot_id":"' + pilot_id + '"}'
    )
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute(
            "INSERT INTO audit_events (occurred_at_utc,event_type,details_json) "
            "VALUES (?,?,?)",
            (STAMP, pubmed_pilot.REQUEST_EVENT, duplicate_json))


def _source_counts(project, run_id):
    with closing(sqlite3.connect(project.database_path)) as db:
        return db.execute(
            'SELECT source_name,status,reported_matches FROM source_queries '
            'WHERE run_id=? ORDER BY source_name',(run_id,)).fetchall()


def _journal(project, run_id, plan, query, source, *,
             pilot_id=None, finish=True, count=15, status=None):
    """Insert canonical provider-core request/outcome shapes, without HTTP."""
    pilot_id = pilot_id or str(uuid4())
    if source=='pubmed':
        base = pubmed_pilot._base(
            pilot_id,run_id,query['query_id'],plan)
        req_type=pubmed_pilot.REQUEST_EVENT
        out_type=pubmed_pilot.OUTCOME_EVENT
        default='count_reported_not_retrieved'
    else:
        base = wos_starter_pilot._base(
            pilot_id,run_id,query['query_id'],plan,revalidate_quota=False)
        req_type=wos_starter_pilot.REQUEST_EVENT
        out_type=wos_starter_pilot.OUTCOME_EVENT
        default='count_reported_sample_not_retained'
    request = dict(base,exact_query=query['exact_query'],
                   status='requested_indeterminate')
    with closing(sqlite3.connect(project.database_path)) as db, db:
        _audit(db,kind=req_type,timestamp=STAMP,details=request)
        if finish:
            completed = dict(
                request, status=status or default, reported_matches=count,
                checked_at_utc=STAMP)
            if source=='wos':
                completed.update(
                    quota={'daily_limit':5000,'daily_remaining':4998,
                           'per_second_limit':2,'valid':True},
                    quota_status='institutional_allowance_observed',
                    access_probe_records_received=min(count,1))
            _audit(db,kind=out_type,timestamp=STAMP,details=completed)
    return pilot_id


def test_empty_project_is_verified_empty_with_no_provider_contact(tmp_path):
    project, run, plan, queries = _fixture(tmp_path)
    before=_audit_rows(project)
    result=read_pilot_history(open_project(project.root))
    assert result['entries']==[]
    assert result['request_events_total']==0
    assert result['next_before_event_id'] is None
    assert result['no_network_requests'] is True
    assert result['source_retrieval_verified'] is False
    assert result['execution_authorized'] is False
    assert _audit_rows(project)==before


def test_historical_pubmed_zero_and_unfinished_wos_are_distinct(tmp_path):
    project,run,plan,queries=_fixture(tmp_path)
    zero=_journal(project,run,plan,queries['pubmed'],'pubmed',count=0)
    unknown=_journal(project,run,plan,queries['wos'],'wos',finish=False)
    before=_audit_rows(project)
    source_before=_source_counts(project,run)
    result=read_pilot_history(project)
    assert result['request_events_total']==2
    assert len(result['entries'])==2
    assert result['next_before_event_id'] is None
    assert [row['pilot_id'] for row in result['entries']]==[unknown,zero]
    wos,pubmed=result['entries']
    assert (wos['source'],wos['status'],wos['reported_matches']) == (
        'wos','requested_indeterminate',None)
    assert (pubmed['source'],pubmed['status'],pubmed['reported_matches']) == (
        'pubmed','count_reported_not_retrieved',0)
    assert wos['sample_only'] is True and wos['count_only'] is False
    assert pubmed['sample_only'] is False and pubmed['count_only'] is True
    assert wos['automatically_retryable'] is False
    for record in result['entries']:
        assert record['source_retrieval_verified'] is False
        assert record['search_completed'] is False
        assert record['execution_authorized'] is False
        assert 'exact_query' not in record
        assert 'accepted_translation' not in record
        assert PRIVATE not in json.dumps(record)
        assert PRIVATE_TITLE not in json.dumps(record)
    assert _audit_rows(project)==before
    assert _source_counts(project,run)==source_before


def test_paginated_history_has_no_duplicate_requests_and_never_claims_full_page(tmp_path):
    project,run,plan,queries=_fixture(tmp_path)
    created=[
        _journal(project,run,plan,queries['pubmed'],'pubmed',count=n)
        for n in range(PAGE_SIZE+3)
    ]
    first=read_pilot_history(project)
    assert first['request_events_total']==len(created)
    assert len(first['entries'])==PAGE_SIZE
    assert first['next_before_event_id'] is not None
    assert first['entries'][0]['pilot_id']==created[-1]
    assert first['entries'][-1]['pilot_id']==created[-PAGE_SIZE]
    older=read_pilot_history(
        project,before_event_id=first['next_before_event_id'])
    assert len(older['entries'])==3
    assert older['next_before_event_id'] is None
    assert [x['pilot_id'] for x in older['entries']]==list(
        reversed(created[:3]))
    assert len({x['pilot_id'] for x in first['entries']+older['entries']})==len(created)
    assert _source_counts(project,run)[0][2] is None


@pytest.mark.parametrize('bad',[True,False,0,-1,1.5,'123',[],{},2**63])
def test_history_rejects_invalid_cursor_before_file_access(tmp_path,bad):
    project,run,plan,queries=_fixture(tmp_path)
    with pytest.raises(PilotHistoryError,match='^pilot_history_cursor_invalid$'):
        read_pilot_history(project,before_event_id=bad)
    with pytest.raises(ApplicationCommandError,match='^invalid_command$'):
        ApplicationCommand.for_project(
            project,'pilot_history',history_before_event_id=bad)


def test_worker_allowlisted_history_is_read_only_and_no_credential_argument(tmp_path):
    project,run,plan,queries=_fixture(tmp_path)
    pid=_journal(project,run,plan,queries['pubmed'],'pubmed')
    before=_audit_rows(project)
    cmd=ApplicationCommand.for_project(project,'pilot_history')
    assert 'project' not in repr(cmd).lower()
    result=execute_command(cmd)
    assert result['entries'][0]['pilot_id']==pid
    assert result['no_network_requests']
    assert _audit_rows(project)==before
    with pytest.raises(ApplicationCommandError,match='^invalid_command$'):
        ApplicationCommand.for_project(project,'pilot_history',pilot_api_key=PRIVATE)
    with pytest.raises(ApplicationCommandError,match='^invalid_command$'):
        ApplicationCommand.for_project(
            project,'pubmed_pilot_read',pilot_id=pid,history_before_event_id=1)


def test_orphan_outcome_does_not_disappear_as_an_empty_history(tmp_path):
    project,run,plan,queries=_fixture(tmp_path)
    pid=str(uuid4())
    orphan=dict(pubmed_pilot._base(pid,run,queries['pubmed']['query_id'],plan),
        exact_query=queries['pubmed']['exact_query'],
        status='count_reported_not_retrieved',reported_matches=1)
    with closing(sqlite3.connect(project.database_path)) as db,db:
        _audit(db,kind=pubmed_pilot.OUTCOME_EVENT,
               timestamp=STAMP,details=orphan)
    with pytest.raises(PilotHistoryError,match='^pilot_evidence_invalid$'):
        read_pilot_history(project)


def test_duplicate_request_uuid_and_duplicate_json_keys_fail_closed(tmp_path):
    project,run,plan,queries=_fixture(tmp_path)
    pid=_journal(project,run,plan,queries['pubmed'],'pubmed',finish=False)
    _journal(project,run,plan,queries['pubmed'],'pubmed',
             pilot_id=pid,finish=False)
    with pytest.raises(PilotHistoryError,match='^pilot_evidence_invalid$'):
        read_pilot_history(project)
    # A different malformed project uses append-only INSERT; real projects
    # prohibit UPDATE and DELETE of existing audit history.
    malformed_parent=tmp_path / 'malformed'
    malformed_parent.mkdir()
    malformed,_,_,_=_fixture(malformed_parent)
    _insert_malformed_request(malformed,str(uuid4()))
    with pytest.raises(PilotHistoryError,match='^pilot_evidence_invalid$'):
        read_pilot_history(malformed)


def test_reopen_discovers_old_attempts_without_any_key_or_run_selection(tmp_path):
    project,run,plan,queries=_fixture(tmp_path)
    pub=_journal(project,run,plan,queries['pubmed'],'pubmed',count=5)
    wos=_journal(project,run,plan,queries['wos'],'wos',finish=False)
    old_events=_audit_rows(project)
    flow=RealProjectFlow(selected_root=project.root,selected_parent=tmp_path)
    try:
        state=flow.open_selected()
        assert state['selected_run_id'] is None
        assert state['pubmed_profile_configured'] is False
        assert state['wos_profile_configured'] is False
        assert state['pilot_history_error'] is None
        assert state['pilot_history']['request_events_total']==2
        assert state['pilot_history']['entries'][0]['pilot_id']==wos
        selected=flow.inspect_saved_pilot(wos)['saved_pilot_detail']
        assert selected['status']=='requested_indeterminate'
        assert selected['count_only'] is False
        assert selected['bibliographic_records_persisted']==0
    finally:
        flow.close()
    reopened=RealProjectFlow(selected_root=project.root,selected_parent=tmp_path)
    try:
        again=reopened.open_selected()
        assert again['selected_run_id'] is None
        assert [x['pilot_id'] for x in again['pilot_history']['entries']]==[wos,pub]
        assert reopened.inspect_saved_pilot(pub)['saved_pilot_detail']['reported_matches']==5
        assert _audit_rows(project)==old_events
    finally:
        reopened.close()


def test_gui_restart_preserves_wos_outcome_unknown_provider_guard(tmp_path,monkeypatch):
    from research_y import wos_checkpoint_store
    monkeypatch.setattr(wos_checkpoint_store,'MIN_REQUEST_INTERVAL',0.0)
    project,run,plan,queries=_fixture(tmp_path)
    _journal(project,run,plan,queries['wos'],'wos',finish=False)
    flow=RealProjectFlow(selected_root=project.root,selected_parent=tmp_path)
    try:
        state=flow.open_selected()
        assert state['pilot_history']['entries'][0]['status']=='requested_indeterminate'
        with closing(sqlite3.connect(project.database_path)) as db:
            hold,_=_provider_hold(
                db,_stamp(datetime.now(timezone.utc)),revalidate_quota=True)
        assert hold=='provider_pilot_outcome_unknown'
        assert flow.state()['pilot_history']['entries'][0]['reported_matches'] is None
    finally:
        flow.close()


def test_gui_older_page_and_selected_historical_receipt(tmp_path):
    project,run,plan,queries=_fixture(tmp_path)
    ids=[_journal(project,run,plan,queries['pubmed'],'pubmed',count=i)
         for i in range(PAGE_SIZE+1)]
    flow=RealProjectFlow(selected_root=project.root,selected_parent=tmp_path)
    try:
        recent=flow.open_selected()['pilot_history']
        assert recent['entries'][0]['pilot_id']==ids[-1]
        cursor=recent['next_before_event_id']
        with pytest.raises(ProjectFlowError,match='^pilot_history_cursor_invalid$'):
            flow.inspect_pilot_history(before_event_id=cursor-1)
        older=flow.inspect_pilot_history(before_event_id=cursor)['pilot_history']
        assert len(older['entries'])==1
        assert older['entries'][0]['pilot_id']==ids[0]
        with pytest.raises(ProjectFlowError,match='^unknown_pilot$'):
            flow.inspect_saved_pilot(ids[-1])
        detail=flow.inspect_saved_pilot(ids[0])['saved_pilot_detail']
        assert detail['reported_matches']==0
        assert detail['count_only'] is True
        refreshed=flow.inspect_pilot_history()['pilot_history']
        assert len(refreshed['entries'])==PAGE_SIZE
        assert flow.state()['saved_pilot_detail'] is None
    finally:
        flow.close()


def test_gui_corrupt_pilot_history_is_warning_not_false_empty(tmp_path):
    project,run,plan,queries=_fixture(tmp_path)
    pid=str(uuid4())
    _insert_malformed_request(project,pid)
    flow=RealProjectFlow(selected_root=project.root,selected_parent=tmp_path)
    try:
        state=flow.open_selected()
        assert state['project']['name']==project.name
        assert state['pilot_history'] is None
        assert state['pilot_history_error']=='pilot_history_unavailable'
        with pytest.raises(ProjectFlowError,match='^pilot_history_unavailable$'):
            flow.inspect_saved_pilot(pid)
        with pytest.raises(ProjectFlowError):
            flow.inspect_pilot_history()
        assert flow.state()['pilot_history_error']=='pilot_history_unavailable'
    finally:
        flow.close()


def test_stale_saved_detail_refused_until_current_history_refreshed(tmp_path):
    project,run,plan,queries=_fixture(tmp_path)
    pid=_journal(project,run,plan,queries['pubmed'],'pubmed',finish=False)
    flow=RealProjectFlow(selected_root=project.root,selected_parent=tmp_path)
    try:
        flow.open_selected()
        # A distinct process can append a legitimate outcome between list
        # inspection and detail inspection. Never stitch both snapshots.
        result=dict(pubmed_pilot._base(pid,run,queries['pubmed']['query_id'],plan),
                    exact_query=queries['pubmed']['exact_query'],
                    status='count_reported_not_retrieved',reported_matches=0,
                    checked_at_utc=STAMP)
        with closing(sqlite3.connect(project.database_path)) as db,db:
            _audit(db,kind=pubmed_pilot.OUTCOME_EVENT,timestamp=STAMP,details=result)
        with pytest.raises(ProjectFlowError,match='^pilot_history_stale$'):
            flow.inspect_saved_pilot(pid)
        refreshed=flow.inspect_pilot_history()['pilot_history']
        assert refreshed['entries'][0]['status']=='count_reported_not_retrieved'
        assert flow.inspect_saved_pilot(pid)['saved_pilot_detail']['reported_matches']==0
    finally:
        flow.close()


def test_history_graphical_controls_cannot_trigger_provider_or_forge_paths():
    src=inspect.getsource(run)
    for value in ('pilot_history_refresh','pilot_history_older',
                  'pilot_history_detail','pilot-history-heading',
                  'pilot-history-indeterminate','pilot-history-error'):
        assert value in src
    assert 'ui.html(' not in src
    probe=src.split("@app.post('/_probe/start')")[1].split(
        "@app.post('/_probe/stop')")[0]
    assert 'pilot_history' not in probe
