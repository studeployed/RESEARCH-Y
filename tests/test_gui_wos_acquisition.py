"""P1-06g1: explicit, checkpointed Starter record acquisition via local GUI.

No live institutional requests occur in these tests. Only synthetic licensed
record fixtures reach the real quota-aware source engine and SQLite project.
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import inspect
import json
import sqlite3
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest

from research_y import wos_acquisition_gui as acquisition
from research_y.projects import create_project
from research_y.storage import ApprovedTerm, StrategyGroup
from research_y.strategy_admission import commit_approved_strategy
from research_y.wos_checkpoint_runner import run_wos_checkpoint
from research_y.wos_checkpoint_store import (
    inspect_wos_checkpoint, WoSCheckpointError,
)
from research_y.wos_starter_client import WoSHTTPResponse, WoSStarterClient
from tools.gui_feasibility.real_project_flow import RealProjectFlow, ProjectFlowError
from tools.gui_feasibility.wos_host_profile import WoSHostProfile
from tools.gui_feasibility.real_project_app import run

KEY = 'SYNTHETIC-PRIVATE-STARTER-KEY'
TITLE = 'PRIVATE-LICENSED-RECORD-TITLE'
QUERY = 'TS=("ECMO")'


class Clock:
    def __init__(self):
        self.initial=datetime.now(timezone.utc)
        self.seconds=0.0

    def now(self):
        return self.initial+timedelta(seconds=self.seconds)

    def monotonic(self):
        return self.seconds+5000

    def sleep(self, seconds):
        self.seconds+=seconds


class Provider:
    def __init__(self, clock, *, count=103, quota=5000):
        self.clock=clock
        self.count=count
        self.quota=quota
        self.calls=[]
        self.remaining=4999

    def __call__(self, request, timeout):
        values=parse_qs(urlsplit(request.full_url).query)
        assert request.get_method()=='GET'
        assert urlsplit(request.full_url).netloc=='api.clarivate.com'
        assert urlsplit(request.full_url).path=='/apis/wos-starter/v1/documents'
        assert values['q']==[QUERY]
        assert values['db']==['WOS'] and values['sortField']==['LD+A']
        assert request.get_header('X-apikey')==KEY
        assert timeout==10
        assert KEY not in request.full_url
        page=int(values['page'][0])
        limit=int(values['limit'][0])
        assert limit in (1,50)
        self.calls.append((page,limit))
        self.clock.sleep(2)
        self.remaining-=1
        records=[{
            'uid':f'WOS:{i+1:015d}',
            'title':TITLE,
            'licensed_extras':{'copyright':'private'}
        } for i in range((page-1)*limit,min(page*limit,self.count))]
        body={'metadata':{'total':self.count,'page':page,'limit':limit},
              'hits':records}
        headers={'X-RateLimit-Limit-Day':str(self.quota),
                 'X-RateLimit-Remaining-Day':str(self.remaining)}
        return WoSHTTPResponse(200,headers,json.dumps(body).encode())


def _project(tmp_path):
    project=create_project(tmp_path,'Source acquisition fixture')
    admitted=commit_approved_strategy(
        project,request_id=str(uuid4()),theme='Extracorporeal studies',
        approved_by='Researcher',approval_confirmed=True,
        groups=(StrategyGroup('g-ecmo','ECMO',
            (ApprovedTerm('ECMO','researcher',True),)),))
    return project,admitted.run_id


def _flow(tmp_path, *, profile=True):
    project,rid=_project(tmp_path)
    flow=RealProjectFlow(selected_root=project.root,
                         selected_parent=tmp_path,
                         wos_profile=WoSHostProfile(KEY) if profile else None)
    flow.open_selected()
    flow.select_run(rid)
    report=flow.inspect_preflight()['preflight_report']
    query=next(row for s in report['sources'] if s['source_name']=='wos'
               for row in s['queries'])
    assert query['exact_query']==QUERY
    return project,flow,rid,query


def _rows(project):
    with closing(sqlite3.connect(project.database_path)) as db:
        return {
            'metadata':db.execute(
                "SELECT original_metadata_json FROM source_retrievals "
                "WHERE source_name='wos'").fetchall(),
            'queries':db.execute(
                "SELECT source_name,status,reported_matches "
                "FROM source_queries ORDER BY source_name").fetchall(),
            'jobs':db.execute("SELECT COUNT(*) FROM wos_checkpoint_jobs").fetchone()[0],
            'events':db.execute(
                "SELECT event_type,details_json FROM audit_events "
                "ORDER BY event_id").fetchall(),
        }


def _inject_tick(monkeypatch,flow, *, count=103,lost_reply=False):
    clock=Clock()
    provider=Provider(clock,count=count)
    original=flow._operation
    once={'lose':lost_reply}
    real=run_wos_checkpoint

    def run_with_clock(project,query_id,client,**options):
        return real(project,query_id,client,now=clock.now,**options)

    monkeypatch.setattr(acquisition,'run_wos_checkpoint',run_with_clock)

    def substitute(name,**kw):
        if name!='wos_acquisition_tick':
            return original(name,**kw)
        assert kw['acquisition_confirmed'] is True
        assert kw['acquisition_api_key']==KEY
        assert type(kw['acquisition_revalidate_quota']) is bool
        client=WoSStarterClient(
            api_key=kw['acquisition_api_key'],
            request_budget=3,timeout=10,
            transport=provider,clock=clock.monotonic,
            sleep=clock.sleep,utc_now=clock.now)
        result=acquisition.run_wos_acquisition_session(
            flow.project,run_id=kw['run_id'],query_id=kw['acquisition_query_id'],
            confirmed=True,
            revalidate_quota=kw['acquisition_revalidate_quota'],client=client)
        if once['lose']:
            once['lose']=False
            raise ProjectFlowError('worker_interrupted')
        return result

    monkeypatch.setattr(flow,'_operation',substitute)
    return clock,provider


def test_prepare_is_offline_with_exact_frozen_plan_and_local_retention_consent(tmp_path):
    project,flow,rid,q=_flow(tmp_path)
    try:
        original=_rows(project)
        assert original['jobs']==0
        offer=flow.offer_wos_acquisition(q['query_id'])
        assert offer['wos_acquisition_offer']['exact_query']==QUERY
        assert _rows(project)==original
        cancelled=flow.dismiss_wos_acquisition()
        assert cancelled['wos_acquisition_offer'] is None
        assert _rows(project)==original
        with pytest.raises(ProjectFlowError,match='retention_confirmation_required'):
            flow.confirm_wos_acquisition()
        flow.offer_wos_acquisition(q['query_id'])
        confirmed=flow.confirm_wos_acquisition()
        checkpoint=confirmed['wos_acquisition']
        assert checkpoint['approved_gui_retention'] is True
        assert checkpoint['exact_query']==QUERY
        assert checkpoint['no_network_requests'] is True
        assert checkpoint['preflight_sha256']==flow.state()['preflight_report']['plan_sha256']
        assert checkpoint['checkpoint']['status']=='pending'
        assert checkpoint['checkpoint']['reported_matches'] is None
        assert checkpoint['checkpoint']['records_committed']==0
        assert checkpoint['source_retrieval_verified'] is False
        after=_rows(project)
        assert after['jobs']==1 and after['metadata']==[]
        assert after['queries']==original['queries']
        assert len([event for event,_ in after['events']
                    if event=='wos_checkpoint_created'])==1
        assert KEY not in json.dumps(confirmed)
    finally:
        flow.close()


def test_exact_plan_or_wrong_source_rejected_before_retention(tmp_path):
    project,flow,rid,q=_flow(tmp_path)
    try:
        pubmed=next(row for src in flow.state()['preflight_report']['sources']
                    if src['source_name']=='pubmed' for row in src['queries'])
        with pytest.raises(ProjectFlowError,match='unknown_wos_query'):
            flow.offer_wos_acquisition(pubmed['query_id'])
        with pytest.raises(ProjectFlowError,match='unknown_wos_query'):
            flow.offer_wos_acquisition(str(uuid4()))
        flow.offer_wos_acquisition(q['query_id'])
        with closing(sqlite3.connect(project.database_path)) as db,db:
            db.execute("UPDATE source_queries SET exact_query=? WHERE query_id=?",
                       ('TS=("wrong")',q['query_id']))
        with pytest.raises(ProjectFlowError,match='source_plan_unverified'):
            flow.confirm_wos_acquisition()
        assert _rows(project)['jobs']==0
        assert flow.state()['wos_acquisition_prepare_pending'] is True
        assert flow.reconcile_wos_acquisition()['wos_acquisition'] is None
        assert flow.state()['wos_acquisition_prepare_pending'] is False
    finally:
        flow.close()


def test_lost_prepare_response_reopens_original_checkpoint_not_duplicate(tmp_path,monkeypatch):
    project,flow,rid,q=_flow(tmp_path)
    original=flow._operation
    lost={'yes':True}

    def substitute(name,**kw):
        result=original(name,**kw)
        if name=='wos_acquisition_prepare' and lost['yes']:
            lost['yes']=False
            raise ProjectFlowError('worker_interrupted')
        return result

    monkeypatch.setattr(flow,'_operation',substitute)
    try:
        flow.offer_wos_acquisition(q['query_id'])
        with pytest.raises(ProjectFlowError,match='worker_interrupted'):
            flow.confirm_wos_acquisition()
        assert flow.state()['wos_acquisition_prepare_pending'] is True
        with pytest.raises(ProjectFlowError,match='acquisition_reconciliation_required'):
            flow.select_run(rid)
        recovered=flow.reconcile_wos_acquisition()
        assert recovered['wos_acquisition']['approved_gui_retention'] is True
        assert recovered['wos_acquisition_prepare_pending'] is False
        assert _rows(project)['jobs']==1
        assert len([event for event,_ in _rows(project)['events']
                    if event=='wos_checkpoint_created'])==1
    finally:
        flow.close()


def test_actual_three_request_bounded_acquisition_stores_records_without_false_completion(
        tmp_path,monkeypatch):
    project,flow,rid,q=_flow(tmp_path)
    try:
        flow.offer_wos_acquisition(q['query_id'])
        flow.confirm_wos_acquisition()
        clock,provider=_inject_tick(monkeypatch,flow,count=103)
        offer=flow.offer_wos_acquisition_tick()
        assert offer['wos_acquisition_tick_offer']['query_id']==q['query_id']
        assert provider.calls==[]
        flow.dismiss_wos_acquisition_tick()
        assert provider.calls==[]
        with pytest.raises(ProjectFlowError,match='session_confirmation_required'):
            flow.confirm_wos_acquisition_tick()
        flow.offer_wos_acquisition_tick()
        done=flow.confirm_wos_acquisition_tick()
        state=done['wos_acquisition']
        assert provider.calls==[(1,50),(2,50),(3,50)]
        assert state['checkpoint']['status']=='paused'
        assert state['checkpoint']['records_committed']==103
        assert state['checkpoint']['pages_committed']==3
        assert state['checkpoint']['reported_matches']==103
        assert not state['checkpoint']['enumeration_reconciled']
        assert not state['source_retrieval_verified']
        assert not state['whole_search_verified']
        assert not state['provider_snapshot_guaranteed']
        assert done['report']['run']['status']=='incomplete'
        assert KEY not in json.dumps(done)
        assert TITLE not in json.dumps(done)
        stored=_rows(project)
        assert len(stored['metadata'])==103
        assert TITLE in stored['metadata'][0][0]
        with pytest.raises(ProjectFlowError,match='session_confirmation_required'):
            flow.confirm_wos_acquisition_tick()  # double click must not resend
        assert len(provider.calls)==3
        assert flow.state()['preflight_report'] is None
    finally:
        flow.close()


def test_crash_after_source_record_commit_only_read_back_never_replay(tmp_path,monkeypatch):
    project,flow,rid,q=_flow(tmp_path)
    try:
        flow.offer_wos_acquisition(q['query_id'])
        flow.confirm_wos_acquisition()
        clock,provider=_inject_tick(monkeypatch,flow,lost_reply=True)
        flow.offer_wos_acquisition_tick()
        with pytest.raises(ProjectFlowError,match='worker_interrupted'):
            flow.confirm_wos_acquisition_tick()
        assert flow.state()['wos_acquisition_tick_pending'] is True
        with pytest.raises(ProjectFlowError,match='acquisition_reconciliation_required'):
            flow.offer_wos_acquisition_tick()
        with pytest.raises(ProjectFlowError,match='acquisition_reconciliation_required'):
            flow.select_run(rid)
        observed=flow.reconcile_wos_acquisition_tick()
        assert observed['wos_acquisition']['checkpoint']['records_committed']==103
        assert observed['wos_acquisition_tick_pending'] is False
        assert len(provider.calls)==3
        assert len(_rows(project)['metadata'])==103
    finally:
        flow.close()


def test_reopen_source_checkpoint_with_no_host_key_does_not_authorize_network(
        tmp_path,monkeypatch):
    project,flow,rid,q=_flow(tmp_path)
    try:
        flow.offer_wos_acquisition(q['query_id'])
        flow.confirm_wos_acquisition()
        clock,provider=_inject_tick(monkeypatch,flow)
        flow.offer_wos_acquisition_tick()
        flow.confirm_wos_acquisition_tick()
    finally:
        flow.close()
    new=RealProjectFlow(selected_root=project.root,selected_parent=tmp_path)
    try:
        new.open_selected()
        new.select_run(rid)
        stored=new.inspect_stored_wos_acquisition(q['query_id'])['wos_acquisition']
        assert stored['checkpoint']['records_committed']==103
        assert stored['approved_gui_retention'] is True
        assert stored['no_network_requests'] is True
        assert new.state()['wos_profile_configured'] is False
        with pytest.raises(ProjectFlowError,match='wos_profile_unavailable'):
            new.offer_wos_acquisition_tick()
        assert len(_rows(project)['metadata'])==103
        assert len(provider.calls)==3
    finally:
        new.close()


def test_no_profile_blocks_source_retention_offer(tmp_path):
    project,flow,rid,q=_flow(tmp_path,profile=False)
    try:
        with pytest.raises(ProjectFlowError,match='wos_profile_unavailable'):
            flow.offer_wos_acquisition(q['query_id'])
        with pytest.raises(ProjectFlowError,match='retention_confirmation_required'):
            flow.confirm_wos_acquisition()
        assert _rows(project)['jobs']==0
    finally:
        flow.close()


def test_non_gui_checkpoint_read_only_not_silently_upgraded(tmp_path):
    from research_y.wos_checkpoint_store import create_wos_checkpoint
    project,rid=_project(tmp_path)
    with closing(sqlite3.connect(project.database_path)) as db:
        qid=db.execute(
            "SELECT query_id FROM source_queries WHERE run_id=? AND source_name='wos'",
            (rid,)).fetchone()[0]
    create_wos_checkpoint(project,qid,retention_authorized=True)
    flow=RealProjectFlow(selected_root=project.root,selected_parent=tmp_path,
                         wos_profile=WoSHostProfile(KEY))
    try:
        flow.open_selected()
        flow.select_run(rid)
        info=flow.inspect_stored_wos_acquisition(qid)['wos_acquisition']
        assert info['approved_gui_retention'] is False
        with pytest.raises(ProjectFlowError,match='gui_admission_missing'):
            flow.offer_wos_acquisition_tick()
        assert _rows(project)['metadata']==[]
    finally:
        flow.close()


def test_source_session_requires_explicit_confirmation_and_fresh_client(tmp_path):
    project,flow,rid,q=_flow(tmp_path)
    try:
        flow.offer_wos_acquisition(q['query_id'])
        flow.confirm_wos_acquisition()
        c=WoSStarterClient(api_key=KEY,request_budget=2)
        with pytest.raises(acquisition.WoSAcquisitionError,
                           match='session_confirmation_required'):
            acquisition.run_wos_acquisition_session(
                project,run_id=rid,query_id=q['query_id'],
                confirmed=False,client=c)
        with pytest.raises(acquisition.WoSAcquisitionError,
                           match='session_confirmation_required'):
            acquisition.run_wos_acquisition_session(
                project,run_id=rid,query_id=q['query_id'],
                confirmed=True,client=c,revalidate_quota=1)
        assert _rows(project)['metadata']==[]
    finally:
        flow.close()


def test_single_page_acquisition_can_reconcile_with_three_request_budget(tmp_path,monkeypatch):
    project,flow,rid,q=_flow(tmp_path)
    try:
        flow.offer_wos_acquisition(q['query_id'])
        flow.confirm_wos_acquisition()
        clock,provider=_inject_tick(monkeypatch,flow,count=1)
        flow.offer_wos_acquisition_tick()
        result=flow.confirm_wos_acquisition_tick()
        saved=result['wos_acquisition']
        assert provider.calls==[(1,50),(1,50),(1,1)]
        assert saved['checkpoint']['status']=='completed_with_warnings'
        assert saved['checkpoint']['stage']=='done'
        assert saved['checkpoint']['pages_expected']==1
        assert saved['checkpoint']['enumeration_reconciled'] is True
        assert saved['checkpoint']['records_committed']==1
        assert saved['source_retrieval_verified'] is False
        assert saved['whole_search_verified'] is False
        with pytest.raises(ProjectFlowError,match='acquisition_already_terminal'):
            flow.offer_wos_acquisition_tick()
    finally:
        flow.close()


def test_multi_page_verification_never_repeats_futile_two_request_sweeps(
        tmp_path,monkeypatch):
    project,flow,rid,q=_flow(tmp_path)
    try:
        flow.offer_wos_acquisition(q['query_id'])
        flow.confirm_wos_acquisition()
        clock,provider=_inject_tick(monkeypatch,flow,count=103)
        flow.offer_wos_acquisition_tick()
        saved=flow.confirm_wos_acquisition_tick()['wos_acquisition']
        assert saved['checkpoint']['records_committed']==103
        assert saved['checkpoint']['stage']=='verify'
        assert saved['checkpoint']['pages_expected']==3
        assert saved['checkpoint']['enumeration_reconciled'] is False
        with pytest.raises(ProjectFlowError,match='verification_requires_long_worker'):
            flow.offer_wos_acquisition_tick()
        # The service boundary must agree with the GUI restriction, even if
        # a caller constructs an otherwise legitimate new client.
        client=WoSStarterClient(api_key=KEY,request_budget=3)
        with pytest.raises(acquisition.WoSAcquisitionError,
                           match='verification_requires_long_worker'):
            acquisition.run_wos_acquisition_session(
                project,run_id=rid,query_id=q['query_id'],confirmed=True,
                client=client)
        assert len(provider.calls)==3
    finally:
        flow.close()


def test_untouched_group_may_be_prepared_after_sibling_retrieval_started(
        tmp_path,monkeypatch):
    from research_y.preflight_review import PreflightError, read_preflight
    project=create_project(tmp_path,'Two independent OR groups')
    admitted=commit_approved_strategy(
        project,request_id=str(uuid4()),theme='Two broad concepts',
        approved_by='Researcher',approval_confirmed=True,
        groups=(
            StrategyGroup('g-first','ECMO',(
                ApprovedTerm('ECMO','researcher',True),)),
            StrategyGroup('g-second','Right heart',(
                ApprovedTerm('right ventricle','researcher',True),)),
        ),
    )
    flow=RealProjectFlow(selected_root=project.root,
                         selected_parent=tmp_path,wos_profile=WoSHostProfile(KEY))
    try:
        flow.open_selected()
        flow.select_run(admitted.run_id)
        preflight=flow.inspect_preflight()['preflight_report']
        original_sha=preflight['plan_sha256']
        wos=next(s for s in preflight['sources'] if s['source_name']=='wos')
        first=next(q for q in wos['queries'] if q['group_id']=='g-first')
        second=next(q for q in wos['queries'] if q['group_id']=='g-second')
        flow.offer_wos_acquisition(first['query_id'])
        flow.confirm_wos_acquisition()
        clock,provider=_inject_tick(monkeypatch,flow,count=103)
        flow.offer_wos_acquisition_tick()
        flow.confirm_wos_acquisition_tick()
        assert flow.state()['report']['run']['status']=='incomplete'
        assert flow.state()['preflight_report'] is None
        with pytest.raises(PreflightError,match='run_not_pending'):
            read_preflight(project,admitted.run_id)
        # A SOURCE-SPECIFIC, read-only reconstruction validates the original
        # frozen broad-OR plan without resetting the executed sibling.
        offered=flow.offer_wos_acquisition(second['query_id'])
        assert offered['wos_acquisition_offer']['plan_sha256']==original_sha
        assert offered['wos_acquisition_offer']['exact_query']=='TS=("right ventricle")'
        prepared=flow.confirm_wos_acquisition()['wos_acquisition']
        assert prepared['approved_gui_retention'] is True
        assert prepared['preflight_sha256']==original_sha
        assert prepared['checkpoint']['status']=='pending'
        assert len(provider.calls)==3  # Preparing a second group is offline.
        assert _rows(project)['jobs']==2
        assert len(_rows(project)['metadata'])==103
    finally:
        flow.close()


def test_gui_has_explicit_retention_and_session_controls_not_probe_automation():
    source=inspect.getsource(run)
    for name in ('wos_acquisition_offer','wos_acquisition_prepare',
                 'wos_acquisition_tick_offer','wos_acquisition_tick_confirm',
                 'wos_acquisition_tick_reconcile'):
        assert "name == '"+name+"'" in source
    for marker in ('wos-acquisition-prepare','wos-acquisition-tick-confirm',
                   'wos-acquisition-tick-reconcile','wos-acquisition-progress'):
        assert "data-testid="+marker in source
    block=source.split("@app.post('/_probe/start')")[1].split(
        "@app.post('/_probe/stop')")[0]
    assert 'wos_acquisition' not in block
    assert 'ui.html(' not in source
