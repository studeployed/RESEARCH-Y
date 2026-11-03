"""P1-06f6: offline Starter minimal-page count/quota pilot acceptance tests.

Every HTTP response is synthetic and uses an injected fixed-origin transport.
No institutional credentials or licensed bibliographic payloads are uploaded.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
from threading import Event
import json
import sqlite3
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest

from research_y.projects import create_project, open_project
from research_y.preflight_review import read_preflight
from research_y.storage import ApprovedTerm, StrategyGroup
from research_y.strategy_admission import commit_approved_strategy
from research_y.wos_starter_client import WoSStarterClient, WoSHTTPResponse
from research_y.wos_checkpoint_store import (
    create_wos_checkpoint, _provider_hold, _stamp, _claim,
)
from research_y.wos_starter_pilot import (
    REQUEST_EVENT, OUTCOME_EVENT, WoSPilotError, read_wos_pilot,
    probe_wos_starter_once,
)

KEY = 'SYNTHETIC-PRIVATE-STARTER-KEY'
HEADERS = {
    'X-RateLimit-Limit-Day':'5000',
    'X-RateLimit-Remaining-Day':'4997',
    'X-RateLimit-Limit-Second':'2',
}
LICENSED_TITLE = 'COPYRIGHTED-SYNTHETIC-TITLE-NEVER-PERSIST'
LICENSED_UID = 'WOS:000000000000029'


def fixture(tmp_path):
    project = create_project(tmp_path, 'One-record WoS pilot')
    strategy = commit_approved_strategy(
        project, request_id=str(uuid4()), theme='Right heart failure',
        groups=(StrategyGroup('g1','Right heart',
            (ApprovedTerm('right ventricle','researcher',True),
             ApprovedTerm('right-ventricle','deterministic',True,
                          'Alternative hyphenation'))),),
        approved_by='Researcher', approval_confirmed=True,
    )
    summary=read_preflight(project,strategy.run_id)
    wos=next(source for source in summary['sources']
             if source['source_name']=='wos')
    query=wos['queries'][0]
    return project,strategy.run_id,summary['plan_sha256'],query


def client(*, headers=None, count=123, trace=None, fail=None,
           key=KEY, block=None, response_override=None):
    actual_headers = HEADERS if headers is None else headers
    def transport(request, timeout):
        if trace is not None:
            trace.append(request)
        values=parse_qs(urlsplit(request.full_url).query)
        assert request.get_method()=='GET'
        assert urlsplit(request.full_url).netloc=='api.clarivate.com'
        assert urlsplit(request.full_url).path=='/apis/wos-starter/v1/documents'
        assert values['db']==['WOS'] and values['page']==['1']
        assert values['limit']==['1'] and values['sortField']==['LD+A']
        assert values['q'][0].startswith('TS=(')
        assert KEY not in request.full_url
        assert request.headers['X-apikey'] == key
        if block:
            started,release=block
            started.set()
            assert release.wait(15)
        if fail=='abrupt':
            raise KeyboardInterrupt('simulated worker exit')
        if fail=='network':
            raise URLError('simulated offline')
        if fail=='auth':
            return WoSHTTPResponse(403, actual_headers, b'')
        if fail=='throttle':
            return WoSHTTPResponse(429, {**actual_headers,'Retry-After':'30'},b'')
        if fail=='throttle_no_retry':
            return WoSHTTPResponse(429, actual_headers, b'')
        if response_override is not None:
            return WoSHTTPResponse(200,actual_headers,
                json.dumps(response_override).encode('utf-8'))
        return WoSHTTPResponse(200, actual_headers, json.dumps({
            'metadata':{'total':count,'page':1,'limit':1},
            'hits':([{'uid':LICENSED_UID,'title':LICENSED_TITLE,
                      'unknownLicensedField':'COPYRIGHT-METADATA'}
                     ] if count else []),
        }).encode('utf-8'))
    return WoSStarterClient(api_key=key,transport=transport,
                            request_budget=1,clock=lambda:1000.0,
                            sleep=lambda _:None)


def submit(project,run_id,plan_hash,query,wos_client,*,pilot_id=None,**overrides):
    kwargs=dict(pilot_id=pilot_id or str(uuid4()),run_id=run_id,
                query_id=query['query_id'],expected_plan_sha256=plan_hash,
                confirmed=True,client=wos_client)
    kwargs.update(overrides)
    return probe_wos_starter_once(project,**kwargs)


def audit(project,pilot_id=None):
    with closing(sqlite3.connect(project.database_path)) as db:
        records=[(kind,json.loads(raw)) for kind,raw in db.execute(
            "SELECT event_type,details_json FROM audit_events "
            "WHERE event_type IN (?,?) ORDER BY event_id",
            (REQUEST_EVENT,OUTCOME_EVENT))]
    return records if pilot_id is None else [
        (kind,record) for kind,record in records
        if record['pilot_id']==pilot_id]


def ordinary_queries(project,run_id):
    with closing(sqlite3.connect(project.database_path)) as db:
        return db.execute(
            'SELECT source_name,status,reported_matches FROM source_queries '
            'WHERE run_id=? ORDER BY source_name',(run_id,)).fetchall()


def test_one_record_starter_pilot_reports_count_quota_not_licensed_records(tmp_path):
    project,run_id,plan,query=fixture(tmp_path)
    before=ordinary_queries(project,run_id)
    calls=[]
    pilot_id=str(uuid4())
    report=submit(project,run_id,plan,query,client(trace=calls),pilot_id=pilot_id)
    assert len(calls)==1
    assert report['pilot_id']==pilot_id and report['run_id']==run_id
    assert report['status']=='count_reported_sample_not_retained'
    assert report['reported_matches']==123
    assert report['quota_status']=='institutional_allowance_observed'
    assert report['quota']['daily_limit']==5000
    assert report['quota']['daily_remaining']==4997
    assert report['sample_page_limit']==1
    assert report['access_probe_records_received']==1
    assert report['accepted_translation'] is None
    assert report['translation_status']=='not_exposed_by_starter_contract'
    assert report['count_only'] is False
    assert report['bibliographic_records_persisted']==0
    assert report['retrieval_verified'] is False
    assert report['search_completed'] is False
    assert report['source_retrieval_verified'] is False
    assert report['execution_authorized'] is False
    assert report['automatically_retryable'] is False
    assert [event for event,_ in audit(project,pilot_id)]==[REQUEST_EVENT,OUTCOME_EVENT]
    assert ordinary_queries(project,run_id)==before
    assert read_preflight(project,run_id)['provider_counts'] is None
    text=json.dumps((audit(project),report),sort_keys=True)
    assert LICENSED_TITLE not in text and LICENSED_UID not in text
    assert KEY not in text and 'COPYRIGHT-METADATA' not in text
    with closing(sqlite3.connect(project.database_path)) as db:
        assert db.execute('SELECT COUNT(*) FROM source_retrievals').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM publications').fetchone()[0]==0
    assert read_wos_pilot(open_project(project.root),pilot_id)==report


def test_same_uuid_read_only_replay_does_not_consume_second_quota_request(tmp_path):
    project,rid,sha,q=fixture(tmp_path)
    pid=str(uuid4())
    first_trace=[]
    first=submit(project,rid,sha,q,client(trace=first_trace),pilot_id=pid)
    replay_trace=[]
    second=submit(project,rid,sha,q,client(trace=replay_trace),pilot_id=pid)
    assert second==first and first_trace and not replay_trace
    assert len(audit(project,pid))==2


def test_empty_real_zero_has_zero_page_hits_but_not_final_source_count(tmp_path):
    project,rid,sha,q=fixture(tmp_path)
    report=submit(project,rid,sha,q,client(count=0))
    assert report['reported_matches']==0
    assert report['access_probe_records_received']==0
    assert report['status']=='count_reported_sample_not_retained'
    assert all(row[2] is None for row in ordinary_queries(project,rid))


@pytest.mark.parametrize('headers,status',[
    ({},'entitlement_unverified'),
    ({'X-RateLimit-Limit-Day':'50','X-RateLimit-Remaining-Day':'49'},
     'entitlement_unverified'),
    ({'X-RateLimit-Limit-Day':'5000','X-RateLimit-Remaining-Day':'0'},
     'quota_exhausted_after_probe'),
    ({'X-RateLimit-Limit-Day':'5000','X-RateLimit-Remaining-Day':'nonsense'},
     'entitlement_unverified'),
])
def test_unknown_trial_or_exhausted_quota_never_claims_institutional_verified(
    tmp_path,headers,status
):
    project,rid,sha,q=fixture(tmp_path)
    result=submit(project,rid,sha,q,client(headers=headers))
    assert result['status']==status
    assert result['reported_matches']==123
    assert not result['retrieval_verified']
    assert not result['source_retrieval_verified']


@pytest.mark.parametrize('failure,code',[
    ('network','network_error'),
    ('auth','authentication_or_entitlement_denied'),
    ('throttle','quota_or_rate_limited'),
])
def test_network_auth_and_rate_failures_record_unknown_count_with_static_error(
    tmp_path,failure,code
):
    project,rid,sha,q=fixture(tmp_path)
    pilot_id=str(uuid4())
    result=submit(project,rid,sha,q,client(fail=failure),pilot_id=pilot_id)
    assert result['status']=='probe_failed'
    assert result['reported_matches'] is None
    assert result['error_code']==code
    if failure=='network':
        assert result['quota'] is None
        assert result['quota_status']=='not_observed'
    else:
        # HTTP error headers remain audited, not discarded with the count.
        assert result['quota']['daily_remaining']==4997
        assert result['quota_status']=='institutional_allowance_observed'
    assert not result['retrieval_verified']
    assert len(audit(project,pilot_id))==2
    assert result['retry_after_seconds']==(30 if failure=='throttle' else None)


def test_provider_echoing_secret_is_never_journalled(tmp_path):
    project,rid,sha,q=fixture(tmp_path)
    response={'metadata':{'total':1,'page':1,'limit':1},
              'hits':[{'uid':LICENSED_UID,'title':'provider says '+KEY}]}
    pid=str(uuid4())
    result=submit(project,rid,sha,q,client(response_override=response),pilot_id=pid)
    assert result['status']=='probe_failed'
    assert result['error_code']=='credential_echo_in_source'
    assert KEY not in json.dumps(audit(project,pid))


def test_malformed_or_wrong_source_query_rejected_before_network(tmp_path):
    project,rid,sha,q=fixture(tmp_path)
    with closing(sqlite3.connect(project.database_path)) as db,db:
        db.execute('UPDATE source_queries SET exact_query=? WHERE query_id=?',
                   ('TS=("ECMO" AND "wider")',q['query_id']))
    trace=[]
    with pytest.raises(WoSPilotError,match='^pilot_plan_invalid$'):
        submit(project,rid,sha,q,client(trace=trace))
    assert not trace and not audit(project)


@pytest.mark.parametrize('edit,code',[
    ({'confirmed':False},'pilot_confirmation_required'),
    ({'confirmed':1},'pilot_confirmation_required'),
    ({'pilot_id':'invalid'},'invalid_identifier'),
    ({'query_id':'invalid'},'invalid_identifier'),
    ({'expected_plan_sha256':'a'*64},'pilot_plan_invalid'),
    ({'revalidate_quota':1},'pilot_confirmation_required'),
    ({'revalidate_quota':None},'pilot_confirmation_required'),
])
def test_invalid_pilot_is_never_sent_or_audited(tmp_path,edit,code):
    project,rid,sha,q=fixture(tmp_path)
    trace=[]
    with pytest.raises(WoSPilotError,match='^'+code+'$'):
        submit(project,rid,sha,q,client(trace=trace),**edit)
    assert trace==[] and audit(project)==[]


def test_wrong_source_id_and_idle_reused_client_refused(tmp_path):
    project,rid,sha,q=fixture(tmp_path)
    wos_query=q
    preflight=read_preflight(project,rid)
    pubmed=next(s for s in preflight['sources'] if s['source_name']=='pubmed')
    with pytest.raises(WoSPilotError,match='pilot_plan_invalid'):
        submit(project,rid,sha,pubmed['queries'][0],client())
    current_client=client()
    current_client.requests_made=1
    with pytest.raises(WoSPilotError,match='pilot_client_invalid'):
        submit(project,rid,sha,wos_query,current_client)
    assert audit(project)==[]


def test_changed_run_during_response_makes_count_stale(tmp_path):
    project,rid,sha,q=fixture(tmp_path)
    def transport(request,timeout):
        with closing(sqlite3.connect(project.database_path)) as db,db:
            db.execute("UPDATE search_runs SET status='paused' WHERE run_id=?", (rid,))
        return WoSHTTPResponse(200,HEADERS,json.dumps({
            'metadata':{'total':999,'page':1,'limit':1},
            'hits':[{'uid':LICENSED_UID,'title':LICENSED_TITLE}],
        }).encode())
    c=WoSStarterClient(api_key=KEY,transport=transport,request_budget=1)
    result=submit(project,rid,sha,q,c)
    assert result['status']=='stale_plan'
    assert result['reported_matches'] is None
    assert result['quota'] is None
    assert result['source_retrieval_verified'] is False


def test_crashed_worker_is_indeterminate_and_same_uuid_never_resends(tmp_path):
    project,rid,sha,q=fixture(tmp_path)
    pid=str(uuid4())
    trace=[]
    with pytest.raises(KeyboardInterrupt):
        submit(project,rid,sha,q,client(fail='abrupt',trace=trace),pilot_id=pid)
    saved=read_wos_pilot(project,pid)
    assert saved['status']=='requested_indeterminate'
    assert saved['reported_matches'] is None
    assert saved['automatically_retryable'] is False
    other=[]
    replay=submit(project,rid,sha,q,client(trace=other),pilot_id=pid)
    assert replay==saved and not other
    assert len(trace)==1 and len(audit(project,pid))==1


def test_outcome_audit_failure_leaves_indeterminate_request_and_no_retry(tmp_path,monkeypatch):
    from research_y import wos_starter_pilot as module
    project,rid,sha,q=fixture(tmp_path)
    original=module._audit
    def fail(*args,**kwargs):
        if kwargs['kind']==OUTCOME_EVENT:
            raise OSError('injected write failure')
        return original(*args,**kwargs)
    monkeypatch.setattr(module,'_audit',fail)
    pid=str(uuid4())
    trace=[]
    with pytest.raises(WoSPilotError,match='^pilot_storage_failed$'):
        submit(project,rid,sha,q,client(trace=trace),pilot_id=pid)
    assert len(trace)==1
    assert read_wos_pilot(project,pid)['status']=='requested_indeterminate'
    assert len(audit(project,pid))==1
    other=[]
    assert submit(project,rid,sha,q,client(trace=other),pilot_id=pid)['status']==(
        'requested_indeterminate')
    assert other==[]


def test_request_audit_failure_stops_before_any_transport(tmp_path,monkeypatch):
    from research_y import wos_starter_pilot as module
    project,rid,sha,q=fixture(tmp_path)
    original=module._audit
    def fail(*args,**kwargs):
        if kwargs['kind']==REQUEST_EVENT:
            raise OSError('injected preflight audit write failure')
        return original(*args,**kwargs)
    monkeypatch.setattr(module,'_audit',fail)
    trace=[]
    with pytest.raises(WoSPilotError,match='^pilot_storage_failed$'):
        submit(project,rid,sha,q,client(trace=trace))
    assert not trace and not audit(project)


def test_same_uuid_two_processes_do_not_both_call_provider(tmp_path):
    project,rid,sha,q=fixture(tmp_path)
    started,release=Event(),Event()
    trace=[]
    pid=str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(submit,project,rid,sha,q,
                          client(trace=trace,block=(started,release)),
                          pilot_id=pid)
        assert started.wait(10)
        second=pool.submit(submit,project,rid,sha,q,
                           client(trace=trace),pilot_id=pid)
        observed=second.result(timeout=10)
        assert observed['status']=='requested_indeterminate'
        release.set()
        completed=first.result(timeout=10)
    assert completed['status']=='count_reported_sample_not_retained'
    assert len(trace)==1
    assert len(audit(project,pid))==2


def test_same_uuid_conflicting_query_or_revalidate_flag_is_rejected(tmp_path):
    project,rid,sha,q=fixture(tmp_path)
    pid=str(uuid4())
    submit(project,rid,sha,q,client(),pilot_id=pid)
    with pytest.raises(WoSPilotError,match='^pilot_conflict$'):
        submit(project,rid,sha,q,client(),pilot_id=pid,
               revalidate_quota=True)
    with pytest.raises(WoSPilotError,match='^pilot_conflict$'):
        submit(project,rid,sha,q,client(),pilot_id=pid,query_id=str(uuid4()))
    assert len(audit(project,pid))==2


def test_projectwide_checkpoint_hold_and_live_worker_block_new_pilot(tmp_path):
    project,rid,sha,q=fixture(tmp_path)
    create_wos_checkpoint(project,q['query_id'],retention_authorized=True)
    with closing(sqlite3.connect(project.database_path)) as db,db:
        db.execute('UPDATE wos_checkpoint_jobs SET not_before_utc=?',
            ((datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(
                timespec='microseconds'),))
    trace=[]
    with pytest.raises(WoSPilotError,match='^provider_cooldown$'):
        submit(project,rid,sha,q,client(trace=trace))
    assert trace==[] and audit(project)==[]
    with closing(sqlite3.connect(project.database_path)) as db,db:
        db.execute('UPDATE wos_checkpoint_jobs SET not_before_utc=NULL,'
                   'owner_token=?',(str(uuid4()),))
    with pytest.raises(WoSPilotError,match='^provider_worker_active$'):
        submit(project,rid,sha,q,client(trace=trace))
    assert not trace and not audit(project)


def test_zero_remaining_from_prior_pilot_requires_explicit_revalidation(tmp_path,monkeypatch):
    from research_y import wos_starter_pilot as module
    project,rid,sha,q=fixture(tmp_path)
    first=submit(project,rid,sha,q,client(headers={
        'X-RateLimit-Limit-Day':'5000',
        'X-RateLimit-Remaining-Day':'0'}))
    assert first['status']=='quota_exhausted_after_probe'
    # Remove only the *short pacing* guard to isolate project-level durable
    # quota blocking; no real HTTP is performed in these tests.
    monkeypatch.setattr(module,'MIN_REQUEST_INTERVAL',0.0)
    trace=[]
    with pytest.raises(WoSPilotError,match='provider_quota_revalidation_required'):
        submit(project,rid,sha,q,client(trace=trace))
    assert trace==[]
    explicit=submit(project,rid,sha,q,client(trace=trace),
                    revalidate_quota=True)
    assert explicit['status']=='count_reported_sample_not_retained'
    assert len(trace)==1


def test_distinct_pilots_are_temporarily_serialized_across_client_instances(tmp_path):
    project,rid,sha,q=fixture(tmp_path)
    submit(project,rid,sha,q,client())
    trace=[]
    with pytest.raises(WoSPilotError,match='^provider_pilot_cooldown$'):
        submit(project,rid,sha,q,client(trace=trace))
    assert not trace
    assert len(audit(project))==2


def test_historical_pilot_readable_after_run_state_change(tmp_path):
    project,rid,sha,q=fixture(tmp_path)
    report=submit(project,rid,sha,q,client())
    with closing(sqlite3.connect(project.database_path)) as db,db:
        db.execute('UPDATE search_runs SET status=? WHERE run_id=?',
                   ('paused',rid))
    saved=read_wos_pilot(open_project(project.root),report['pilot_id'])
    assert saved==report


def _hold(project, *, revalidate=False):
    with closing(sqlite3.connect(project.database_path)) as db:
        db.row_factory=sqlite3.Row
        return _provider_hold(db,_stamp(),revalidate_quota=revalidate)


def test_server_retry_after_is_durable_and_cannot_be_bypassed_by_new_pilot(
    tmp_path, monkeypatch
):
    from research_y import wos_starter_pilot as module
    project,rid,sha,q=fixture(tmp_path)
    first=submit(project,rid,sha,q,client(fail='throttle'))
    assert first['status']=='probe_failed'
    assert first['retry_after_seconds']==30
    assert first['quota']['daily_remaining']==4997
    assert _hold(project)[0]=='provider_cooldown'
    # Isolate the longer server hold from the generic 1.05s pilot gap.
    monkeypatch.setattr(module,'MIN_REQUEST_INTERVAL',0.0)
    requests=[]
    for explicit in (False,True):
        with pytest.raises(WoSPilotError,match='^provider_cooldown$'):
            submit(project,rid,sha,q,client(trace=requests),
                   revalidate_quota=explicit)
    assert requests==[]
    assert len(audit(project))==2


def test_429_quota_zero_is_durable_and_shared_even_without_retry_after(
    tmp_path,monkeypatch
):
    from research_y import wos_starter_pilot as module
    project,rid,sha,q=fixture(tmp_path)
    exhausted={'X-RateLimit-Limit-Day':'5000',
               'X-RateLimit-Remaining-Day':'0'}
    failed=submit(project,rid,sha,q,
                  client(headers=exhausted,fail='throttle_no_retry'))
    assert failed['status']=='probe_failed'
    assert failed['reported_matches'] is None
    assert failed['quota']['daily_remaining']==0
    assert failed['retry_after_seconds'] is None
    assert _hold(project)==('provider_quota_revalidation_required',None)
    monkeypatch.setattr(module,'MIN_REQUEST_INTERVAL',0.0)
    attempts=[]
    with pytest.raises(WoSPilotError,match='^provider_quota_revalidation_required$'):
        submit(project,rid,sha,q,client(trace=attempts))
    assert attempts==[]
    permitted=submit(project,rid,sha,q,client(trace=attempts),
                     revalidate_quota=True)
    assert permitted['status']=='count_reported_sample_not_retained'
    assert len(attempts)==1
    assert _hold(project)[0] is None


def test_exhausted_pilot_blocks_existing_checkpoint_worker_without_refetch(tmp_path):
    project,rid,sha,q=fixture(tmp_path)
    exhausted={'X-RateLimit-Limit-Day':'5000',
               'X-RateLimit-Remaining-Day':'0'}
    result=submit(project,rid,sha,q,client(headers=exhausted))
    assert result['status']=='quota_exhausted_after_probe'
    assert _hold(project)[0]=='provider_quota_revalidation_required'
    create_wos_checkpoint(project,q['query_id'],retention_authorized=True)
    claimed=_claim(project,q['query_id'],_stamp(),revalidate_quota=False)
    assert claimed is None
    assert _hold(project)[0]=='provider_quota_revalidation_required'
    with closing(sqlite3.connect(project.database_path)) as db:
        row=db.execute(
            'SELECT status,reported_matches FROM source_queries WHERE query_id=?',
            (q['query_id'],)).fetchone()
    assert row[1] is None
    assert row[0] in ('pending','paused')


def test_failed_http_observed_quota_not_confused_with_source_count(tmp_path):
    project,rid,sha,q=fixture(tmp_path)
    exhausted={'X-RateLimit-Limit-Day':'50',
               'X-RateLimit-Remaining-Day':'0'}
    failed=submit(project,rid,sha,q,
                  client(headers=exhausted,fail='auth'))
    assert failed['status']=='probe_failed'
    assert failed['reported_matches'] is None
    assert failed['error_code']=='authentication_or_entitlement_denied'
    assert failed['quota']['daily_limit']==50
    assert failed['quota_status']=='below_required_institutional_allowance'
    assert ordinary_queries(project,rid)[0][2] is None
    assert _hold(project)[0]=='provider_quota_revalidation_required'


def test_completed_attempt_replay_is_allowed_even_with_same_used_client(tmp_path):
    project,rid,sha,q=fixture(tmp_path)
    pid=str(uuid4())
    existing_client=client()
    first=submit(project,rid,sha,q,existing_client,pilot_id=pid)
    assert existing_client.requests_made==1
    replay=submit(project,rid,sha,q,existing_client,pilot_id=pid)
    assert replay==first
    assert len(audit(project,pid))==2


def test_successful_http_200_retry_after_is_not_lost_on_a_count(tmp_path,monkeypatch):
    from research_y import wos_starter_pilot as module
    project,rid,sha,q=fixture(tmp_path)
    headers={**HEADERS,'Retry-After':'30'}
    result=submit(project,rid,sha,q,client(headers=headers))
    assert result['status']=='count_reported_sample_not_retained'
    assert result['reported_matches']==123
    assert result['retry_after_seconds']==30
    assert _hold(project)[0]=='provider_cooldown'
    monkeypatch.setattr(module,'MIN_REQUEST_INTERVAL',0.0)
    trace=[]
    with pytest.raises(WoSPilotError,match='^provider_cooldown$'):
        submit(project,rid,sha,q,client(trace=trace),revalidate_quota=True)
    assert trace==[]


def test_invalid_http_200_body_still_retains_its_quota_and_retry_after(tmp_path):
    project,rid,sha,q=fixture(tmp_path)
    headers={
        'X-RateLimit-Limit-Day':'5000',
        'X-RateLimit-Remaining-Day':'0',
        'Retry-After':'30',
    }
    malformed={'error':'source rejected this request'}
    result=submit(project,rid,sha,q,
                  client(headers=headers,response_override=malformed))
    assert result['status']=='probe_failed'
    assert result['reported_matches'] is None
    assert result['error_code']=='source_error_or_warning'
    assert result['quota']['daily_remaining']==0
    assert result['retry_after_seconds']==30
    assert _hold(project)[0]=='provider_cooldown'


def test_stale_run_discards_count_but_keeps_provider_failure_limits(tmp_path):
    project,rid,sha,q=fixture(tmp_path)
    headers={
        'X-RateLimit-Limit-Day':'5000',
        'X-RateLimit-Remaining-Day':'0',
        'Retry-After':'30',
    }
    def transport(request,timeout):
        with closing(sqlite3.connect(project.database_path)) as db, db:
            db.execute("UPDATE search_runs SET status='paused' WHERE run_id=?",
                       (rid,))
        return WoSHTTPResponse(429,headers,b'')
    c=WoSStarterClient(api_key=KEY,transport=transport,request_budget=1)
    result=submit(project,rid,sha,q,c)
    assert result['status']=='stale_plan'
    assert result['reported_matches'] is None
    assert result['quota']['daily_remaining']==0
    assert result['retry_after_seconds']==30
    assert result['error_code']=='quota_or_rate_limited'
    assert _hold(project)[0]=='provider_cooldown'
    restored=read_wos_pilot(open_project(project.root),result['pilot_id'])
    assert restored==result
    assert all(row[2] is None for row in ordinary_queries(project,rid))


def test_stale_successful_count_still_preserves_observed_exhaustion(tmp_path):
    project,rid,sha,q=fixture(tmp_path)
    exhausted={'X-RateLimit-Limit-Day':'5000',
               'X-RateLimit-Remaining-Day':'0'}
    def transport(request,timeout):
        with closing(sqlite3.connect(project.database_path)) as db, db:
            db.execute("UPDATE search_runs SET status='paused' WHERE run_id=?",
                       (rid,))
        return WoSHTTPResponse(200,exhausted,json.dumps({
            'metadata':{'total':99,'page':1,'limit':1},
            'hits':[{'uid':LICENSED_UID,'title':LICENSED_TITLE}]
        }).encode('utf-8'))
    result=submit(project,rid,sha,q,
                  WoSStarterClient(api_key=KEY,transport=transport,
                                   request_budget=1))
    assert result['status']=='stale_plan'
    assert result['reported_matches'] is None
    assert result['quota']['daily_remaining']==0
    assert _hold(project)[0]=='provider_quota_revalidation_required'
    assert LICENSED_UID not in json.dumps(audit(project))


def test_unrepresentable_retry_after_fails_closed_without_discarding_count(tmp_path):
    from research_y.wos_checkpoint_store import WoSCheckpointError
    project,rid,sha,q=fixture(tmp_path)
    headers={**HEADERS,'Retry-After':str(366*86400)}
    result=submit(project,rid,sha,q,client(headers=headers))
    assert result['reported_matches']==123
    assert result['retry_after_seconds'] is None
    assert result['retry_after_unverifiable'] is True
    with pytest.raises(WoSCheckpointError,match='provider_retry_after_unverifiable'):
        _hold(project,revalidate=True)
