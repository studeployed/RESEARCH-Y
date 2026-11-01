"""Offline durable Starter integration: real project/schema/client, synthetic HTTP."""
from __future__ import annotations
from contextlib import closing

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from urllib.parse import parse_qs, urlsplit

import pytest

from research_y.projects import create_project, open_project
from research_y.storage import ApprovedTerm, StrategyGroup, approve_strategy, create_search_run, plan_source_query
from research_y.wos_starter_client import WoSStarterClient, WoSHTTPResponse
from research_y.wos_checkpoint_store import (
    WoSCheckpointError, create_wos_checkpoint, inspect_wos_checkpoint,
    pause_wos_checkpoint, recover_wos_worker, validate_wos_checkpoint,
)
from research_y.wos_checkpoint_runner import run_wos_checkpoint

QUERY = 'TS=("ECMO")'
KEY = 'SYNTHETIC-ONLY-DO-NOT-SAVE'


class Clock:
    def __init__(self):
        self.value = 0.0
    def now(self):
        return datetime(2026, 10, 31, 12, tzinfo=timezone.utc) + timedelta(seconds=self.value)
    def monotonic(self):
        return self.value
    def sleep(self, seconds):
        self.value += seconds


class Provider:
    def __init__(self, clock, total=103):
        self.clock, self.total = clock, total
        self.remaining, self.daily = 5000, 5000
        self.calls = []
        self.fail_page = None
        self.error_status = 503
        self.retry_after = '120'
        self.change_count = False
        self.swap_uid = False
        self.echo_key = False
        self.title = 'Synthetic title'
        self.callback = None
        self.project = None
        self.response_mutator = None

    def __call__(self, req, timeout):
        fields = parse_qs(urlsplit(req.full_url).query)
        page, limit = int(fields['page'][0]), int(fields['limit'][0])
        assert fields['q'] == [QUERY] and fields['sortField'] == ['LD+A']
        assert req.get_header('X-apikey') == KEY
        purpose = None
        if self.project:
            with closing(sqlite3.connect(self.project.database_path)) as db, db:
                row = db.execute("SELECT purpose FROM wos_checkpoint_attempts WHERE outcome='started'").fetchone()
                purpose = row[0] if row else None
        self.calls.append((purpose, page, limit))
        self.clock.sleep(2)
        self.remaining -= 1
        headers = {'X-RateLimit-Limit-Day': str(self.daily), 'X-RateLimit-Remaining-Day': str(max(0,self.remaining))}
        if self.callback:
            self.callback(purpose, page, limit)
        if page == self.fail_page and limit == 50:
            return WoSHTTPResponse(self.error_status, {**headers, 'Retry-After':self.retry_after}, b'PRIVATE ERROR')
        total = self.total + int(self.change_count)
        hits = [{'uid': f'WOS:{i+1:015d}', 'title': self.title, 'unexpectedField': {'retained':True}}
                for i in range((page-1)*limit, min(page*limit,total))]
        if self.swap_uid and page == 2 and limit == 50:
            hits[0]['uid'] = 'WOS:999999999999999'
        if self.echo_key and hits:
            hits[0]['hidden'] = KEY
        body = {'metadata':{'total':total,'page':page,'limit':limit},'hits':hits}
        if self.response_mutator:
            self.response_mutator(body)
        return WoSHTTPResponse(200, headers, json.dumps(body).encode())


def setup(tmp_path, *, total=103, second_group=False):
    project = create_project(tmp_path, 'Starter project')
    groups = [StrategyGroup('g1','ECMO',(ApprovedTerm('ECMO','researcher',True),))]
    if second_group:
        groups.append(StrategyGroup('g2','Second',(ApprovedTerm('ECMO','researcher',True),)))
    version = approve_strategy(project, theme='Test', groups=tuple(groups), approved_by='Researcher', approval_confirmed=True)
    run = create_search_run(project, version.strategy_version_id)
    queries = [plan_source_query(project,run_id=run.run_id,group_id=g.group_id,source_name='wos',exact_query=QUERY) for g in groups]
    for q in queries:
        create_wos_checkpoint(project,q.query_id,retention_authorized=True)
    clock = Clock()
    provider = Provider(clock,total)
    provider.project = project
    return project, queries, clock, provider


def execute(project,q,clock,provider,**options):
    client = WoSStarterClient(api_key=KEY,request_budget=10000,transport=provider,
                              clock=clock.monotonic,sleep=clock.sleep,utc_now=clock.now)
    return run_wos_checkpoint(open_project(project.root),q.query_id,client,now=clock.now,**options)


def test_unknown_count_is_not_zero_before_provider_contact(tmp_path):
    p,qs,c,s = setup(tmp_path)
    state = inspect_wos_checkpoint(p,qs[0].query_id)
    assert state.reported_matches is None and state.pages_expected is None
    assert state.status == 'pending' and state.records_committed == 0
    assert s.calls == [] and not state.enumeration_reconciled


def test_103_records_full_capture_metadata_and_independent_verification(tmp_path):
    p,qs,c,s = setup(tmp_path)
    result = execute(p,qs[0],c,s)
    assert result.status == 'completed_with_warnings' and result.enumeration_reconciled
    assert result.reported_matches == result.records_committed == 103
    assert result.pages_committed == result.pages_expected == result.verification_pages == 3
    assert result.requests_confirmed_attempted == 7 and result.requests_unknown == 0
    assert not result.source_retrieval_verified and not result.provider_snapshot_guaranteed
    assert [x for x in s.calls if x[0]=='acquire'] == [('acquire',1,50),('acquire',2,50),('acquire',3,50)]
    assert [x for x in s.calls if x[0]=='verify'] == [('verify',1,50),('verify',2,50),('verify',3,50)]
    with closing(sqlite3.connect(p.database_path)) as db, db:
        assert db.execute('SELECT COUNT(*) FROM source_retrievals').fetchone()[0] == 103
        assert db.execute('SELECT COUNT(*) FROM query_retrievals').fetchone()[0] == 103
        metadata = json.loads(db.execute('SELECT original_metadata_json FROM source_retrievals LIMIT 1').fetchone()[0])
        assert metadata['record']['unexpectedField'] == {'retained':True}
        assert metadata['abstract_status'] == 'not_returned_by_source'
        assert metadata['rights_status'] == 'licence_review_required'
        assert db.execute('SELECT COUNT(*) FROM publications').fetchone()[0] == 0
        assert db.execute('SELECT status FROM search_runs').fetchone()[0] == 'incomplete'
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    before = len(s.calls)
    assert execute(p,qs[0],c,s).enumeration_reconciled
    assert len(s.calls) == before


def test_pause_reopen_fetches_only_missing_acquisition_pages(tmp_path):
    p,qs,c,s = setup(tmp_path)
    first = execute(p,qs[0],c,s,max_requests=1)
    assert first.status == 'paused' and first.pages_committed == 1
    assert first.records_committed == 50
    c.sleep(2)
    last = execute(p,qs[0],c,s)
    assert last.enumeration_reconciled and last.records_committed == 103
    assert len([x for x in s.calls if x==('acquire',1,50)]) == 1
    assert s.calls[1] == ('probe',1,1)
    validate_wos_checkpoint(open_project(p.root),qs[0].query_id)


def test_quota_zero_requires_explicit_later_observation_not_midnight_assumption(tmp_path):
    p,qs,c,s = setup(tmp_path)
    s.remaining = 1
    first = execute(p,qs[0],c,s)
    assert first.status == 'paused' and first.reason_code == 'quota_revalidation_required'
    assert first.pages_committed == 1 and first.quota['daily_remaining'] == 0
    c.sleep(86400)
    s.remaining = 5000
    blocked = execute(p,qs[0],c,s)
    assert blocked.status == 'paused' and len(s.calls) == 1
    final = execute(p,qs[0],c,s,revalidate_quota=True)
    assert final.enumeration_reconciled and final.quota['daily_limit'] == 5000
    assert len([x for x in s.calls if x==('acquire',1,50)]) == 1


def test_10005_records_checkpointed_and_verified_without_duplicates(tmp_path):
    p,qs,c,s = setup(tmp_path,total=10005)
    assert execute(p,qs[0],c,s,max_requests=1).records_committed == 50
    c.sleep(2)
    result = execute(p,qs[0],c,s)
    assert result.enumeration_reconciled
    assert result.records_committed == result.reported_matches == 10005
    assert result.pages_committed == result.verification_pages == 201
    with closing(sqlite3.connect(p.database_path)) as db, db:
        assert db.execute('SELECT COUNT(DISTINCT uid) FROM wos_checkpoint_ids').fetchone()[0] == 10005
    assert len([x for x in s.calls if x[0]=='acquire']) == 201


@pytest.mark.parametrize('total',[0,1,50,51,100],ids=['zero','one','full-page','partial-two','two-full'])
def test_page_boundary_and_genuine_zero_reconciliation(tmp_path,total):
    p,qs,c,s = setup(tmp_path,total=total)
    result = execute(p,qs[0],c,s)
    assert result.enumeration_reconciled and result.records_committed == total
    assert result.pages_expected == max(1,(total+49)//50)


def test_retry_after_survives_reopen_and_failures_do_not_reset_on_probe(tmp_path):
    p,qs,c,s = setup(tmp_path)
    s.fail_page = 2
    for attempt in range(3):
        result = execute(p,qs[0],c,s)
        assert result.pages_committed == 1 and result.failures == attempt+1
        calls = len(s.calls)
        early = execute(p,qs[0],c,s)
        assert len(s.calls)==calls and early.failures==result.failures
        c.sleep(121)
    assert result.status=='incomplete' and result.reason_code=='retry_budget_exhausted'
    assert len([x for x in s.calls if x==('acquire',2,50)])==3
    calls=len(s.calls)
    s.fail_page=None
    assert not execute(p,qs[0],c,s,revalidate_quota=True).enumeration_reconciled
    assert len(s.calls)==calls


def test_retryable_failure_can_recover_after_provider_backoff(tmp_path):
    p,qs,c,s=setup(tmp_path)
    s.fail_page=2
    assert execute(p,qs[0],c,s).status=='paused'
    c.sleep(121);s.fail_page=None
    result=execute(p,qs[0],c,s)
    assert result.enumeration_reconciled and result.failures==0


def test_source_count_drift_stops_without_overwriting_committed_subset(tmp_path):
    p,qs,c,s=setup(tmp_path)
    execute(p,qs[0],c,s,max_requests=1)
    c.sleep(2);s.change_count=True
    result=execute(p,qs[0],c,s)
    assert result.status=='incomplete' and result.reason_code=='source_count_changed'
    assert result.records_committed==50 and result.reported_matches==103
    assert len(s.calls)==2
    c.sleep(500);s.change_count=False
    execute(p,qs[0],c,s,revalidate_quota=True)
    assert len(s.calls)==2  # A changed source requires a new query/run, not silent mixing.


def test_same_count_identity_drift_is_detected_in_separate_verification_pass(tmp_path):
    p,qs,c,s=setup(tmp_path)
    def change(state):
        if state.stage=='verify':s.swap_uid=True
    result=execute(p,qs[0],c,s,on_progress=change)
    assert result.records_committed==103 and result.status=='incomplete'
    assert result.reason_code=='source_identity_changed' and not result.enumeration_reconciled
    assert result.verification_pages==1


def test_cross_page_duplicate_is_not_deduplicated_into_false_success(tmp_path):
    p,qs,c,s=setup(tmp_path)
    def duplicate(body):
        if body['metadata']['page']==2:body['hits'][0]['uid']='WOS:000000000000001'
    s.response_mutator=duplicate
    result=execute(p,qs[0],c,s)
    assert result.reason_code=='cross_page_duplicate' and result.pages_committed==1
    with closing(sqlite3.connect(p.database_path)) as db, db:
        assert db.execute('SELECT COUNT(*) FROM wos_checkpoint_observations').fetchone()[0]==2
        assert db.execute('SELECT COUNT(*) FROM source_retrievals').fetchone()[0]==50


def test_verification_restart_preserves_receipts_but_rechecks_the_entire_set(tmp_path):
    p,qs,c,s=setup(tmp_path)
    result=execute(p,qs[0],c,s,max_requests=4)
    assert result.verification_pages==1 and result.stage=='verify'
    c.sleep(86400)
    final=execute(p,qs[0],c,s)
    assert final.enumeration_reconciled
    assert len([x for x in s.calls if x[0]=='acquire'])==3
    with closing(sqlite3.connect(p.database_path)) as db, db:
        assert db.execute('SELECT COUNT(DISTINCT epoch) FROM wos_checkpoint_verifications').fetchone()[0]==2


def test_shared_accession_one_source_record_multiple_group_memberships(tmp_path):
    p,qs,c,s=setup(tmp_path,second_group=True)
    assert execute(p,qs[0],c,s).enumeration_reconciled
    c.sleep(2)
    assert execute(p,qs[1],c,s).enumeration_reconciled
    with closing(sqlite3.connect(p.database_path)) as db, db:
        assert db.execute('SELECT COUNT(*) FROM source_retrievals').fetchone()[0]==103
        assert db.execute('SELECT COUNT(*) FROM query_retrievals').fetchone()[0]==206


def test_conflicting_source_metadata_is_retained_as_observation_not_overwritten(tmp_path):
    p,qs,c,s=setup(tmp_path,second_group=True)
    execute(p,qs[0],c,s);c.sleep(2);s.title='Changed source value'
    result=execute(p,qs[1],c,s)
    assert result.reason_code=='source_record_conflict' and result.records_committed==0
    with closing(sqlite3.connect(p.database_path)) as db, db:
        assert 'Changed source value' not in db.execute('SELECT original_metadata_json FROM source_retrievals LIMIT 1').fetchone()[0]
        assert any('Changed source value' in row[0] for row in db.execute('SELECT response_json FROM wos_checkpoint_observations'))


def test_pause_requested_during_network_commits_inflight_page_then_stops(tmp_path):
    p,qs,c,s=setup(tmp_path)
    s.callback=lambda *_:pause_wos_checkpoint(p,qs[0].query_id)
    result=execute(p,qs[0],c,s)
    assert result.status=='paused' and result.records_committed==50 and len(s.calls)==1


def test_cancellation_is_terminal_and_keeps_completed_data(tmp_path):
    p,qs,c,s=setup(tmp_path)
    execute(p,qs[0],c,s,max_requests=1)
    pause_wos_checkpoint(p,qs[0].query_id,cancel=True)
    c.sleep(100)
    result=execute(p,qs[0],c,s)
    assert result.status=='cancelled' and result.records_committed==50 and len(s.calls)==1


def test_audit_write_failure_rolls_back_page_metadata_membership_and_progress(tmp_path):
    p,qs,c,s=setup(tmp_path)
    with closing(sqlite3.connect(p.database_path)) as db, db:
        db.execute("CREATE TRIGGER test_fail_audit BEFORE INSERT ON audit_events WHEN NEW.event_type='wos_page_committed' BEGIN SELECT RAISE(ABORT,'synthetic interruption'); END")
    with pytest.raises(WoSCheckpointError,match='checkpoint_write_failed'):execute(p,qs[0],c,s)
    state=inspect_wos_checkpoint(p,qs[0].query_id)
    assert state.pages_committed==state.records_committed==0 and state.reported_matches is None
    assert state.requests_unknown==1 and state.worker_active
    with closing(sqlite3.connect(p.database_path)) as db, db:
        assert db.execute('SELECT COUNT(*) FROM source_retrievals').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM query_retrievals').fetchone()[0]==0
        db.execute('DROP TRIGGER test_fail_audit')
    with pytest.raises(WoSCheckpointError,match='confirmation'):
        recover_wos_worker(p,qs[0].query_id,previous_worker_stopped=False)
    recover_wos_worker(p,qs[0].query_id,previous_worker_stopped=True)
    c.sleep(2)
    assert execute(p,qs[0],c,s).enumeration_reconciled


def test_immutable_records_and_corruption_preflight_before_any_provider_call(tmp_path):
    p,qs,c,s=setup(tmp_path)
    execute(p,qs[0],c,s,max_requests=1)
    with closing(sqlite3.connect(p.database_path)) as db, db:
        with pytest.raises(sqlite3.IntegrityError):db.execute('DELETE FROM wos_checkpoint_pages')
        with pytest.raises(sqlite3.IntegrityError):db.execute("UPDATE source_queries SET exact_query='TS=(\"other\")'")
        db.execute('DROP TRIGGER immutable_wos_checkpoint_observations_update')
        db.execute("UPDATE wos_checkpoint_observations SET response_json='{}'")
    c.sleep(2);calls=len(s.calls)
    with pytest.raises(WoSCheckpointError,match='checksum'):execute(p,qs[0],c,s)
    assert len(s.calls)==calls


def test_unapproved_query_and_unauthorised_retention_are_refused(tmp_path):
    p=create_project(tmp_path,'Approval')
    v=approve_strategy(p,theme='Broad',groups=(StrategyGroup('g','Concept',(ApprovedTerm('ECMO','researcher',True),ApprovedTerm('shock','researcher',True))),),approved_by='R',approval_confirmed=True)
    r=create_search_run(p,v.strategy_version_id)
    q=plan_source_query(p,run_id=r.run_id,group_id='g',source_name='wos',exact_query=QUERY)
    with pytest.raises(WoSCheckpointError,match='retention'):create_wos_checkpoint(p,q.query_id,retention_authorized=False)
    with pytest.raises(WoSCheckpointError,match='approved_compilation'):create_wos_checkpoint(p,q.query_id,retention_authorized=True)


def test_credential_echo_is_never_persisted(tmp_path):
    p,qs,c,s=setup(tmp_path)
    s.echo_key=True
    result=execute(p,qs[0],c,s)
    assert result.reason_code=='credential_echo_in_source' and result.reported_matches is None
    assert KEY.encode() not in p.database_path.read_bytes()


def test_process_death_leaves_unknown_attempt_and_requires_explicit_recovery(tmp_path):
    p,qs,c,s=setup(tmp_path)
    execute(p,qs[0],c,s,max_requests=1)
    c.sleep(10)
    code='''
import os,sys
from datetime import datetime,timezone
from research_y.projects import open_project
from research_y.wos_starter_client import WoSStarterClient
from research_y.wos_checkpoint_runner import run_wos_checkpoint
p=open_project(sys.argv[1])
def killed(request,timeout):os._exit(97)
client=WoSStarterClient(api_key="SYNTHETIC-ONLY-DO-NOT-SAVE",transport=killed)
run_wos_checkpoint(p,sys.argv[2],client,now=lambda:datetime(2026,11,1,tzinfo=timezone.utc))
'''
    env=dict(os.environ)
    env['PYTHONPATH']=str(Path(__file__).resolve().parents[1]/'src')
    child=subprocess.run([sys.executable,'-c',code,str(p.root),qs[0].query_id],env=env,capture_output=True,timeout=20)
    assert child.returncode==97
    state=inspect_wos_checkpoint(open_project(p.root),qs[0].query_id)
    assert state.records_committed==50 and state.requests_unknown==1
    with pytest.raises(WoSCheckpointError,match='worker_busy'):execute(p,qs[0],c,s)
    recover_wos_worker(p,qs[0].query_id,previous_worker_stopped=True)
    c.sleep(86400)
    final=execute(p,qs[0],c,s)
    assert final.enumeration_reconciled and final.requests_unknown==1
    assert len([x for x in s.calls if x==('acquire',1,50)])==1


@pytest.mark.parametrize('limit',[50,4999],ids=['trial','below-institutional'])
def test_trial_or_insufficient_entitlement_never_continues(tmp_path,limit):
    p,qs,c,s=setup(tmp_path)
    s.daily=s.remaining=limit
    result=execute(p,qs[0],c,s)
    assert result.reason_code=='entitlement_unverified' and result.records_committed==0
    assert len(s.calls)==1
    c.sleep(86400)
    assert execute(p,qs[0],c,s).status=='incomplete' and len(s.calls)==1


def test_auth_failure_unknown_count_not_zero_and_no_error_body_saved(tmp_path):
    p,qs,c,s=setup(tmp_path)
    s.fail_page=1;s.error_status=401
    result=execute(p,qs[0],c,s)
    assert result.status=='incomplete' and result.reported_matches is None
    assert result.requests_confirmed_attempted==1 and result.records_committed==0
    assert b'PRIVATE ERROR' not in p.database_path.read_bytes()


def test_server_retry_after_on_success_survives_process_boundary(tmp_path):
    p,qs,c,s=setup(tmp_path)
    original=s.__call__
    def delayed(req,timeout):
        response=original(req,timeout)
        return WoSHTTPResponse(200,{**response.headers,'Retry-After':'300'},response.body)
    client=WoSStarterClient(api_key=KEY,transport=delayed,request_budget=20,clock=c.monotonic,sleep=c.sleep,utc_now=c.now)
    first=run_wos_checkpoint(p,qs[0].query_id,client,now=c.now)
    assert first.status=='paused' and first.reason_code=='server_retry_after'
    assert first.records_committed==50
    calls=len(s.calls);c.sleep(120)
    assert execute(p,qs[0],c,s).status=='paused' and len(s.calls)==calls
    c.sleep(181)
    assert execute(p,qs[0],c,s).enumeration_reconciled


def test_active_worker_blocks_second_writer_without_duplicate_network(tmp_path):
    p,qs,c,s=setup(tmp_path,second_group=True)
    def collision(purpose,page,limit):
        if purpose=='acquire' and page==1:
            with pytest.raises(WoSCheckpointError,match='another_wos_worker_active'):
                execute(p,qs[1],c,s)
    s.callback=collision
    assert execute(p,qs[0],c,s).enumeration_reconciled
    assert inspect_wos_checkpoint(p,qs[1].query_id).status=='pending'


def test_stale_worker_response_cannot_commit_after_explicit_recovery(tmp_path):
    p,qs,c,s=setup(tmp_path)
    # Simulates the fencing race, not permission to recover an actually live worker.
    s.callback=lambda *_:recover_wos_worker(p,qs[0].query_id,previous_worker_stopped=True)
    with pytest.raises(WoSCheckpointError,match='stale_worker'):execute(p,qs[0],c,s)
    state=inspect_wos_checkpoint(p,qs[0].query_id)
    assert state.records_committed==0 and state.requests_unknown==1


def test_relocation_preserves_query_page_and_record_identity(tmp_path):
    p,qs,c,s=setup(tmp_path)
    execute(p,qs[0],c,s,max_requests=1)
    destination=tmp_path/'relocated';p.root.rename(destination)
    p=open_project(destination);s.project=p;c.sleep(2)
    assert execute(p,qs[0],c,s).enumeration_reconciled


@pytest.mark.parametrize('budget',[0,-1,True,10001,1.5],ids=['zero','negative','bool','too-large','float'])
def test_invalid_session_budgets_fail_before_network(tmp_path,budget):
    p,qs,c,s=setup(tmp_path)
    with pytest.raises(WoSCheckpointError,match='budget'):execute(p,qs[0],c,s,max_requests=budget)
    assert s.calls==[]


def test_session_budget_cannot_hide_exhausted_quota(tmp_path):
    p,qs,c,s=setup(tmp_path)
    s.remaining=1
    result=execute(p,qs[0],c,s,max_requests=1)
    assert result.reason_code=='quota_revalidation_required'
    c.sleep(86400);s.remaining=5000
    execute(p,qs[0],c,s)
    assert len(s.calls)==1


def test_failed_final_probe_never_labels_complete_and_requires_new_identity_pass(tmp_path):
    p,qs,c,s=setup(tmp_path)
    def fail_final(purpose,page,limit):
        if purpose=='final':s.change_count=True
    s.callback=fail_final
    result=execute(p,qs[0],c,s)
    assert result.stage=='final' and not result.enumeration_reconciled
    assert result.status=='incomplete' and result.reason_code=='source_count_changed'
    assert result.records_committed==103


@pytest.mark.parametrize('cancel', [False, True])
def test_pause_or_cancel_survives_rejected_inflight_response(tmp_path, cancel):
    p,qs,c,s = setup(tmp_path)
    def stop(purpose, page, limit):
        if purpose == 'acquire' and page == 2:
            pause_wos_checkpoint(p, qs[0].query_id, cancel=cancel)
            s.change_count = True
    s.callback = stop
    result = execute(p,qs[0],c,s)
    assert result.status == ('cancelled' if cancel else 'paused')
    assert result.reason_code == 'source_count_changed'
    assert result.records_committed == 50 and not result.enumeration_reconciled
    before = len(s.calls)
    c.sleep(3600)
    assert not execute(p,qs[0],c,s,revalidate_quota=True).enumeration_reconciled
    assert len(s.calls) == before


def test_missing_entitlement_is_retained_as_observation_not_acquisition(tmp_path):
    p,qs,c,s = setup(tmp_path)
    base = s.__call__
    def no_headers(req, timeout):
        reply = base(req, timeout)
        return WoSHTTPResponse(reply.status, {}, reply.body)
    result = execute(p,qs[0],c,no_headers)
    assert result.status == 'incomplete' and result.reason_code == 'entitlement_unverified'
    assert result.pages_committed == 0 and result.records_committed == 0
    with closing(sqlite3.connect(p.database_path)) as db:
        assert db.execute('SELECT COUNT(*) FROM wos_checkpoint_observations').fetchone()[0] == 1
    assert not result.enumeration_reconciled
