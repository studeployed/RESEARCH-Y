"""P1-06h1 — Explicit PubMed ESearch identifier retrieval in isolated local GUI.

Synthetic official ESearch replies only. Real immutable strategy, original
SQLite checkpoints, original PubMed parser/partitioner and supervised host
state machine are exercised. No external provider requests in normal CI.
"""
from contextlib import closing
from datetime import date
import inspect
import json
import sqlite3
from urllib.parse import parse_qs
from uuid import uuid4

import pytest

from research_y import pubmed_source_gui as source
from research_y.projects import create_project
from research_y.storage import ApprovedTerm, StrategyGroup
from research_y.strategy_admission import commit_approved_strategy
from research_y.pubmed_probe import PubMedESearchProbeClient
from research_y.application_worker import OperationStatus
from research_y.pubmed_checkpoint_store import inspect_pubmed_checkpoint
from tools.gui_feasibility.pubmed_host_profile import PubMedHostProfile
from tools.gui_feasibility.real_project_flow import RealProjectFlow, ProjectFlowError
from tools.gui_feasibility.real_project_app import run

EMAIL='private@synthetic.example'
KEY='PRIVATE-SYNTHETIC-NCBI-KEY'
START='1800-01-01'
END='2026-11-04'
IDS=('1000001','1000002','1000003','1000004')


class Transport:
    def __init__(self, query, *, ids=IDS, root_count=None, dated_count=None):
        self.query=query
        self.ids=ids
        self.root_count=len(ids) if root_count is None else root_count
        self.dated_count=dated_count
        self.calls=[]
        self.on_page=None

    def __call__(self,req,timeout):
        assert req.get_method()=='POST'
        assert req.full_url=='https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi'
        assert timeout==15
        fields=parse_qs(req.data.decode('utf-8'))
        assert fields['db']==['pubmed'] and fields['retmode']==['json']
        assert fields['tool']==['RESEARCHY'] and fields['email']==[EMAIL]
        assert fields['api_key']==[KEY]
        query=fields['term'][0]
        count=self.root_count if query==self.query else self.dated_count
        assert count is not None
        retmax=int(fields['retmax'][0])
        offset=int(fields.get('retstart',['0'])[0])
        self.calls.append((query,offset,retmax))
        if self.on_page is not None and retmax:
            self.on_page()
        return json.dumps({'esearchresult':{
            'count':str(count),'retstart':str(offset),'retmax':str(retmax),
            'idlist':list(self.ids[offset:offset+retmax]) if retmax else [],
            'querytranslation':query,
            'warninglist':{'outputmessages':[]},
            'errorlist':{'phrasesnotfound':[]},
        }}).encode()


def _project(tmp_path):
    project=create_project(tmp_path,'PubMed graphical source fixture')
    approval=commit_approved_strategy(
        project,request_id=str(uuid4()),theme='Extracorporeal medicine',
        approved_by='Researcher',approval_confirmed=True,
        groups=(StrategyGroup('g-one','ECMO',(
            ApprovedTerm('ECMO','researcher',True),)),),
    )
    with closing(sqlite3.connect(project.database_path)) as db:
        row=db.execute("SELECT query_id,exact_query FROM source_queries "
                       "WHERE run_id=? AND source_name='pubmed'",(
                           approval.run_id,)).fetchone()
    assert row is not None
    return project,approval.run_id,row[0],row[1]


def _flow(tmp_path, *, profile=True):
    project,rid,qid,query=_project(tmp_path)
    flow=RealProjectFlow(
        selected_root=project.root,selected_parent=tmp_path,
        pubmed_profile=PubMedHostProfile(EMAIL,KEY) if profile else None)
    flow.open_selected()
    flow.select_run(rid)
    return project,flow,rid,qid,query


def _client(transport):
    # Deterministic test pacing, no operating-system sleeping or network.
    class Clock:
        current=10000.
        def now(self):
            self.current+=1.
            return self.current
    clock=Clock()
    return PubMedESearchProbeClient(
        email=EMAIL,api_key=KEY,transport=transport,
        timeout=15,clock=clock.now,sleep=lambda _:None)


def _limit_synthetic_esearch_attempts(monkeypatch, *, limit):
    """Cap only synthetic request dispatch, never the production/GUI budget.

    A real spawned read worker still sees MAX_PUBMED_REQUESTS=512; changing
    that constant in one process would fabricate contradictory checkpoint
    presentation fields and invalidate late-pause reconciliation.
    """
    original = source._BudgetedESearch._reserve

    def capped_reserve(self):
        if self.requests_made >= limit:
            raise source.PubMedProbeError("Synthetic local transport budget exhausted")
        return original(self)

    monkeypatch.setattr(source._BudgetedESearch, "_reserve", capped_reserve)
    return original


def _db(project):
    with closing(sqlite3.connect(project.database_path)) as db:
        return {
            'pages':db.execute('SELECT COUNT(*) FROM pubmed_checkpoint_pages').fetchone()[0],
            'ids':db.execute('SELECT COUNT(*) FROM pubmed_checkpoint_ids').fetchone()[0],
            'metadata':db.execute('SELECT COUNT(*) FROM source_retrievals WHERE source_name="pubmed"').fetchone()[0],
            'reported':db.execute('SELECT source_name,reported_matches,status '
                                  'FROM source_queries ORDER BY source_name').fetchall(),
            'events':db.execute('SELECT event_type,details_json FROM audit_events '
                                'ORDER BY event_id').fetchall(),
        }


class Supervisor:
    """Only lifecycle is doubled; source service and SQLite remain genuine."""

    def __init__(self):
        self.id=str(uuid4())
        self.cmd=None
        self.state='running'
        self.result=None
        self.error=None
        self.closed=False
        self.calls=0

    def submit(self,cmd):
        assert cmd.operation=='pubmed_identifier_run'
        assert self.cmd is None
        self.cmd=cmd
        self.calls+=1
        return self.id

    def poll(self,operation_id):
        assert operation_id==self.id
        return OperationStatus(operation_id,'pubmed_identifier_run',None,
                               self.state,self.error,
                               None if self.result is None else json.dumps(self.result))

    def close(self,*,grace_seconds=0,kill_seconds=2):
        self.closed=True


def test_no_profile_reads_existing_project_without_offering_provider_requests(tmp_path):
    project,flow,rid,qid,query=_flow(tmp_path,profile=False)
    try:
        before=_db(project)
        read=flow.inspect_stored_pubmed_source(qid)['pubmed_source']
        assert read['checkpoint'] is None
        assert read['no_network_requests'] is True
        assert read['source_retrieval_verified'] is False
        with pytest.raises(ProjectFlowError,match='pubmed_profile_unavailable'):
            flow.offer_pubmed_source(qid,coverage_start=START,coverage_end=END)
        assert _db(project)==before
    finally:
        flow.close()


def test_explicit_preview_no_transport_then_actual_bounded_identifier_reconciliation(
        tmp_path):
    project,flow,rid,qid,query=_flow(tmp_path)
    provider=Transport(query)
    supervisor=Supervisor()
    flow._pubmed_source_worker.close()
    flow._pubmed_source_worker=supervisor
    try:
        before=_db(project)
        preview=flow.offer_pubmed_source(
            qid,coverage_start=START,coverage_end=END)
        assert preview['pubmed_source_offer']['exact_query']==query
        assert preview['pubmed_source_offer']['coverage_start']==START
        assert preview['pubmed_source_offer']['max_session_requests']==512
        assert _db(project)==before and provider.calls==[]
        flow.dismiss_pubmed_source()
        with pytest.raises(ProjectFlowError,match='pubmed_session_confirmation_required'):
            flow.confirm_pubmed_source()
        flow.offer_pubmed_source(qid,coverage_start=START,coverage_end=END)
        launched=flow.confirm_pubmed_source()
        assert launched['pubmed_source_pending'] is True
        assert launched['pubmed_source_offer'] is None
        assert supervisor.calls==1 and provider.calls==[]
        assert supervisor.cmd.pubmed_source_plan_sha256
        assert supervisor.cmd.pubmed_source_contact_email==EMAIL
        assert supervisor.cmd.pubmed_source_api_key==KEY
        assert KEY not in repr(supervisor.cmd)
        assert KEY not in json.dumps(launched)
        with pytest.raises(ProjectFlowError,match='pubmed_source_reconciliation_required'):
            flow.select_run(rid)
        with pytest.raises(ProjectFlowError,match='pubmed_source_reconciliation_required'):
            flow.confirm_pubmed_source()
        assert flow.poll_pubmed_source()['pubmed_source_pending'] is True
        assert provider.calls==[]
        receipt=source.run_pubmed_source_session(
            project,run_id=rid,query_id=qid,
            expected_plan_sha256=supervisor.cmd.pubmed_source_plan_sha256,
            coverage_start=START,coverage_end=END,
            confirmed=True,client=_client(provider))
        assert receipt['status']=='identifiers_reconciled_metadata_pending'
        assert receipt['source_retrieval_verified'] is False
        assert receipt['whole_search_verified'] is False
        assert receipt['checkpoint']['identifiers_committed']==4
        assert receipt['checkpoint']['pages_committed']==1
        assert receipt['checkpoint']['reported_matches']==4
        assert receipt['checkpoint']['metadata_records_linked']==0
        assert KEY not in json.dumps(receipt)
        assert all(v not in json.dumps(receipt) for v in IDS)
        assert _db(project)['ids']==4 and _db(project)['metadata']==0
        supervisor.state='returned'
        supervisor.result=receipt
        done=flow.reconcile_pubmed_source()
        assert done['pubmed_source_pending'] is False
        assert done['pubmed_source_last_outcome']['requests_reserved']>0
        assert done['pubmed_source']['checkpoint']['identifiers_reconciled'] is True
        assert done['pubmed_source']['source_retrieval_verified'] is False
        assert done['report']['status']=='incomplete'
        assert KEY not in json.dumps(done)
    finally:
        flow.close()
    assert supervisor.closed


def test_invalid_coverage_and_tampered_source_plan_never_call_provider(tmp_path):
    project,flow,rid,qid,query=_flow(tmp_path)
    try:
        for start,end in (
            ('2026-11-05','2026-11-04'),
            ('2026-01-1','2026-11-04'),
            ('not-a-date','2026-11-04')):
            with pytest.raises(ProjectFlowError,match='pubmed_coverage_invalid'):
                flow.offer_pubmed_source(qid,coverage_start=start,coverage_end=end)
        with pytest.raises(ProjectFlowError,match='unknown_pubmed_query'):
            flow.offer_pubmed_source(str(uuid4()),
                                     coverage_start=START,coverage_end=END)
        flow.offer_pubmed_source(qid,coverage_start=START,coverage_end=END)
        with closing(sqlite3.connect(project.database_path)) as db,db:
            db.execute('UPDATE source_queries SET exact_query=? WHERE query_id=?',
                       ('("UNAPPROVED"[All Fields])',qid))
        with pytest.raises(ProjectFlowError,match='pubmed_plan_unverified'):
            flow.confirm_pubmed_source()
        assert _db(project)['pages']==0
    finally:
        flow.close()


def test_request_budget_exhaustion_keeps_root_count_but_no_fictional_ids(
        tmp_path,monkeypatch):
    project,rid,qid,query=_project(tmp_path)
    provider=Transport(query)
    plan=source.preview_pubmed_source(project,run_id=rid,query_id=qid)
    before=_db(project)
    original_reserve=_limit_synthetic_esearch_attempts(monkeypatch,limit=2)
    result=source.run_pubmed_source_session(
        project,run_id=rid,query_id=qid,
        expected_plan_sha256=plan['plan_sha256'],
        coverage_start=START,coverage_end=END,
        confirmed=True,client=_client(provider))
    assert result['status']=='incomplete'
    assert result['session_requests_reserved']==2
    assert result['checkpoint'] is not None
    assert result['checkpoint']['reported_matches']==4
    assert result['checkpoint']['identifiers_committed']==0
    assert result['checkpoint']['pages_committed']==0
    assert not result['checkpoint']['identifiers_reconciled']
    assert _db(project)['metadata']==0
    monkeypatch.setattr(source._BudgetedESearch,'_reserve',original_reserve)
    resumed=source.run_pubmed_source_session(
        project,run_id=rid,query_id=qid,
        expected_plan_sha256=plan['plan_sha256'],
        coverage_start=START,coverage_end=END,
        confirmed=True,client=_client(provider))
    assert resumed['status']=='identifiers_reconciled_metadata_pending'
    assert resumed['checkpoint']['identifiers_committed']==4
    assert resumed['checkpoint']['pages_committed']==1
    assert not resumed['source_retrieval_verified']


def test_missing_date_coverage_for_large_query_fails_closed_without_checkpoint(tmp_path):
    project,rid,qid,query=_project(tmp_path)
    provider=Transport(query,ids=(),root_count=9012,dated_count=0)
    plan=source.preview_pubmed_source(project,run_id=rid,query_id=qid)
    result=source.run_pubmed_source_session(
        project,run_id=rid,query_id=qid,
        expected_plan_sha256=plan['plan_sha256'],
        coverage_start='2026-11-04',coverage_end='2026-11-04',
        confirmed=True,client=_client(provider))
    assert result['status']=='incomplete'
    assert result['checkpoint'] is None
    assert result['session_requests_reserved']==2
    assert _db(project)['ids']==0 and _db(project)['pages']==0
    assert all(row[1] is None for row in _db(project)['reported'])


def test_pause_after_durable_plan_does_not_delete_inflight_committed_ids(tmp_path):
    project,rid,qid,query=_project(tmp_path)
    provider=Transport(query)
    snapshot=source.preview_pubmed_source(project,run_id=rid,query_id=qid)
    # No checkpoint plan is yet saved; falsely reporting pause would be unsafe.
    with pytest.raises(source.PubMedSourceError,match='pubmed_checkpoint_not_ready'):
        source.pause_pubmed_source_session(project,run_id=rid,query_id=qid)
    once={'sent':False}
    def pause_during_page():
        if once['sent']:
            return
        once['sent']=True
        observed=source.pause_pubmed_source_session(
            project,run_id=rid,query_id=qid)
        assert observed['checkpoint']['status']=='paused'
    provider.on_page=pause_during_page
    result=source.run_pubmed_source_session(
        project,run_id=rid,query_id=qid,
        expected_plan_sha256=snapshot['plan_sha256'],
        coverage_start=START,coverage_end=END,
        confirmed=True,client=_client(provider))
    assert result['checkpoint']['status']=='paused'
    assert result['checkpoint']['pages_committed']==1
    assert result['checkpoint']['identifiers_committed']==4
    provider.on_page=None
    resumed=source.run_pubmed_source_session(
        project,run_id=rid,query_id=qid,
        expected_plan_sha256=snapshot['plan_sha256'],
        coverage_start=START,coverage_end=END,
        confirmed=True,client=_client(provider))
    assert resumed['checkpoint']['status']=='identifiers_reconciled_metadata_pending'
    assert resumed['checkpoint']['pages_committed']==1
    assert len(provider.calls)>1


def test_stopped_worker_failure_never_promotes_source_completeness(tmp_path):
    project,flow,rid,qid,query=_flow(tmp_path)
    supervisor=Supervisor()
    flow._pubmed_source_worker.close()
    flow._pubmed_source_worker=supervisor
    try:
        flow.offer_pubmed_source(qid,coverage_start=START,coverage_end=END)
        flow.confirm_pubmed_source()
        supervisor.state='failed'
        supervisor.error='operation_failed'
        done=flow.reconcile_pubmed_source()
        assert done['pubmed_source_pending'] is False
        assert done['pubmed_source_last_outcome']['worker_state']=='failed'
        assert done['pubmed_source_last_outcome']['requests_reserved'] is None
        assert done['pubmed_source']['checkpoint'] is None
        assert done['pubmed_source']['source_retrieval_verified'] is False
        assert _db(project)['ids']==0
    finally:
        flow.close()


def test_read_only_reopen_after_identifier_retrieval_no_credentials(tmp_path):
    project,rid,qid,query=_project(tmp_path)
    plan=source.preview_pubmed_source(project,run_id=rid,query_id=qid)
    first=source.run_pubmed_source_session(
        project,run_id=rid,query_id=qid,
        expected_plan_sha256=plan['plan_sha256'],
        coverage_start=START,coverage_end=END,confirmed=True,
        client=_client(Transport(query)))
    assert first['checkpoint']['identifiers_reconciled']
    flow=RealProjectFlow(selected_root=project.root,selected_parent=tmp_path)
    try:
        flow.open_selected()
        flow.select_run(rid)
        restored=flow.inspect_stored_pubmed_source(qid)['pubmed_source']
        assert restored['checkpoint']['reported_matches']==4
        assert restored['checkpoint']['identifiers_committed']==4
        assert restored['checkpoint']['identifiers_reconciled']
        assert restored['checkpoint']['metadata_records_linked']==0
        assert restored['no_network_requests']
        assert flow.state()['pubmed_profile_configured'] is False
        assert all(key not in json.dumps(restored) for key in (KEY,EMAIL,*IDS))
    finally:
        flow.close()


def test_late_pause_after_reconciled_identifiers_is_atomic_noop_and_worker_reconciles(
        tmp_path):
    project,flow,rid,qid,query=_flow(tmp_path)
    supervisor=Supervisor()
    flow._pubmed_source_worker.close()
    flow._pubmed_source_worker=supervisor
    try:
        flow.offer_pubmed_source(qid,coverage_start=START,coverage_end=END)
        flow.confirm_pubmed_source()
        receipt=source.run_pubmed_source_session(
            project,run_id=rid,query_id=qid,
            expected_plan_sha256=supervisor.cmd.pubmed_source_plan_sha256,
            coverage_start=START,coverage_end=END,
            confirmed=True,client=_client(Transport(query)))
        assert receipt['checkpoint']['status']=='identifiers_reconciled_metadata_pending'
        before=_db(project)
        # The supervisor may still say running briefly after the original
        # child has committed a verified identifier checkpoint and returned.
        assert flow.state()['pubmed_source_worker_state']=='running'
        pause=flow.pause_pubmed_source()['pubmed_source']
        assert pause['checkpoint']['status']=='identifiers_reconciled_metadata_pending'
        assert _db(project)==before  # no downgraded state or spurious audit event
        supervisor.state='returned'
        supervisor.result=receipt
        done=flow.reconcile_pubmed_source()
        assert done['pubmed_source_pending'] is False
        assert done['pubmed_source']['checkpoint']==receipt['checkpoint']
        assert done['pubmed_source']['checkpoint']['identifiers_reconciled']
        assert done['source_retrieval_verified'] is False
        flow.select_run(rid)
    finally:
        flow.close()


def test_late_pause_of_incomplete_receipt_permits_only_status_change(
        tmp_path,monkeypatch):
    project,flow,rid,qid,query=_flow(tmp_path)
    supervisor=Supervisor()
    flow._pubmed_source_worker.close()
    flow._pubmed_source_worker=supervisor
    try:
        flow.offer_pubmed_source(qid,coverage_start=START,coverage_end=END)
        flow.confirm_pubmed_source()
        _limit_synthetic_esearch_attempts(monkeypatch,limit=2)
        receipt=source.run_pubmed_source_session(
            project,run_id=rid,query_id=qid,
            expected_plan_sha256=supervisor.cmd.pubmed_source_plan_sha256,
            coverage_start=START,coverage_end=END,
            confirmed=True,client=_client(Transport(query)))
        assert receipt['status']=='incomplete'
        assert receipt['checkpoint']['status']=='incomplete'
        paused=flow.pause_pubmed_source()['pubmed_source']
        assert paused['checkpoint']['status']=='paused'
        assert paused['checkpoint']['identifiers_committed']==0
        assert RealProjectFlow._pubmed_checkpoint_receipt_consistent(
            receipt['checkpoint'],paused['checkpoint'])
        forged=json.loads(json.dumps(receipt))
        forged['checkpoint']['reported_matches']=999
        assert not RealProjectFlow._pubmed_checkpoint_receipt_consistent(
            forged['checkpoint'],paused['checkpoint'])
        supervisor.result=forged
        supervisor.state='returned'
        with pytest.raises(ProjectFlowError,match='pubmed_receipt_invalid'):
            flow.reconcile_pubmed_source()
        assert flow.state()['pubmed_source_pending']
        supervisor.result=receipt
        done=flow.reconcile_pubmed_source()
        assert done['pubmed_source_pending'] is False
        assert done['pubmed_source']['checkpoint']['status']=='paused'
        assert done['pubmed_source_last_outcome']['source_retrieval_verified'] is False
    finally:
        flow.close()


def _historical_daily_partition_checkpoint(project,qid,query,days):
    """Valid historical CLI checkpoint with more leaves than the GUI planner."""
    from datetime import timedelta
    from research_y.pubmed_partition import (
        DateWindow, CountedPartition, PubMedPartitionResult)
    from research_y.pubmed_checkpoint_store import create_pubmed_checkpoint
    start=date(2025,1,1)
    window=DateWindow(start,start+timedelta(days=days-1))
    nodes=[]

    def split(interval,parent=None,depth=0):
        idx=len(nodes)
        count=(interval.end-interval.start).days+1
        decision='collect' if count==1 else 'split'
        nodes.append(CountedPartition(
            idx,parent,interval,interval.query_for(query),count,depth,
            decision,'Synthetic historically planned Create Date partition'))
        if decision=='split':
            left,right=interval.split()
            split(left,idx,depth+1)
            split(right,idx,depth+1)
    split(window)
    plan=PubMedPartitionResult(
        query,window,days,'incomplete',(),tuple(nodes),(),())
    create_pubmed_checkpoint(project,qid,plan,page_size=200)
    return window


def test_128_historical_leaf_counts_reconcile_with_extended_budget(tmp_path):
    project,rid,qid,query=_project(tmp_path)
    window=_historical_daily_partition_checkpoint(project,qid,query,128)
    source_preview=source.preview_pubmed_source(
        project,run_id=rid,query_id=qid)
    cp=source_preview['checkpoint']
    assert cp['partition_leaf_count']==128
    assert cp['minimum_resume_requests']==130
    assert cp['resume_budget_sufficient'] is True
    assert source_preview['max_session_requests']==512
    assert cp['coverage']=={
        'start':window.start.isoformat(),'end':window.end.isoformat()}
    counts=[]
    from datetime import timedelta
    import re
    def transport(req,timeout):
        assert req.get_method()=='POST'
        values=parse_qs(req.data.decode())
        term=values['term'][0]
        offset=int(values.get('retstart',['0'])[0])
        retmax=int(values['retmax'][0])
        if term==query:
            count=128
            ids=[str(1100000+i) for i in range(128)]
        else:
            pair=re.search(
                r'(\d{4})/(\d{2})/(\d{2}):(\d{4})/(\d{2})/(\d{2})',
                term)
            assert pair is not None
            y1,m1,d1,y2,m2,d2=map(int,pair.groups())
            first,last=date(y1,m1,d1),date(y2,m2,d2)
            count=(last-first).days+1
            ids=[str(1100000+(first-window.start).days+i)
                 for i in range(count)]
        counts.append((term,retmax))
        return json.dumps({'esearchresult':{
            'count':str(count),'retstart':str(offset),
            'retmax':str(retmax),
            'idlist':ids[offset:offset+retmax] if retmax else [],
            'querytranslation':term,
            'warninglist':{'outputmessages':[]},
            'errorlist':{'phrasesnotfound':[]},
        }}).encode()
    receipt=source.run_pubmed_source_session(
        project,run_id=rid,query_id=qid,
        expected_plan_sha256=source_preview['plan_sha256'],
        coverage_start=window.start.isoformat(),
        coverage_end=window.end.isoformat(),confirmed=True,
        client=_client(transport))
    assert receipt['status']=='identifiers_reconciled_metadata_pending'
    assert receipt['checkpoint']['identifiers_committed']==128
    assert receipt['checkpoint']['pages_committed']==128
    assert receipt['checkpoint']['identifiers_reconciled'] is True
    assert receipt['session_requests_reserved']==258
    assert len(counts)==258
    assert not receipt['source_retrieval_verified']
    assert _db(project)['ids']==128 and _db(project)['metadata']==0


def test_511_leaf_legacy_checkpoint_fails_before_any_provider_requests(tmp_path):
    project,rid,qid,query=_project(tmp_path)
    window=_historical_daily_partition_checkpoint(project,qid,query,511)
    source_preview=source.preview_pubmed_source(project,run_id=rid,query_id=qid)
    cp=source_preview['checkpoint']
    assert cp['partition_leaf_count']==511
    assert cp['minimum_resume_requests']==513
    assert cp['resume_budget_sufficient'] is False
    before=_db(project)
    provider=Transport(query,ids=(),root_count=511,dated_count=511)
    with pytest.raises(source.PubMedSourceError,
                       match='pubmed_verification_exceeds_budget'):
        source.run_pubmed_source_session(
            project,run_id=rid,query_id=qid,
            expected_plan_sha256=source_preview['plan_sha256'],
            coverage_start=window.start.isoformat(),
            coverage_end=window.end.isoformat(),confirmed=True,
            client=_client(provider))
    assert provider.calls==[]
    assert _db(project)==before
    flow=RealProjectFlow(
        selected_root=project.root,selected_parent=tmp_path,
        pubmed_profile=PubMedHostProfile(EMAIL,KEY))
    try:
        flow.open_selected()
        flow.select_run(rid)
        read=flow.inspect_stored_pubmed_source(qid)['pubmed_source']
        assert read['checkpoint']['minimum_resume_requests']==513
        assert read['checkpoint']['resume_budget_sufficient'] is False
        with pytest.raises(ProjectFlowError,match='pubmed_verification_exceeds_budget'):
            flow.offer_pubmed_source(
                qid,coverage_start=window.start.isoformat(),
                coverage_end=window.end.isoformat())
        assert flow.state()['pubmed_source_pending'] is False
        assert _db(project)==before
    finally:
        flow.close()


def test_graphical_pubmed_controls_never_exposed_on_probe_automation_route():
    text=inspect.getsource(run)
    for operation in ('pubmed_identifier_offer','pubmed_identifier_confirm',
                      'pubmed_identifier_pause','pubmed_identifier_poll',
                      'pubmed_identifier_reconcile'):
        assert "name == '"+operation+"'" in text
    for marker in ('pubmed-source-heading','pubmed-source-progress',
                   'pubmed-source-confirm','pubmed-source-poll'):
        assert 'data-testid='+marker in text
    assert "await act('pubmed_identifier_poll')" in text
    assert 'ui.html(' not in text
    route=text.split("@app.post('/_probe/start')")[1].split(
        "@app.post('/_probe/stop')")[0]
    assert 'pubmed_identifier' not in route
