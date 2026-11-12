"""P1-06f7: isolated Starter GUI consent, quota and audited read-only recovery.

All provider replies are synthetic. No live licensed request or user key is used.
Real project SQLite, preflight inspections and supervised worker reads are used.
"""
from contextlib import closing
import inspect
import json
import os
import sqlite3
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest

from research_y.projects import create_project
from research_y.storage import ApprovedTerm, StrategyGroup
from research_y.strategy_admission import commit_approved_strategy
from research_y.wos_starter_client import WoSStarterClient, WoSHTTPResponse
from research_y.wos_starter_pilot import (
    REQUEST_EVENT, OUTCOME_EVENT, WoSPilotError, probe_wos_starter_once,
)
from tools.gui_feasibility.wos_host_profile import WoSHostProfile, WoSHostProfileError
from tools.gui_feasibility.pubmed_host_profile import PubMedHostProfile
from tools.gui_feasibility.real_project_flow import RealProjectFlow, ProjectFlowError
from tools.gui_feasibility.real_project_app import run


KEY = 'SYNTHETIC-PRIVATE-STARTER-KEY'
LICENSED_TITLE = 'COPYRIGHTED-SYNTHETIC-TITLE-NEVER-PERSIST'
HEADERS = {
    'X-RateLimit-Limit-Day':'5000',
    'X-RateLimit-Remaining-Day':'4997',
    'X-RateLimit-Limit-Second':'2',
}


def _project(tmp_path):
    project = create_project(tmp_path, 'Starter GUI pilot fixture')
    admitted = commit_approved_strategy(
        project, request_id=str(uuid4()), theme='Right heart failure',
        groups=(StrategyGroup('g-right', 'Right ventricle', (
            ApprovedTerm('right ventricle', 'researcher', True),
            ApprovedTerm('right-ventricle', 'deterministic', True,
                         'Hyphenation alternative'))),),
        approved_by='Researcher', approval_confirmed=True)
    return project, admitted.run_id


def _flow(tmp_path, *, profile=True, pubmed=False):
    project, run_id = _project(tmp_path)
    flow = RealProjectFlow(
        selected_root=project.root, selected_parent=tmp_path,
        wos_profile=WoSHostProfile(KEY) if profile else None,
        pubmed_profile=(PubMedHostProfile('fixture@example.org') if pubmed else None))
    flow.open_selected()
    flow.select_run(run_id)
    report = flow.inspect_preflight()
    assert report['preflight_report']['run_id'] == run_id
    query = next(s for s in report['preflight_report']['sources']
                 if s['source_name']=='wos')['queries'][0]
    return project, flow, run_id, query


def _events(project):
    with closing(sqlite3.connect(project.database_path)) as db:
        rows = db.execute(
            'SELECT event_type,details_json FROM audit_events '
            'WHERE event_type IN (?,?) ORDER BY event_id',
            (REQUEST_EVENT,OUTCOME_EVENT)).fetchall()
    return [(event,json.loads(raw)) for event,raw in rows]


def _source_counts(project, run_id):
    with closing(sqlite3.connect(project.database_path)) as db:
        return db.execute(
            'SELECT source_name,status,reported_matches FROM source_queries '
            'WHERE run_id=? ORDER BY source_name',(run_id,)).fetchall()


def _transport(request, timeout, *, count=57, headers=None, trace=None,
               abrupt=False, fail=None):
    if trace is not None:
        trace.append(request.full_url)
    values = parse_qs(urlsplit(request.full_url).query)
    assert request.get_method()=='GET'
    assert urlsplit(request.full_url).netloc=='api.clarivate.com'
    assert urlsplit(request.full_url).path=='/apis/wos-starter/v1/documents'
    assert values['db']==['WOS']
    assert values['page']==['1'] and values['limit']==['1']
    assert values['sortField']==['LD+A']
    assert values['q'][0].startswith('TS=(')
    assert KEY not in request.full_url
    assert request.headers['X-apikey']==KEY
    if abrupt:
        raise KeyboardInterrupt('simulated process interruption')
    if fail=='network':
        raise URLError('offline fixture')
    if fail=='auth':
        return WoSHTTPResponse(403, headers or HEADERS, b'')
    return WoSHTTPResponse(200,headers or HEADERS,json.dumps({
        'metadata':{'total':count,'page':1,'limit':1},
        'hits':([{'uid':'WOS:000000000000029',
                  'title':LICENSED_TITLE,
                  'unknownLicensedField':'PRIVATE-LICENSED-FIELD'}]
                if count else []),
    }).encode('utf-8'))


def _inject(monkeypatch, flow, *, count=57, headers=None, trace=None,
            lost_reply=False, lost_read=False, abruptly=False, fail=None):
    """Only the network-capable operation is swapped; receipt read is real."""
    original = flow._operation
    calls = []
    errors = dict(lost_reply=lost_reply,lost_read=lost_read,
                  abruptly=abruptly)

    def call(name, **kw):
        if name=='wos_pilot_read' and errors['lost_read']:
            errors['lost_read']=False
            raise ProjectFlowError('worker_unavailable')
        if name!='wos_pilot_sample':
            return original(name,**kw)
        calls.append(kw['pilot_id'])
        assert kw['pilot_api_key']==KEY
        assert kw['pilot_confirmed'] is True
        assert type(kw['pilot_wos_revalidate_quota']) is bool
        try:
            client = WoSStarterClient(
                api_key=kw['pilot_api_key'], request_budget=1,
                clock=lambda:1000.0,sleep=lambda _:None,
                transport=lambda request,timeout:_transport(
                    request,timeout,count=count,headers=headers,trace=trace,
                    abrupt=errors['abruptly'],fail=fail))
            result = probe_wos_starter_once(
                flow.project,pilot_id=kw['pilot_id'],
                run_id=kw['run_id'],query_id=kw['pilot_query_id'],
                expected_plan_sha256=kw['pilot_plan_sha256'],
                confirmed=kw['pilot_confirmed'],
                revalidate_quota=kw['pilot_wos_revalidate_quota'],
                client=client)
        except KeyboardInterrupt:
            errors['abruptly']=False
            raise ProjectFlowError('worker_interrupted') from None
        except WoSPilotError as exc:
            raise ProjectFlowError(exc.code) from None
        if errors['lost_reply']:
            errors['lost_reply']=False
            raise ProjectFlowError('worker_interrupted')
        return result

    monkeypatch.setattr(flow,'_operation',call)
    return calls


def test_missing_host_profile_does_not_offer_network_or_write_receipt(tmp_path):
    project, flow, run_id, query = _flow(tmp_path,profile=False)
    try:
        assert flow.state()['wos_profile_configured'] is False
        with pytest.raises(ProjectFlowError,match='^wos_profile_unavailable$'):
            flow.offer_wos_pilot(query['query_id'])
        with pytest.raises(ProjectFlowError,match='^wos_profile_unavailable$'):
            flow.confirm_wos_pilot()
        assert flow.state()['wos_pilot_candidate'] is None
        assert _events(project)==[]
        assert all(row[2] is None for row in _source_counts(project,run_id))
    finally:
        flow.close()


@pytest.mark.parametrize('matches', [0, 99124])
def test_explicit_preview_and_confirm_do_not_persist_licensed_metadata(
        tmp_path,monkeypatch,matches):
    project,flow,run_id,query=_flow(tmp_path)
    before=_source_counts(project,run_id)
    trace=[]
    calls=_inject(monkeypatch,flow,count=matches,trace=trace)
    try:
        preview=flow.offer_wos_pilot(query['query_id'])
        candidate=preview['wos_pilot_candidate']
        assert candidate['exact_query']==query['exact_query']
        assert candidate['query_id']==query['query_id']
        assert candidate['revalidate_quota'] is False
        assert _events(project)==[] and trace==[]
        assert KEY not in json.dumps(preview)
        done=flow.confirm_wos_pilot()
        assert done['wos_pilot_reconciliation_required'] is False
        assert done['wos_pilot_candidate'] is None
        report=done['last_wos_pilot']
        assert report['status']=='count_reported_sample_not_retained'
        assert report['reported_matches']==matches
        assert report['source']=='wos'
        assert report['sample_only'] is True
        assert report['count_only'] is False
        assert report['bibliographic_records_persisted']==0
        assert report['translation_status']=='not_exposed_by_starter_contract'
        assert report['accepted_translation'] is None
        assert report['quota']['daily_limit']==5000
        assert report['quota']['daily_remaining']==4997
        assert report['source_retrieval_verified'] is False
        assert report['retrieval_verified'] is False
        assert report['execution_authorized'] is False
        assert report['search_completed'] is False
        assert report['automatically_retryable'] is False
        assert len(calls)==len(trace)==1
        assert [event for event,_ in _events(project)]==[
            REQUEST_EVENT,OUTCOME_EVENT]
        for record in _events(project):
            serialized=json.dumps(record)
            assert KEY not in serialized
            assert LICENSED_TITLE not in serialized
            assert 'PRIVATE-LICENSED-FIELD' not in serialized
        assert KEY not in json.dumps(done)
        assert LICENSED_TITLE not in json.dumps(done)
        assert _source_counts(project,run_id)==before
        assert done['selected_run_id']==run_id
        with pytest.raises(ProjectFlowError,match='^pilot_confirmation_required$'):
            flow.confirm_wos_pilot()
    finally:
        flow.close()


def test_cancellation_invalid_selection_and_wrong_source_are_inert(tmp_path):
    project,flow,run_id,query=_flow(tmp_path)
    try:
        with pytest.raises(ProjectFlowError,match='^unknown_wos_query$'):
            flow.offer_wos_pilot(str(uuid4()))
        pubmed=next(s for s in flow.state()['preflight_report']['sources']
                    if s['source_name']=='pubmed')['queries'][0]
        with pytest.raises(ProjectFlowError,match='^unknown_wos_query$'):
            flow.offer_wos_pilot(pubmed['query_id'])
        with pytest.raises(ProjectFlowError,match='^pilot_confirmation_required$'):
            flow.offer_wos_pilot(query['query_id'],revalidate_quota=1)
        offered=flow.offer_wos_pilot(query['query_id'])
        assert offered['wos_pilot_candidate'] is not None
        cancelled=flow.revise_wos_pilot()
        assert cancelled['wos_pilot_candidate'] is None
        with pytest.raises(ProjectFlowError,match='^pilot_confirmation_required$'):
            flow.confirm_wos_pilot()
        assert _events(project)==[]
    finally:
        flow.close()


def test_lost_result_uses_exact_receipt_without_reissuing_provider_request(
        tmp_path,monkeypatch):
    project,flow,run_id,query=_flow(tmp_path)
    trace=[]
    calls=_inject(monkeypatch,flow,trace=trace,lost_reply=True)
    try:
        flow.offer_wos_pilot(query['query_id'])
        original=flow.state()['wos_pilot_candidate']['pilot_id']
        with pytest.raises(ProjectFlowError,match='^worker_interrupted$'):
            flow.confirm_wos_pilot()
        assert flow.state()['wos_pilot_reconciliation_required']
        with pytest.raises(ProjectFlowError,match='^pilot_reconciliation_required$'):
            flow.open_selected()
        with pytest.raises(ProjectFlowError,match='^pilot_reconciliation_required$'):
            flow.select_run(run_id)
        with pytest.raises(ProjectFlowError,match='^pilot_reconciliation_required$'):
            flow.confirm_wos_pilot()
        recovered=flow.reconcile_wos_pilot()
        assert recovered['last_wos_pilot']['pilot_id']==original
        assert recovered['last_wos_pilot']['reported_matches']==57
        assert recovered['wos_pilot_reconciliation_required'] is False
        assert calls==[original] and len(trace)==1
        assert len(_events(project))==2
    finally:
        flow.close()


def test_failed_journal_read_keeps_original_uuid_locked(tmp_path,monkeypatch):
    project,flow,run_id,query=_flow(tmp_path)
    calls=_inject(monkeypatch,flow,lost_read=True)
    try:
        flow.offer_wos_pilot(query['query_id'])
        with pytest.raises(ProjectFlowError,match='^worker_unavailable$'):
            flow.confirm_wos_pilot()
        assert flow.state()['wos_pilot_reconciliation_required']
        recovered=flow.reconcile_wos_pilot()
        assert recovered['last_wos_pilot']['reported_matches']==57
        assert len(calls)==1
    finally:
        flow.close()


def test_abrupt_request_without_outcome_is_not_retried_or_discarded(
        tmp_path,monkeypatch):
    from research_y import wos_starter_pilot, wos_checkpoint_store
    monkeypatch.setattr(wos_starter_pilot,'MIN_REQUEST_INTERVAL',0.0)
    monkeypatch.setattr(wos_checkpoint_store,'MIN_REQUEST_INTERVAL',0.0)
    project,flow,run_id,query=_flow(tmp_path)
    trace=[]
    calls=_inject(monkeypatch,flow,trace=trace,abruptly=True)
    try:
        flow.offer_wos_pilot(query['query_id'])
        first=flow.state()['wos_pilot_candidate']['pilot_id']
        with pytest.raises(ProjectFlowError,match='^worker_interrupted$'):
            flow.confirm_wos_pilot()
        assert [kind for kind,_ in _events(project)]==[REQUEST_EVENT]
        recovered=flow.reconcile_wos_pilot()
        assert recovered['last_wos_pilot']['status']=='requested_indeterminate'
        assert recovered['last_wos_pilot']['reported_matches'] is None
        assert recovered['last_wos_pilot']['automatically_retryable'] is False
        assert len(trace)==1 and calls==[first]
        flow.offer_wos_pilot(query['query_id'])
        second=flow.state()['wos_pilot_candidate']['pilot_id']
        assert first!=second
        with pytest.raises(ProjectFlowError,match='^provider_pilot_outcome_unknown$'):
            flow.confirm_wos_pilot()
        no_send=flow.reconcile_wos_pilot()
        assert no_send['last_wos_pilot']['status']=='not_recorded'
        assert len(trace)==1
    finally:
        flow.close()


def test_invalidated_stored_query_fails_before_request_and_can_be_reconciled(
        tmp_path,monkeypatch):
    project,flow,run_id,query=_flow(tmp_path)
    trace=[]
    _inject(monkeypatch,flow,trace=trace)
    try:
        flow.offer_wos_pilot(query['query_id'])
        with closing(sqlite3.connect(project.database_path)) as db,db:
            db.execute('UPDATE source_queries SET exact_query=? WHERE query_id=?',
                       ('TS=("unauthorised and different")',query['query_id']))
        with pytest.raises(ProjectFlowError,match='^pilot_plan_invalid$'):
            flow.confirm_wos_pilot()
        assert trace==[] and _events(project)==[]
        result=flow.reconcile_wos_pilot()
        assert result['last_wos_pilot']['status']=='not_recorded'
    finally:
        flow.close()


def test_trial_quota_is_not_labelled_institutional(tmp_path,monkeypatch):
    project,flow,run_id,query=_flow(tmp_path)
    headers=dict(HEADERS,**{'X-RateLimit-Limit-Day':'50',
                             'X-RateLimit-Remaining-Day':'49'})
    _inject(monkeypatch,flow,headers=headers)
    try:
        flow.offer_wos_pilot(query['query_id'])
        report=flow.confirm_wos_pilot()['last_wos_pilot']
        assert report['status']=='entitlement_unverified'
        assert report['quota']['daily_limit']==50
        assert report['quota_status']=='below_required_institutional_allowance'
    finally:
        flow.close()


def test_explicit_quota_revalidation_still_requires_two_steps(tmp_path,monkeypatch):
    from research_y import wos_starter_pilot, wos_checkpoint_store
    monkeypatch.setattr(wos_starter_pilot,'MIN_REQUEST_INTERVAL',0.0)
    monkeypatch.setattr(wos_checkpoint_store,'MIN_REQUEST_INTERVAL',0.0)
    project,flow,run_id,query=_flow(tmp_path)
    trace=[]
    exhausted={**HEADERS,'X-RateLimit-Remaining-Day':'0'}
    _inject(monkeypatch,flow,headers=exhausted,trace=trace)
    try:
        flow.offer_wos_pilot(query['query_id'])
        exhausted_report=flow.confirm_wos_pilot()['last_wos_pilot']
        assert exhausted_report['status']=='quota_exhausted_after_probe'
        flow.offer_wos_pilot(query['query_id'])
        with pytest.raises(ProjectFlowError,match='^provider_quota_revalidation_required$'):
            flow.confirm_wos_pilot()
        assert flow.reconcile_wos_pilot()['last_wos_pilot']['status']=='not_recorded'
        assert len(trace)==1
        flow.offer_wos_pilot(query['query_id'],revalidate_quota=True)
        candidate=flow.state()['wos_pilot_candidate']
        assert candidate['revalidate_quota'] is True
        flow.revise_wos_pilot()
        assert len(trace)==1
        flow.offer_wos_pilot(query['query_id'],revalidate_quota=True)
        # Same already-observed exhausted provider headers are deliberately
        # reported as exhausted, not fabricated as quota recovery.
        renewed=flow.confirm_wos_pilot()['last_wos_pilot']
        assert renewed['revalidate_quota'] is True
        assert renewed['status']=='quota_exhausted_after_probe'
        assert len(trace)==2
    finally:
        flow.close()


def test_wos_and_pubmed_have_mutually_exclusive_pending_receipts(
        tmp_path,monkeypatch):
    project,flow,run_id,query=_flow(tmp_path,pubmed=True)
    _inject(monkeypatch,flow,lost_reply=True)
    try:
        flow.offer_wos_pilot(query['query_id'])
        with pytest.raises(ProjectFlowError,match='^worker_interrupted$'):
            flow.confirm_wos_pilot()
        pubmed=next(s for s in flow.state()['preflight_report']['sources']
                    if s['source_name']=='pubmed')['queries'][0]
        with pytest.raises(ProjectFlowError,match='^pilot_reconciliation_required$'):
            flow.offer_pubmed_pilot(pubmed['query_id'])
        with pytest.raises(ProjectFlowError,match='^pilot_reconciliation_required$'):
            flow.confirm_pubmed_pilot()
        flow.reconcile_wos_pilot()
        candidate=flow.offer_pubmed_pilot(pubmed['query_id'])
        assert candidate['wos_pilot_candidate'] is None
    finally:
        flow.close()


def test_profile_consumes_only_trusted_environment_and_never_echoes(monkeypatch):
    monkeypatch.setenv('RESEARCHY_GUI_WOS_API_KEY',KEY)
    profile=WoSHostProfile.from_prototype_environment()
    assert profile.api_key==KEY
    assert 'RESEARCHY_GUI_WOS_API_KEY' not in os.environ
    assert KEY not in repr(profile)
    assert WoSHostProfile.from_prototype_environment() is None
    monkeypatch.setenv('RESEARCHY_GUI_WOS_API_KEY','')
    with pytest.raises(WoSHostProfileError,match='^wos_profile_invalid$'):
        WoSHostProfile.from_prototype_environment()
    assert 'RESEARCHY_GUI_WOS_API_KEY' not in os.environ
    for unsafe in (None,'',KEY+'\nsecret',KEY+chr(0),'K'*4097,23):
        with pytest.raises(WoSHostProfileError,match='^wos_profile_invalid$'):
            WoSHostProfile(unsafe)


def test_wos_gui_network_action_not_available_on_automated_probe_route():
    from desktop_source import project_ui_source
    source = project_ui_source()
    assert "name == 'wos_pilot_offer'" in source
    assert "name == 'wos_pilot_confirm'" in source
    assert "name == 'wos_pilot_reconcile'" in source
    assert "name == 'wos_pilot_revalidation_offer'" in source
    assert 'flow.confirm_wos_pilot()' in source
    for marker in ('wos-pilot-offer','wos-pilot-confirm',
                   'wos-pilot-reconcile','wos-profile-unavailable'):
        assert "data-testid="+marker in source
    assert "ui.html(" not in source
    block=source.split("@app.post('/_probe/start')")[1].split(
        "@app.post('/_probe/stop')")[0]
    assert 'wos_pilot' not in block
