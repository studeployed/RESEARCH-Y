"""P1-06f5: explicit, reversible pilot GUI consent and read-only recovery.

The host profile and authenticated run selection are real; the PubMed HTTP
response is synthetic. All preflight and journal observation operations
are run through the ordinary supervised Python worker. No actual HTTP calls.
"""
from contextlib import closing
import inspect
import json
import os
import sqlite3
from urllib.parse import parse_qs
from uuid import uuid4

import pytest

from research_y.projects import create_project
from research_y.pubmed_probe import PubMedESearchProbeClient
from research_y.pubmed_pilot import (
    REQUEST_EVENT, OUTCOME_EVENT, PubMedPilotError, probe_pubmed_count_once,
)
from research_y.storage import ApprovedTerm, StrategyGroup
from research_y.strategy_admission import commit_approved_strategy
from tools.gui_feasibility.pubmed_host_profile import (
    PubMedHostProfile, PubMedHostProfileError,
)
from tools.gui_feasibility.real_project_flow import RealProjectFlow, ProjectFlowError
from tools.gui_feasibility.real_project_app import run


KEY = 'fixture-PRIVATE-PUBMED-API-KEY-12345'
EMAIL = 'fixture.private@example.org'


def _project(tmp_path):
    p = create_project(tmp_path, 'Pilot GUI specimen')
    admitted = commit_approved_strategy(
        p, request_id=str(uuid4()), theme='Right ventricle',
        approved_by='Researcher', approval_confirmed=True,
        groups=(StrategyGroup('g-heart', 'Right ventricle', (
            ApprovedTerm('right ventricle', 'researcher', True),
            ApprovedTerm('right-ventricle', 'deterministic', True,
                         'Hyphenation alternative'),
        )),),
    )
    return p, admitted.run_id


def _flow(tmp_path, *, profile=True):
    project, run_id = _project(tmp_path)
    config = PubMedHostProfile(EMAIL, KEY) if profile else None
    flow = RealProjectFlow(selected_root=project.root, selected_parent=tmp_path,
                           pubmed_profile=config)
    flow.open_selected()
    flow.select_run(run_id)
    selected = flow.inspect_preflight()
    assert selected['preflight_report']['run_id'] == run_id
    source = next(s for s in selected['preflight_report']['sources']
                  if s['source_name'] == 'pubmed')
    query = source['queries'][0]
    return project, flow, run_id, query


def _events(project):
    with closing(sqlite3.connect(project.database_path)) as db:
        rows = db.execute(
            'SELECT event_type,details_json FROM audit_events '
            'WHERE event_type IN (?,?) ORDER BY event_id',
            (REQUEST_EVENT, OUTCOME_EVENT)).fetchall()
    return [(event,json.loads(raw)) for event,raw in rows]


def _queries(project, run_id):
    with closing(sqlite3.connect(project.database_path)) as db:
        return db.execute(
            'SELECT source_name,status,reported_matches FROM source_queries '
            'WHERE run_id=? ORDER BY source_name', (run_id,)).fetchall()


def _synthetic_transport(request, timeout, *, count=57, trace=None, abrupt=False):
    if trace is not None:
        trace.append(request.full_url)
    assert request.full_url.startswith(
        'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi')
    assert request.get_method() == 'POST'
    values = parse_qs(request.data.decode('utf-8'))
    assert values['db'] == ['pubmed']
    assert values['retmax'] == ['0']
    assert values['retmode'] == ['json']
    assert values['api_key'] == [KEY]
    assert values['email'] == [EMAIL]
    if abrupt:
        raise KeyboardInterrupt('synthetic interrupted worker')
    return json.dumps({'esearchresult': {
        'count': str(count), 'retstart': '0', 'retmax': '0',
        'idlist': [], 'querytranslation': values['term'][0],
        'warninglist': {'outputmessages': []},
        'errorlist': {'phrasesnotfound': []},
    }}).encode('utf-8')


def _inject_count_only_transport(monkeypatch, flow, *, trace=None,
                                 response_lost=False, first_abrupt=False,
                                 read_lost=False, count=57):
    """Swap *only* count invocation; all inspect calls use the real worker."""
    original = flow._operation
    count_calls = []
    failures = {'response': response_lost,
                'read': read_lost,
                'abrupt': first_abrupt}

    def call(name, **kwargs):
        if name == 'pubmed_pilot_read' and failures['read']:
            failures['read'] = False
            raise ProjectFlowError('worker_unavailable')
        if name != 'pubmed_pilot_count':
            return original(name, **kwargs)
        count_calls.append(kwargs['pilot_id'])
        assert kwargs['pilot_contact_email'] == EMAIL
        assert kwargs['pilot_api_key'] == KEY
        assert kwargs['pilot_confirmed'] is True
        try:
            client = PubMedESearchProbeClient(
                email=kwargs['pilot_contact_email'],
                api_key=kwargs['pilot_api_key'],
                transport=lambda request,timeout: _synthetic_transport(
                    request,timeout,count=count,trace=trace,
                    abrupt=failures['abrupt']),
            )
            result=probe_pubmed_count_once(
                flow.project, pilot_id=kwargs['pilot_id'],
                run_id=kwargs['run_id'], query_id=kwargs['pilot_query_id'],
                expected_plan_sha256=kwargs['pilot_plan_sha256'],
                confirmed=True, client=client)
        except KeyboardInterrupt:
            failures['abrupt'] = False
            raise ProjectFlowError('worker_interrupted') from None
        except PubMedPilotError as exc:
            raise ProjectFlowError(exc.code) from None
        if failures['response']:
            failures['response'] = False
            raise ProjectFlowError('worker_interrupted')
        return result

    monkeypatch.setattr(flow,'_operation',call)
    return count_calls


def test_no_profile_does_not_expose_network_control_or_send_a_request(tmp_path):
    project,flow,run_id,query=_flow(tmp_path,profile=False)
    try:
        assert flow.state()['pubmed_profile_configured'] is False
        with pytest.raises(ProjectFlowError,match='^pubmed_profile_unavailable$'):
            flow.offer_pubmed_pilot(query['query_id'])
        with pytest.raises(ProjectFlowError,match='^pubmed_profile_unavailable$'):
            flow.confirm_pubmed_pilot()
        assert flow.state()['pubmed_pilot_candidate'] is None
        assert _events(project)==[]
        assert all(row[2] is None for row in _queries(project,run_id))
    finally:
        flow.close()


def test_explicit_two_step_gui_pilot_is_audited_and_never_mutates_run_counts(tmp_path,monkeypatch):
    project,flow,run_id,query=_flow(tmp_path)
    trace=[]
    calls=_inject_count_only_transport(monkeypatch,flow,trace=trace,count=49126)
    try:
        before=_queries(project,run_id)
        preflight=flow.state()['preflight_report']
        state=flow.offer_pubmed_pilot(query['query_id'])
        candidate=state['pubmed_pilot_candidate']
        assert candidate['exact_query']==query['exact_query']
        assert candidate['query_id']==query['query_id']
        assert candidate['plan_sha256']==preflight['plan_sha256']
        assert len(_events(project))==0 and trace==[]
        public=json.dumps(state)
        assert KEY not in public and EMAIL not in public
        assert 'PRIVATE-PUBMED' not in repr(flow._pubmed_profile)
        done=flow.confirm_pubmed_pilot()
        assert done['pubmed_pilot_reconciliation_required'] is False
        assert done['pubmed_pilot_candidate'] is None
        report=done['last_pubmed_pilot']
        assert report['status']=='count_reported_not_retrieved'
        assert report['reported_matches']==49126
        assert report['count_only'] is True
        assert report['retrieval_verified'] is False
        assert report['source_retrieval_verified'] is False
        assert report['execution_authorized'] is False
        assert report['search_completed'] is False
        assert report['automatically_retryable'] is False
        assert len(calls)==1 and len(trace)==1
        assert [event for event,_ in _events(project)]==[
            REQUEST_EVENT,OUTCOME_EVENT]
        assert all(KEY not in json.dumps(row) and EMAIL not in json.dumps(row)
                   for row in _events(project))
        assert KEY not in json.dumps(done) and EMAIL not in json.dumps(done)
        assert done['selected_run_id']==run_id
        assert done['report']==flow.state()['report']
        assert _queries(project,run_id)==before
        with pytest.raises(ProjectFlowError,match='^pilot_confirmation_required$'):
            flow.confirm_pubmed_pilot()
    finally:
        flow.close()


def test_offer_requires_approved_current_pubmed_query_and_cancellation_is_inert(tmp_path):
    project,flow,run_id,query=_flow(tmp_path)
    try:
        with pytest.raises(ProjectFlowError,match='^unknown_pubmed_query$'):
            flow.offer_pubmed_pilot(str(uuid4()))
        sources=flow.state()['preflight_report']['sources']
        wos=next(s for s in sources if s['source_name']=='wos')
        with pytest.raises(ProjectFlowError,match='^unknown_pubmed_query$'):
            flow.offer_pubmed_pilot(wos['queries'][0]['query_id'])
        offered=flow.offer_pubmed_pilot(query['query_id'])
        assert offered['pubmed_pilot_candidate']['pilot_id']
        cancelled=flow.revise_pubmed_pilot()
        assert cancelled['pubmed_pilot_candidate'] is None
        with pytest.raises(ProjectFlowError,match='^pilot_confirmation_required$'):
            flow.confirm_pubmed_pilot()
        assert _events(project)==[]
    finally:
        flow.close()


def test_lost_worker_response_is_read_only_reconciled_by_original_uuid(tmp_path,monkeypatch):
    project,flow,run_id,query=_flow(tmp_path)
    trace=[]
    calls=_inject_count_only_transport(monkeypatch,flow,trace=trace,response_lost=True)
    try:
        flow.offer_pubmed_pilot(query['query_id'])
        with pytest.raises(ProjectFlowError,match='^worker_interrupted$'):
            flow.confirm_pubmed_pilot()
        assert flow.state()['pubmed_pilot_reconciliation_required'] is True
        original_id=flow.state()['pubmed_pilot_candidate']['pilot_id']
        with pytest.raises(ProjectFlowError,match='^pilot_reconciliation_required$'):
            flow.confirm_pubmed_pilot()
        with pytest.raises(ProjectFlowError,match='^pilot_reconciliation_required$'):
            flow.select_run(run_id)
        with pytest.raises(ProjectFlowError,match='^pilot_reconciliation_required$'):
            flow.open_selected()
        assert len(_events(project))==2
        recovered=flow.reconcile_pubmed_pilot()
        assert recovered['last_pubmed_pilot']['pilot_id']==original_id
        assert recovered['last_pubmed_pilot']['reported_matches']==57
        assert recovered['pubmed_pilot_reconciliation_required'] is False
        assert calls==[original_id]
        assert len(trace)==1 and len(_events(project))==2
    finally:
        flow.close()


def test_post_commit_read_failure_does_not_resend_query(tmp_path,monkeypatch):
    project,flow,run_id,query=_flow(tmp_path)
    trace=[]
    calls=_inject_count_only_transport(monkeypatch,flow,trace=trace,read_lost=True)
    try:
        flow.offer_pubmed_pilot(query['query_id'])
        with pytest.raises(ProjectFlowError,match='^worker_unavailable$'):
            flow.confirm_pubmed_pilot()
        assert flow.state()['pubmed_pilot_reconciliation_required']
        after=flow.reconcile_pubmed_pilot()
        assert after['last_pubmed_pilot']['reported_matches']==57
        assert len(trace)==1 and len(calls)==1
    finally:
        flow.close()


def test_crash_after_request_is_indeterminate_and_new_attempt_needs_fresh_consent(tmp_path,monkeypatch):
    project,flow,run_id,query=_flow(tmp_path)
    trace=[]
    calls=_inject_count_only_transport(monkeypatch,flow,trace=trace,
                                       first_abrupt=True)
    try:
        flow.offer_pubmed_pilot(query['query_id'])
        first=flow.state()['pubmed_pilot_candidate']['pilot_id']
        with pytest.raises(ProjectFlowError,match='^worker_interrupted$'):
            flow.confirm_pubmed_pilot()
        assert [kind for kind,_ in _events(project)]==[REQUEST_EVENT]
        assert flow.state()['pubmed_pilot_reconciliation_required'] is True
        observed=flow.reconcile_pubmed_pilot()
        assert observed['last_pubmed_pilot']['status']=='requested_indeterminate'
        assert observed['last_pubmed_pilot']['reported_matches'] is None
        assert observed['last_pubmed_pilot']['automatically_retryable'] is False
        assert trace==['https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi']
        assert calls==[first]
        with pytest.raises(ProjectFlowError,match='^pilot_confirmation_required$'):
            flow.confirm_pubmed_pilot()
        # It is possible to start another separate attempt only after the
        # user reselects the query and approves that next network request.
        flow.offer_pubmed_pilot(query['query_id'])
        second=flow.state()['pubmed_pilot_candidate']['pilot_id']
        assert first!=second and len(trace)==1
        next_result=flow.confirm_pubmed_pilot()
        assert next_result['last_pubmed_pilot']['pilot_id']==second
        assert len(trace)==2 and calls==[first,second]
        assert [kind for kind,_ in _events(project)]==[
            REQUEST_EVENT,REQUEST_EVENT,OUTCOME_EVENT]
    finally:
        flow.close()


def test_invalidated_source_plan_fails_before_network_and_can_be_reconciled(tmp_path,monkeypatch):
    project,flow,run_id,query=_flow(tmp_path)
    trace=[]
    _inject_count_only_transport(monkeypatch,flow,trace=trace)
    try:
        flow.offer_pubmed_pilot(query['query_id'])
        with closing(sqlite3.connect(project.database_path)) as db,db:
            db.execute('UPDATE source_queries SET exact_query=? WHERE query_id=?',
                       ('"wrong"[Title]',query['query_id']))
        with pytest.raises(ProjectFlowError,match='^pilot_plan_invalid$'):
            flow.confirm_pubmed_pilot()
        assert trace==[] and _events(project)==[]
        result=flow.reconcile_pubmed_pilot()
        assert result['last_pubmed_pilot']['status']=='not_recorded'
        assert result['last_pubmed_pilot']['reported_matches'] is None
    finally:
        flow.close()


def test_profile_comes_from_trusted_environment_and_is_never_serialized(monkeypatch):
    monkeypatch.setenv('RESEARCHY_GUI_PUBMED_CONTACT_EMAIL',EMAIL)
    monkeypatch.setenv('RESEARCHY_GUI_PUBMED_API_KEY',KEY)
    profile=PubMedHostProfile.from_prototype_environment()
    assert profile.contact_email==EMAIL and profile.api_key==KEY
    assert 'RESEARCHY_GUI_PUBMED_CONTACT_EMAIL' not in os.environ
    assert 'RESEARCHY_GUI_PUBMED_API_KEY' not in os.environ
    assert KEY not in repr(profile) and EMAIL not in repr(profile)
    assert PubMedHostProfile.from_prototype_environment() is None
    monkeypatch.setenv('RESEARCHY_GUI_PUBMED_API_KEY',KEY)
    with pytest.raises(PubMedHostProfileError,match='^pubmed_profile_invalid$'):
        PubMedHostProfile.from_prototype_environment()
    assert 'RESEARCHY_GUI_PUBMED_API_KEY' not in os.environ


def test_profile_rejects_control_characters_and_never_logs_secrets():
    with pytest.raises(PubMedHostProfileError,match='pubmed_profile_invalid'):
        PubMedHostProfile('contact@example.org'+chr(0),KEY)
    with pytest.raises(PubMedHostProfileError,match='pubmed_profile_invalid'):
        PubMedHostProfile(EMAIL,'unsafe'+chr(10)+'value')
    with pytest.raises(PubMedHostProfileError,match='pubmed_profile_invalid'):
        PubMedHostProfile('private name@example.org')


def test_gui_controls_keep_two_step_consent_out_of_automated_probe_route():
    code=inspect.getsource(run)
    assert "name == 'pubmed_pilot_offer'" in code
    assert "name == 'pubmed_pilot_confirm'" in code
    assert "name == 'pubmed_pilot_reconcile'" in code
    assert 'flow.confirm_pubmed_pilot()' in code
    assert "'data-testid=pubmed-pilot-offer'" in code
    assert "'data-testid=pubmed-pilot-confirm'" in code
    assert "'data-testid=pubmed-pilot-reconcile'" in code
    assert "'data-testid=pubmed-profile-unavailable'" in code
    assert "ui.html(" not in code
    # The existing CI/browser probe has no ability to submit a pilot action.
    block=code.split("@app.post('/_probe/start')")[1].split("@app.post('/_probe/stop')")[0]
    assert 'pubmed_pilot' not in block
