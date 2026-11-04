"""P1-06i2 — bounded run-wide source staging, consent and stopped-worker safety.

All provider replies are synthetic. Original approved two-group OR plans, real
PubMed EFetch/XML and WoS checkpoint code, and transactional project SQLite
are exercised; only the transport and supervisor lifecycle are substituted.
"""
from contextlib import closing
import inspect
import json
import sqlite3
from urllib.error import URLError
from urllib.parse import parse_qs
from uuid import uuid4

import pytest

from test_run_execution_board import _project, _pubmed, _digest, _row, Clock, KEY, EMAIL
from research_y import run_source_coordinator as coordinator
from research_y import wos_acquisition_gui as wos_gui
from research_y.pubmed_metadata import PubMedEFetchClient
from research_y.pubmed_probe import PubMedESearchProbeClient
from research_y.wos_starter_client import WoSStarterClient, WoSHTTPResponse
from research_y.run_execution_board import read_run_execution_board
from research_y.application_worker import OperationStatus
from tools.gui_feasibility.real_project_flow import RealProjectFlow, ProjectFlowError
from tools.gui_feasibility.pubmed_host_profile import PubMedHostProfile
from tools.gui_feasibility.wos_host_profile import WoSHostProfile
from tools.gui_feasibility.real_project_app import run as gui_run


class PubMedTransport:
    def __init__(self, *, fail_at=None):
        self.calls = []
        self.fail_at = fail_at

    def __call__(self, req, timeout):
        assert req.full_url.endswith('/entrez/eutils/efetch.fcgi')
        assert req.get_method() == 'POST' and timeout == 15
        fields = parse_qs(req.data.decode())
        assert fields['db'] == ['pubmed'] and fields['retmode'] == ['xml']
        assert fields['email'] == [EMAIL] and fields['api_key'] == [KEY]
        pmids = tuple(fields['id'][0].split(','))
        assert 1 <= len(pmids) <= 20
        self.calls.append(pmids)
        if len(self.calls) == self.fail_at:
            raise URLError('PRIVATE-PROVIDER-ERROR-NEVER-ECHO')
        articles = ''.join(
            f'<PubmedArticle><MedlineCitation Status="MEDLINE">'
            f'<PMID>{pmid}</PMID><Article>'
            f'<ArticleTitle>PRIVATE SOURCE TITLE</ArticleTitle>'
            f'<Abstract><AbstractText>PRIVATE SOURCE ABSTRACT</AbstractText></Abstract>'
            f'</Article></MedlineCitation></PubmedArticle>' for pmid in pmids)
        return ('<?xml version="1.0"?><PubmedArticleSet>' +
                articles + '</PubmedArticleSet>').encode()


class WoSTransport:
    def __init__(self):
        self.calls = []
        self.clock = Clock()

    def __call__(self, req, timeout):
        assert timeout == 10 and req.get_method() == 'GET'
        assert req.get_header('X-apikey') == KEY
        fields = parse_qs(req.full_url.split('?', 1)[1])
        page, limit = int(fields['page'][0]), int(fields['limit'][0])
        assert fields['db'] == ['WOS']
        self.calls.append((page, limit))
        self.clock.sleep(2)
        body = json.dumps({
            'metadata': {'total':1, 'page':page, 'limit':limit},
            'hits':[{'uid':'WOS:000000001','title':'PRIVATE WOS TITLE'}]
        }).encode()
        return WoSHTTPResponse(200,{
            'X-RateLimit-Limit-Day':'5000',
            'X-RateLimit-Remaining-Day':str(4999-len(self.calls)),
        },body)


def inject_synthetic_clients(monkeypatch, pubmed, wos):
    """Return real client TYPES configured with purely synthetic transports."""
    real_esearch = PubMedESearchProbeClient
    real_efetch = PubMedEFetchClient
    real_wos = WoSStarterClient
    monkeypatch.setattr(coordinator, 'PubMedESearchProbeClient',
        lambda **kw: real_esearch(
            **kw,clock=lambda:10000.0,
            sleep=lambda seconds:None,
            transport=lambda request, timeout:b'NO-ESearch-HTTP'))
    monkeypatch.setattr(coordinator, 'PubMedEFetchClient',
        lambda esearch:real_efetch(esearch, transport=pubmed))
    monkeypatch.setattr(coordinator, 'WoSStarterClient',
        lambda **kw:real_wos(
            **kw,transport=wos,
            clock=wos.clock.monotonic,sleep=wos.clock.sleep,
            utc_now=wos.clock.now))


def prepared_two_sources(tmp_path):
    project, run_id, queries = _project(tmp_path)
    pubid, pubquery = queries['g-ecmo','pubmed']
    _pubmed(project,pubid,pubquery)
    wosid, wosquery = queries['g-ecmo','wos']
    preview=wos_gui.preview_wos_acquisition(
        project, run_id=run_id, query_id=wosid)
    prepared=wos_gui.prepare_wos_acquisition(
        project,run_id=run_id,query_id=wosid,
        expected_plan_sha256=preview['plan_sha256'],
        retention_authorized=True,confirmed=True)
    assert prepared['approved_gui_retention'] is True
    return project,run_id,queries


class Supervisor:
    def __init__(self):
        self.id=str(uuid4())
        self.command=None
        self.state='running'
        self.receipt=None
        self.error=None
        self.calls=0
        self.closed=False

    def submit(self,cmd):
        assert self.command is None
        assert cmd.operation == 'run_coord_run'
        self.command=cmd
        self.calls+=1
        return self.id

    def poll(self,operation_id):
        assert operation_id==self.id
        return OperationStatus(
            self.id,'run_coord_run',None,self.state,self.error,
            None if self.receipt is None else json.dumps(self.receipt))

    def close(self, *, grace_seconds=0, kill_seconds=2):
        self.closed=True


def test_unstarted_run_is_offline_and_every_unprepared_group_has_manual_gate(tmp_path):
    project,rid,queries=_project(tmp_path)
    before=_digest(project)
    preview=coordinator.preview_run_coordination(project,run_id=rid)
    assert preview['eligible_tasks']==[]
    assert len(preview['blocked_tasks'])==4
    assert set(x['blocker'] for x in preview['blocked_tasks'])=={
        'manual_pubmed_date_coverage_approval_required',
        'manual_wos_retention_consent_required'}
    assert preview['no_network_requests']
    assert preview['source_retrieval_verified'] is False
    assert _digest(project)==before


def test_prepared_two_source_jobs_execute_sequentially_with_exact_source_budgets(
        tmp_path, monkeypatch):
    p,rid,queries=prepared_two_sources(tmp_path)
    pubmed,wos = PubMedTransport(),WoSTransport()
    inject_synthetic_clients(monkeypatch,pubmed,wos)
    initial=_digest(p)
    plan=coordinator.preview_run_coordination(p,run_id=rid)
    assert _digest(p)==initial
    assert [(x['group_id'],x['source_name'],x['action']) for x in
            plan['eligible_tasks']]==[
                ('g-ecmo','pubmed','pubmed_metadata'),
                ('g-ecmo','wos','wos_acquire')]
    assert len(plan['blocked_tasks'])==2
    tasks=tuple(plan['eligible_tasks'])
    assert [x['max_requests'] for x in tasks]==[100,3]
    receipt=coordinator.run_coordinated_source_session(
        p,run_id=rid,expected_plan_sha256=plan['plan_sha256'],
        tasks=tasks,confirmed=True,wos_key=KEY,
        pubmed_email=EMAIL,pubmed_key=KEY)
    assert receipt['planned_step_count']==2
    assert receipt['dispatched_step_count']==2
    assert receipt['stopped_reason'] is None
    assert [x['requests_made'] for x in receipt['steps']]==[1,3]
    assert [x['action'] for x in receipt['steps']]==[
        'pubmed_metadata','wos_acquire']
    assert pubmed.calls==[('111','222')]
    assert wos.calls==[(1,50),(1,50),(1,1)]
    assert receipt['global_unique_publications'] is None
    assert receipt['source_retrieval_verified'] is False
    assert receipt['whole_search_verified'] is False
    assert receipt['no_automatic_retry']
    assert 'PRIVATE SOURCE' not in json.dumps(receipt)
    assert KEY not in json.dumps(receipt)
    board=read_run_execution_board(p,rid)
    assert _row(board,'g-ecmo','pubmed')['source_stage']=='pubmed_metadata_acquired'
    assert _row(board,'g-ecmo','wos')['source_stage']==(
        'wos_enumeration_reconciled_with_warnings')
    assert receipt['new_board_revision']==board['revision']
    assert board['verified_complete'] is False


def test_stale_run_evidence_and_forged_work_list_rejected_before_http(
        tmp_path, monkeypatch):
    p,rid,queries=prepared_two_sources(tmp_path)
    pubmed,wos=PubMedTransport(),WoSTransport()
    inject_synthetic_clients(monkeypatch,pubmed,wos)
    preview=coordinator.preview_run_coordination(p,run_id=rid)
    work=tuple(preview['eligible_tasks'])
    for kwargs in (
        {'expected_plan_sha256':'b'*64},
        {'confirmed':False},
        {'tasks':work*2},
        {'tasks':tuple(reversed(work))},
        {'tasks':(dict(work[0],max_requests=1),)},
        {'tasks':(dict(work[0],exact_query='"HIDDEN"[All Fields]'),)},
    ):
        value=dict(project=p,run_id=rid,
                   expected_plan_sha256=preview['plan_sha256'],
                   tasks=work,confirmed=True,wos_key=KEY,
                   pubmed_email=EMAIL,pubmed_key=KEY)
        value.update(kwargs)
        with pytest.raises(coordinator.RunCoordinationError):
            coordinator.run_coordinated_source_session(**value)
    assert not pubmed.calls and not wos.calls
    assert read_run_execution_board(p,rid)['query_count']==4


def test_incomplete_efetch_stops_before_any_second_provider_request(
        tmp_path,monkeypatch):
    p,rid,queries=_project(tmp_path)
    pubid,query=queries['g-ecmo','pubmed']
    ids=tuple(str(1000001+i) for i in range(25))
    _pubmed(p,pubid,query,pmids=ids)
    wosid,wquery=queries['g-ecmo','wos']
    preview=wos_gui.preview_wos_acquisition(p,run_id=rid,query_id=wosid)
    wos_gui.prepare_wos_acquisition(
        p,run_id=rid,query_id=wosid,
        expected_plan_sha256=preview['plan_sha256'],
        confirmed=True,retention_authorized=True)
    pubmed,wos=PubMedTransport(fail_at=2),WoSTransport()
    inject_synthetic_clients(monkeypatch,pubmed,wos)
    offer=coordinator.preview_run_coordination(p,run_id=rid)
    result=coordinator.run_coordinated_source_session(
        p,run_id=rid,expected_plan_sha256=offer['plan_sha256'],
        tasks=tuple(offer['eligible_tasks']),confirmed=True,
        wos_key=KEY,pubmed_email=EMAIL,pubmed_key=KEY)
    assert result['dispatched_step_count']==1
    assert result['steps'][0]['metadata_records_committed']==20
    assert result['steps'][0]['metadata_records_pending']==5
    assert result['steps'][0]['successful_batches']==1
    assert result['steps'][0]['requests_made'] is None
    assert result['stopped_reason']=='source_outcome_uncertain'
    assert len(pubmed.calls)==2 and not wos.calls
    assert read_run_execution_board(p,rid)['totals']['metadata_source_records']==20
    assert result['verified_complete'] is False
    assert 'PRIVATE-PROVIDER-ERROR' not in json.dumps(result)


def test_manual_efetch_changes_reject_stale_approved_run_before_provider(
        tmp_path,monkeypatch):
    p,rid,queries=prepared_two_sources(tmp_path)
    pubmed,wos=PubMedTransport(),WoSTransport()
    inject_synthetic_clients(monkeypatch,pubmed,wos)
    plan=coordinator.preview_run_coordination(p,run_id=rid)
    from test_run_execution_board import _efetch
    qid,_=queries['g-ecmo','pubmed']
    _efetch(p,qid)
    with pytest.raises(coordinator.RunCoordinationError,
                       match='run_coordination_stale'):
        coordinator.run_coordinated_source_session(
            p,run_id=rid,expected_plan_sha256=plan['plan_sha256'],
            tasks=tuple(plan['eligible_tasks']),confirmed=True,
            wos_key=KEY,pubmed_email=EMAIL,pubmed_key=KEY)
    assert not pubmed.calls and not wos.calls


def test_no_implicit_quota_revalidation_or_unconsented_wos_checkpoint(
        tmp_path,monkeypatch):
    p,rid,queries=_project(tmp_path)
    pubmed,wos=PubMedTransport(),WoSTransport()
    inject_synthetic_clients(monkeypatch,pubmed,wos)
    # The source has no independently authorised metadata retention plan.
    qid,query=queries['g-ecmo','wos']
    offer=coordinator.preview_run_coordination(p,run_id=rid)
    assert all(x['query_id']!=qid for x in offer['eligible_tasks'])
    assert any(x['query_id']==qid and
               x['blocker']=='manual_wos_retention_consent_required'
               for x in offer['blocked_tasks'])
    assert not wos.calls


def test_supervised_gui_confirms_two_tasks_once_and_reconciles_durable_ledger(
        tmp_path,monkeypatch):
    p,rid,queries=prepared_two_sources(tmp_path)
    pubmed,wos=PubMedTransport(),WoSTransport()
    inject_synthetic_clients(monkeypatch,pubmed,wos)
    flow=RealProjectFlow(selected_root=p.root,selected_parent=tmp_path,
        wos_profile=WoSHostProfile(KEY),
        pubmed_profile=PubMedHostProfile(EMAIL,KEY))
    flow.open_selected();flow.select_run(rid)
    worker=Supervisor()
    flow._coord_worker.close()
    flow._coord_worker=worker
    try:
        initial=_digest(p)
        offered=flow.offer_run_coordination()['run_coordination_offer']
        assert len(offered['tasks'])==2
        assert offered['max_external_requests']==103
        assert _digest(p)==initial and not pubmed.calls and not wos.calls
        flow.dismiss_run_coordination()
        with pytest.raises(ProjectFlowError,match='run_coordination_confirmation_required'):
            flow.confirm_run_coordination()
        flow.offer_run_coordination()
        started=flow.confirm_run_coordination()
        assert started['run_coordination_pending'] is True
        assert worker.calls==1
        assert worker.command.coord_pubmed_email==EMAIL
        assert worker.command.coord_wos_key==KEY
        assert KEY not in repr(worker.command)
        with pytest.raises(ProjectFlowError,match='run_coordination_reconciliation_required'):
            flow.select_run(rid)
        with pytest.raises(ProjectFlowError,match='run_coordination_reconciliation_required'):
            flow.confirm_pubmed_metadata()
        with pytest.raises(ProjectFlowError,match='run_coordination_reconciliation_required'):
            flow.confirm_run_coordination()
        progress=flow.poll_run_coordination()
        assert progress['run_coordination_worker_state']=='running'
        assert len(progress['run_execution_board']['queries'])==4
        assert not pubmed.calls and not wos.calls
        original=worker.command
        receipt=coordinator.run_coordinated_source_session(
            p,run_id=rid,
            expected_plan_sha256=original.coord_plan_sha256,
            tasks=original.coord_tasks,confirmed=True,
            wos_key=original.coord_wos_key,
            pubmed_email=original.coord_pubmed_email,
            pubmed_key=original.coord_pubmed_key)
        worker.state='returned'
        worker.receipt=receipt
        done=flow.reconcile_run_coordination()
        assert done['run_coordination_pending'] is False
        assert done['run_coordination_last_outcome']['dispatched_step_count']==2
        assert done['run_coordination_last_outcome']['whole_search_verified'] is False
        assert done['run_execution_board']['global_unique_publications'] is None
        assert done['report']['status']=='incomplete'
        assert len(pubmed.calls)==1 and len(wos.calls)==3
        assert KEY not in json.dumps(done)
    finally:
        flow.close()
    assert worker.closed


def test_ambiguous_worker_failure_never_gets_fabricated_requests_or_search_success(
        tmp_path):
    p,rid,queries=prepared_two_sources(tmp_path)
    flow=RealProjectFlow(selected_root=p.root,selected_parent=tmp_path,
        wos_profile=WoSHostProfile(KEY),
        pubmed_profile=PubMedHostProfile(EMAIL,KEY))
    flow.open_selected();flow.select_run(rid)
    worker=Supervisor()
    flow._coord_worker.close()
    flow._coord_worker=worker
    try:
        flow.offer_run_coordination()
        flow.confirm_run_coordination()
        worker.state='returned'
        worker.receipt=dict(method=coordinator.METHOD,run_id=rid,
                            planned_step_count=2,
                            dispatched_step_count=2,steps=[],
                            whole_search_verified=False)
        with pytest.raises(ProjectFlowError,match='run_coordination_receipt_invalid'):
            flow.reconcile_run_coordination()
        assert flow.state()['run_coordination_pending'] is True
        worker.state='interrupted'
        worker.error='worker_interrupted'
        worker.receipt=None
        done=flow.reconcile_run_coordination()
        outcome=done['run_coordination_last_outcome']
        assert outcome['worker_state']=='interrupted'
        assert outcome['dispatched_step_count'] is None
        assert outcome['stopped_reason']=='worker_interrupted_outcome_unknown'
        assert outcome['whole_search_verified'] is False
        assert done['run_coordination_pending'] is False
    finally:
        flow.close()


def test_missing_profile_is_not_silently_promoted_to_run_network_consent(tmp_path):
    p,rid,queries=prepared_two_sources(tmp_path)
    flow=RealProjectFlow(selected_root=p.root,selected_parent=tmp_path)
    flow.open_selected();flow.select_run(rid)
    try:
        offered=flow.offer_run_coordination()['run_coordination_offer']
        assert offered['tasks']==[]
        assert len(offered['unavailable'])==2
        with pytest.raises(ProjectFlowError,match='run_coordination_confirmation_required'):
            flow.confirm_run_coordination()
    finally:
        flow.close()


def test_probe_route_never_automatically_executes_or_retries_run_coordination():
    source=inspect.getsource(gui_run)
    for marker in ('run_coord_offer','run_coord_dismiss','run_coord_confirm',
                   'run_coord_poll','run_coord_reconcile'):
        assert "name == '"+marker+"'" in source
    for marker in ('run-coordination-offer','run-coordination-confirm',
                   'run-coordination-progress','run-coordination-reconcile'):
        assert 'data-testid='+marker in source
    assert "await act('run_coord_poll')" in source
    automated=source.split("@app.post('/_probe/start')")[1].split(
        "@app.post('/_probe/stop')")[0]
    assert "run_coord" not in automated
    assert "ui.html(" not in source
