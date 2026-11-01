"""Actual project/capture/export integration through the spawned local worker."""
from contextlib import closing
from dataclasses import replace
from hashlib import sha256
import os
from pathlib import Path
import shutil
import sqlite3
import time
from uuid import uuid4

import pytest
from research_y import application_worker as worker
from research_y.application_commands import ApplicationCommand, execute_command
from research_y.application_inspection import list_export_requests, observe_export_request, read_export_report
from research_y.projects import create_project, open_project
from research_y.storage import ApprovedTerm, StrategyGroup, approve_strategy, create_search_run, plan_source_query


@pytest.fixture
def application(tmp_path):
    p=create_project(tmp_path,'Worker integration')
    version=approve_strategy(p,theme='Synthetic strategy',approved_by='Fixture',approval_confirmed=True,
        groups=(StrategyGroup('g','Group',(ApprovedTerm('ECMO','researcher',True),)),))
    run=create_search_run(p,version.strategy_version_id)
    q=plan_source_query(p,run_id=run.run_id,group_id='g',source_name='pubmed',exact_query='"ECMO"[All Fields]')
    return p,run.run_id,q.query_id


def run(pool, command):
    oid=pool.submit(command); until=time.monotonic()+30
    while time.monotonic()<until:
        done=pool.poll(oid)
        if done.state!='running':
            # Drain the tiny supervisor-finalisation interval before resubmission.
            pool._thread.join(2)
            return done
        time.sleep(.01)
    pytest.fail('bounded application operation did not finish')


def cmd(p,operation,**kw):
    return ApplicationCommand.for_project(p,operation,**kw)


def prepare(p,r,eid):
    return cmd(p,'prepare_export',run_id=r,export_id=eid,output_name='summary.xlsx')


def crash_after_prepare(command):
    execute_command(command)
    os._exit(73)


def block_after_prepare(command):
    execute_command(command)
    (Path(command.project_root)/'worker-boundary').write_text('prepared')
    time.sleep(60)
    return {}


def crash_before_final_commit(command):
    from research_y import workbook_exports as exports
    original=exports._append
    def append(db,eid,prior,action,data):
        original(db,eid,prior,action,data)
        if action=='published': os._exit(73)
    exports._append=append
    return execute_command(command)


def test_real_snapshot_and_read_operations_do_not_mutate_research(application):
    p,r,_=application; before=p.database_path.read_bytes()
    with worker.ApplicationWorker() as pool:
        done=run(pool,cmd(p,'inspect',run_id=r))
        assert done.state=='returned'
        s=done.result()['snapshot']
        assert s['selected_run_id']==r and s['report']['status']=='incomplete'
        assert not s['source_retrieval_verified'] and not s['gui_implemented']
    assert p.database_path.read_bytes()==before


def test_real_export_and_explicit_observation_keep_same_id(application):
    p,r,_=application; eid=str(uuid4())
    with worker.ApplicationWorker() as pool:
        first=run(pool,prepare(p,r,eid))
        assert first.state=='returned' and first.result()['state']=='prepared'
        assert not first.result()['audited_success']
        assert run(pool,prepare(p,r,eid)).result()==first.result()
        final=run(pool,cmd(p,'resume_export',export_id=eid)).result()
        assert final['audited_success'] and not final['source_retrieval_verified']
        observed=run(pool,cmd(p,'observe_export',export_id=eid)).result()
        assert observed['outcome']=='published_verified'
        snapshot=run(pool,cmd(p,'inspect',run_id=r)).result()['snapshot']
        assert len(snapshot['exports'])==1 and snapshot['exports'][0]['export_id']==eid
        assert not snapshot['exports'][0]['audited_success']
        report=run(pool,cmd(p,'export_report',export_id=eid)).result()
        assert report['run']['run_id']==r and report['status']=='incomplete'
    content=(p.root/'exports'/'summary.xlsx').read_bytes()
    assert content.startswith(b'PK') and sha256(content).hexdigest()==final['artifact_sha256']


def test_prepare_crash_and_restart_discovers_original_request(application,monkeypatch):
    p,r,_=application; eid=str(uuid4())
    monkeypatch.setattr(worker,'execute_command',crash_after_prepare)
    with worker.ApplicationWorker() as pool:
        assert run(pool,prepare(p,r,eid)).state=='interrupted'
    entries=list_export_requests(open_project(p.root))
    assert len(entries)==1 and entries[0].export_id==eid and entries[0].recorded_state=='prepared'
    monkeypatch.setattr(worker,'execute_command',execute_command)
    with worker.ApplicationWorker() as pool:
        done=run(pool,cmd(open_project(p.root),'resume_export',export_id=eid))
        assert done.result()['audited_success']
    assert len(list_export_requests(p))==1


def test_visible_file_without_receipt_not_success_and_recovers(application,monkeypatch):
    p,r,_=application; eid=str(uuid4())
    with worker.ApplicationWorker() as pool:
        assert run(pool,prepare(p,r,eid)).state=='returned'
    monkeypatch.setattr(worker,'execute_command',crash_before_final_commit)
    with worker.ApplicationWorker() as pool:
        done=run(pool,cmd(p,'resume_export',export_id=eid))
        assert done.state=='interrupted'
    reopened=open_project(p.root)
    assert (p.root/'exports'/'summary.xlsx').exists()
    assert observe_export_request(reopened,eid).outcome=='published_receipt_missing'
    monkeypatch.setattr(worker,'execute_command',execute_command)
    with worker.ApplicationWorker() as pool:
        assert run(pool,cmd(reopened,'resume_export',export_id=eid)).result()['audited_success']


def test_bounded_shutdown_does_not_cancel_a_prepared_export(application,monkeypatch):
    p,r,_=application; eid=str(uuid4())
    monkeypatch.setattr(worker,'execute_command',block_after_prepare)
    pool=worker.ApplicationWorker()
    try:
        oid=pool.submit(prepare(p,r,eid)); until=time.monotonic()+20
        while not (p.root/'worker-boundary').exists() and time.monotonic()<until: time.sleep(.02)
        assert (p.root/'worker-boundary').exists()
    finally:
        pool.close(grace_seconds=0,kill_seconds=1)
    assert pool.poll(oid).state=='interrupted'
    assert list_export_requests(open_project(p.root))[0].recorded_state=='prepared'
    assert not (p.root/'exports'/'summary.xlsx').exists()


def test_changed_source_after_prepare_never_recaptures(application):
    p,r,q=application; eid=str(uuid4())
    with worker.ApplicationWorker() as pool:
        first=run(pool,prepare(p,r,eid)).result()
        with closing(sqlite3.connect(p.database_path)) as db,db:
            db.execute('UPDATE source_queries SET reported_matches=17,status="failed" WHERE query_id=?',(q,))
        last=run(pool,cmd(p,'resume_export',export_id=eid)).result()
    assert last['report_sha256']==first['report_sha256']
    report=read_export_report(p,eid).as_dict()
    assert report['queries'][0]['reported_matches'] is None


def test_project_relocation_and_fresh_worker(application,tmp_path):
    p,r,_=application; eid=str(uuid4())
    with worker.ApplicationWorker() as pool: run(pool,prepare(p,r,eid))
    moved=tmp_path/'relocated'; shutil.move(str(p.root),str(moved)); reopened=open_project(moved)
    with worker.ApplicationWorker() as pool:
        assert run(pool,cmd(reopened,'resume_export',export_id=eid)).result()['audited_success']


@pytest.mark.parametrize('damage,outcome',[('missing','published_file_missing'),('changed','destination_changed')])
def test_changed_workbook_return_is_not_domain_success(application,damage,outcome):
    p,r,_=application; eid=str(uuid4())
    with worker.ApplicationWorker() as pool:
        run(pool,prepare(p,r,eid)); run(pool,cmd(p,'resume_export',export_id=eid))
        path=p.root/'exports'/'summary.xlsx'
        if damage=='missing': path.unlink()
        else: path.write_bytes(b'researcher edit')
        done=run(pool,cmd(p,'observe_export',export_id=eid))
        assert done.state=='returned' and done.result()['outcome']==outcome
        assert not done.result()['audited_success']
        if damage=='changed': assert path.read_bytes()==b'researcher edit'


def test_external_directory_required_again_after_restart(application,tmp_path):
    p,r,_=application; eid=str(uuid4()); external=tmp_path/'chosen'; external.mkdir()
    with worker.ApplicationWorker() as pool:
        assert run(pool,replace(prepare(p,r,eid),directory=str(external))).state=='returned'
        assert run(pool,cmd(p,'resume_export',export_id=eid,directory=str(external))).result()['audited_success']
    with worker.ApplicationWorker() as pool:
        missing=run(pool,cmd(p,'observe_export',export_id=eid)).result()
        assert missing['outcome']=='destination_confirmation_required' and not missing['audited_success']
        assert run(pool,cmd(p,'observe_export',export_id=eid,directory=str(external))).result()['audited_success']


def test_explicit_cancel_is_separate_from_worker_shutdown(application):
    p,r,_=application; eid=str(uuid4())
    with worker.ApplicationWorker() as pool:
        run(pool,prepare(p,r,eid))
        result=run(pool,cmd(p,'cancel_export',export_id=eid)).result()
        assert result['state']=='cancelled' and not result['audited_success']
        failed=run(pool,cmd(p,'resume_export',export_id=eid))
        assert (failed.state,failed.error)==('failed','cancelled')


def test_wrong_expected_project_identity_is_not_reopened_or_repaired(application):
    p,r,_=application; before=p.database_path.read_bytes()
    with worker.ApplicationWorker() as pool:
        done=run(pool,replace(cmd(p,'inspect',run_id=r),project_id=str(uuid4())))
        assert done.state=='failed' and done.error=='invalid_evidence'
    assert p.database_path.read_bytes()==before


def test_unknown_run_and_failed_preparation_no_new_request(application):
    p,_,_=application
    with worker.ApplicationWorker() as pool:
        done=run(pool,prepare(p,str(uuid4()),str(uuid4())))
        assert done.state=='failed'
    assert list_export_requests(p)==()
    assert not list((p.root/'exports').iterdir())


def test_audit_failure_has_no_optimistic_success(application):
    p,r,_=application
    with closing(sqlite3.connect(p.database_path)) as db,db:
        db.execute("CREATE TRIGGER reject_worker_export BEFORE INSERT ON audit_events WHEN NEW.event_type LIKE 'workbook_export_v1:%' BEGIN SELECT RAISE(ABORT,'synthetic'); END")
    with worker.ApplicationWorker() as pool:
        done=run(pool,prepare(p,r,str(uuid4())))
        assert done.state=='failed' and done.error=='journal_failed'
    assert list_export_requests(p)==()


def test_busy_read_is_bounded_and_does_not_fabricate_empty_data(application):
    p,r,_=application
    with closing(sqlite3.connect(p.database_path)) as db:
        db.execute('BEGIN EXCLUSIVE')
        try:
            with worker.ApplicationWorker() as pool:
                done=run(pool,cmd(p,'inspect',run_id=r))
                assert (done.state,done.error,done.result())==('failed','project_busy',None)
        finally: db.rollback()
