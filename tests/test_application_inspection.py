"""Real application/read-only journal integration; no live providers or GUI."""
from contextlib import closing
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from uuid import uuid4

import pytest
from research_y import application_inspection as app
from research_y import workbook_exports as exports
from research_y.projects import create_project, open_project
from research_y.storage import ApprovedTerm, StrategyGroup, approve_strategy, create_search_run, plan_source_query
from test_workbook_export_integration import application, research_dump


def dump(p):
    with closing(sqlite3.connect(p.database_path)) as db:
        return '\n'.join(db.iterdump())


def prepare(f, name='summary.xlsx', **kwargs):
    p,run,_=f; eid=str(uuid4())
    exports.prepare_workbook_export(p,run,name,export_id=eid,**kwargs)
    return eid


def test_empty_real_project_inspection_does_not_create_runs_or_exports(tmp_path):
    p=create_project(tmp_path,'Empty'); before=dump(p)
    snapshot=app.read_application_snapshot(p).as_dict()
    assert snapshot['runs']==snapshot['exports']==[]
    assert snapshot['selected_run_id'] is None and snapshot['report'] is None
    assert snapshot['last_recorded_audit_event']['event_id']==1
    assert snapshot['last_successful_source_checkpoint'] is None
    assert dump(p)==before and not list((p.root/'exports').iterdir())


def test_real_snapshot_retains_unknown_zero_query_text_and_warning_scope(application):
    p,run,qid=application; before=dump(p)
    result=app.read_application_snapshot(p,selected_run_id=run).as_dict()
    assert len(result['runs'])==1 and result['runs'][0]['run_id']==run
    assert result['report']['run']['run_id']==run
    assert result['report']['queries'][0]['exact_query']=='"ECMO"[All Fields]'
    assert result['report']['queries'][0]['reported_matches'] is None
    assert result['report']['counts']['queries'][0]['metadata_source_records']==0
    assert result['report']['counts']['totals']['global_unique_publications'] is None
    assert result['report']['status']=='incomplete' and not result['source_retrieval_verified']
    assert result['report']['warnings'] and dump(p)==before
    with closing(sqlite3.connect(p.database_path)) as db,db:
        db.execute('UPDATE source_queries SET reported_matches=0 WHERE query_id=?',(qid,))
    assert app.read_application_snapshot(p,selected_run_id=run).as_dict()['report']['queries'][0]['reported_matches']==0


def test_published_inventory_requires_separate_current_file_observation(application,monkeypatch):
    p,run,_=application; eid=prepare(application)
    exports.resume_workbook_export(p,eid)
    before=dump(p)
    def forbidden(*_,**__): pytest.fail('inspection attempted a write or render')
    monkeypatch.setattr(exports,'_append',forbidden)
    monkeypatch.setattr(exports,'_renderer',forbidden)
    entry,=app.list_export_requests(p)
    assert entry.export_id==eid and entry.run_id==run and entry.recorded_state=='published'
    assert not entry.audited_success and not entry.files_checked
    observed=app.observe_export_request(p,eid)
    assert observed.outcome=='published_verified' and observed.audited_success
    assert not observed.source_retrieval_verified and not observed.request.source_retrieval_verified
    assert dump(p)==before


def test_inventory_does_not_open_artifact_files(application,monkeypatch):
    p,_,_=application; eid=prepare(application); exports.resume_workbook_export(p,eid)
    monkeypatch.setattr(exports,'_store',lambda *_,**__:pytest.fail('artifact opened during inventory'))
    assert app.list_export_requests(p)[0].export_id==eid


def test_retry_and_reopen_keep_same_request_and_original_report(application):
    p,run,qid=application; eid=prepare(application)
    before=app.read_export_report(p,eid)
    with closing(sqlite3.connect(p.database_path)) as db,db:
        db.execute('UPDATE source_queries SET reported_matches=17,status="failed" WHERE query_id=?',(qid,))
    exports.prepare_workbook_export(p,run,'summary.xlsx',export_id=eid)
    reopened=open_project(p.root)
    entries=app.list_export_requests(reopened)
    assert len(entries)==1 and entries[0].export_id==eid
    assert app.read_export_report(reopened,eid).payload_json==before.payload_json
    assert before.as_dict()['queries'][0]['reported_matches'] is None
    current=app.read_application_snapshot(reopened,selected_run_id=run).as_dict()
    assert current['report']['queries'][0]['reported_matches']==17
    assert current['exports'][0]['report_sha256']==before.sha256


@pytest.mark.parametrize('phase',['prepared','staging','staged','publishing','cancelled','published'])
def test_all_durable_phases_discoverable_without_repair(application,phase):
    p,_,_=application; eid=prepare(application); cached=None
    if phase=='cancelled': exports.cancel_workbook_export(p,eid)
    elif phase=='published': exports.resume_workbook_export(p,eid)
    else:
        for _ in range(5):
            if app.list_export_requests(p)[0].recorded_state==phase: break
            _,cached=exports._step(p,eid,None,cached)
    before=dump(p)
    entry,=app.list_export_requests(open_project(p.root))
    assert entry.recorded_state==phase and not entry.audited_success
    assert entry.worker_status=='unknown' and dump(p)==before


@pytest.mark.parametrize('damage,expected',[
    ('output-missing','published_file_missing'),('output-changed','destination_changed'),
    ('original-missing','retained_artifact_missing'),('original-changed','retained_artifact_changed')])
def test_file_damage_cannot_reuse_success_receipt(application,damage,expected):
    p,_,_=application; eid=prepare(application); exports.resume_workbook_export(p,eid)
    assert app.observe_export_request(p,eid).audited_success
    if damage.startswith('original'):
        with exports._transaction(p,write=False) as db:
            state=exports._required(db,p,eid)
        path=p.root/'exports'/exports.STORE/state['stage']['name']
    else: path=p.root/'exports'/'summary.xlsx'
    if damage.endswith('missing'): path.unlink()
    else: path.write_bytes(b'CHANGED')
    before=dump(p)
    observed=app.observe_export_request(p,eid)
    assert observed.outcome==expected and not observed.audited_success
    assert observed.request.recorded_state=='published' and dump(p)==before


def test_external_recovery_requires_reselection_without_persisting_path(application,tmp_path):
    p,_,_=application; target=tmp_path/'external'; target.mkdir(); wrong=tmp_path/'wrong'; wrong.mkdir()
    eid=prepare(application,directory=target); exports.resume_workbook_export(p,eid,directory=target)
    before=dump(p)
    assert app.observe_export_request(p,eid).outcome=='destination_confirmation_required'
    assert app.observe_export_request(p,eid,directory=wrong).outcome=='destination_directory_changed'
    assert app.observe_export_request(p,eid,directory=target).audited_success
    assert str(target) not in app.read_application_snapshot(p).payload_json
    assert str(target) not in dump(p) and dump(p)==before


def test_relocation_preserves_inventory_and_default_artifact_verification(application,tmp_path):
    p,run,_=application; eid=prepare(application); exports.resume_workbook_export(p,eid)
    original=app.read_export_report(p,eid)
    moved=tmp_path/'moved'; shutil.move(str(p.root),str(moved)); reopened=open_project(moved)
    assert app.list_export_requests(reopened)[0].export_id==eid
    assert app.observe_export_request(reopened,eid).audited_success
    snapshot=app.read_application_snapshot(reopened,selected_run_id=run)
    assert snapshot.location==moved and str(moved) not in snapshot.payload_json
    assert app.read_export_report(reopened,eid).payload_json==original.payload_json


def test_one_snapshot_across_concurrent_run_and_export_updates(application,monkeypatch):
    p,run,qid=application; eid=prepare(application)
    with closing(sqlite3.connect(p.database_path)) as db:
        assert db.execute('PRAGMA journal_mode=WAL').fetchone()[0]=='wal'
    original=app._inventory
    def intervening(db,project):
        result=original(db,project)
        exports.cancel_workbook_export(p,eid)
        with closing(sqlite3.connect(p.database_path)) as writer,writer:
            writer.execute('UPDATE search_runs SET status="failed" WHERE run_id=?',(run,))
            writer.execute('UPDATE source_queries SET reported_matches=99 WHERE query_id=?',(qid,))
        return result
    monkeypatch.setattr(app,'_inventory',intervening)
    frozen=app.read_application_snapshot(p,selected_run_id=run).as_dict()
    assert frozen['runs'][0]['stored_status']==frozen['report']['run']['status']=='pending'
    assert frozen['report']['queries'][0]['reported_matches'] is None
    assert frozen['exports'][0]['recorded_state']=='prepared'
    monkeypatch.undo()
    later=app.read_application_snapshot(p,selected_run_id=run).as_dict()
    assert later['runs'][0]['stored_status']==later['report']['run']['status']=='failed'
    assert later['exports'][0]['recorded_state']=='cancelled'
    assert later['report']['status']=='incomplete' and not later['source_retrieval_verified']
    assert later['report']['queries'][0]['reported_matches']==99


@pytest.mark.parametrize('stage',['before-prepared-commit','before-published-commit'])
def test_actual_child_crash_is_discovered_without_false_success(application,stage):
    p,run,_=application; eid=str(uuid4())
    code=r'''
import os,sys
from research_y import workbook_exports as e
from research_y.projects import open_project
p=open_project(sys.argv[1]); run,eid,stage=sys.argv[2:]
original=e._append
def append(db,export_id,previous,kind,data):
    original(db,export_id,previous,kind,data)
    if (kind=='prepared' and stage=='before-prepared-commit') or (kind=='published' and stage=='before-published-commit'):
        os._exit(73)
e._append=append
e.prepare_workbook_export(p,run,'crash.xlsx',export_id=eid)
e.resume_workbook_export(p,eid)
'''
    env=dict(os.environ); env['PYTHONPATH']=str(Path(__file__).parents[1]/'src')+os.pathsep+env.get('PYTHONPATH','')
    result=subprocess.run([sys.executable,'-c',code,str(p.root),run,eid,stage],env=env,capture_output=True,timeout=45)
    assert result.returncode==73,(result.stdout,result.stderr)
    reopened=open_project(p.root)  # Explicit normal hot-journal recovery first.
    before=dump(reopened)
    if stage=='before-prepared-commit':
        assert app.list_export_requests(reopened)==()
        assert not (p.root/'exports'/'crash.xlsx').exists()
    else:
        entry,=app.list_export_requests(reopened)
        assert entry.export_id==eid and entry.recorded_state=='publishing'
        assert app.observe_export_request(reopened,eid).outcome=='published_receipt_missing'
        assert not app.observe_export_request(reopened,eid).audited_success
        assert dump(reopened)==before
        exports.resume_workbook_export(reopened,entry.export_id)
        assert app.observe_export_request(reopened,entry.export_id).audited_success


def test_identical_unrelated_visible_file_not_reconciled_by_observation(application):
    p,_,_=application; eid=prepare(application); cached=None
    for _ in range(3): _,cached=exports._step(p,eid,None,cached)
    with exports._transaction(p,write=False) as db: state=exports._required(db,p,eid)
    assert state['state']=='publishing'
    original=p.root/'exports'/exports.STORE/state['stage']['name']
    (p.root/'exports'/'summary.xlsx').write_bytes(original.read_bytes())
    before=dump(p)
    assert app.observe_export_request(p,eid).outcome=='destination_conflict'
    assert dump(p)==before


@pytest.mark.parametrize('damage',['hash','timestamp','namespace','future','invalid-json'])
def test_corrupt_or_unknown_journal_never_becomes_empty_inventory(application,damage):
    p,_,_=application; prepare(application)
    with closing(sqlite3.connect(p.database_path)) as db,db:
        triggers=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='audit_events'")]
        for name in triggers: db.execute('DROP TRIGGER "'+name+'"')
        row=db.execute('SELECT event_id,details_json FROM audit_events WHERE event_type LIKE ?', (exports.EVENT+':%',)).fetchone()
        if damage=='hash':
            raw=json.loads(row[1]); raw['sha256']='0'*64
            db.execute('UPDATE audit_events SET details_json=? WHERE event_id=?',(json.dumps(raw),row[0]))
        elif damage=='timestamp': db.execute("UPDATE audit_events SET occurred_at_utc='2000-01-01T00:00:00+00:00' WHERE event_id=?",(row[0],))
        elif damage=='namespace': db.execute("UPDATE audit_events SET event_type='workbook_export_v1:bad' WHERE event_id=?",(row[0],))
        elif damage=='future': db.execute("UPDATE audit_events SET event_type=replace(event_type,'v1:','v2:') WHERE event_id=?",(row[0],))
        else: db.execute("UPDATE audit_events SET details_json='PRIVATE INVALID' WHERE event_id=?",(row[0],))
    before=dump(p)
    with pytest.raises(app.ApplicationInspectionError) as error: app.list_export_requests(p)
    assert 'PRIVATE' not in str(error.value) and dump(p)==before


@pytest.mark.parametrize('damage',['manifest','schema','foreign-key'])
def test_invalid_project_fails_readonly_without_repair(application,damage):
    p,_,_=application
    if damage=='manifest':
        raw=json.loads(p.manifest_path.read_text()); raw['project_id']=str(uuid4()); p.manifest_path.write_text(json.dumps(raw))
    else:
        with closing(sqlite3.connect(p.database_path)) as db,db:
            if damage=='schema': db.execute('PRAGMA user_version=999')
            else: db.execute('UPDATE search_runs SET strategy_version_id=?',(str(uuid4()),))
    before=dump(p)
    with pytest.raises(app.ApplicationInspectionError): app.read_application_snapshot(p)
    assert dump(p)==before


def test_unapproved_parameter_never_leaks_through_selected_run(application):
    p,run,qid=application
    with closing(sqlite3.connect(p.database_path)) as db,db:
        db.execute('UPDATE source_queries SET parameters_json=? WHERE query_id=?',(json.dumps({'api_key':'PRIVATE SECRET'}),qid))
    with pytest.raises(app.ApplicationInspectionError) as error: app.read_application_snapshot(p,selected_run_id=run)
    assert 'PRIVATE SECRET' not in str(error.value)


def test_project_text_retained_as_data_not_browser_markup(application):
    p,run,_=application
    with closing(sqlite3.connect(p.database_path)) as db,db:
        db.execute('UPDATE project_metadata SET theme=? WHERE singleton_id=1',('<script>alert(1)</script>',))
    snap=app.read_application_snapshot(p,selected_run_id=run)
    assert snap.as_dict()['project']['theme']=='<script>alert(1)</script>'
    assert not snap.as_dict()['gui_implemented']  # NOT a claim of browser escaping acceptance.


def test_every_run_and_export_retained_without_implicit_latest_selection(application):
    p,first,_=application
    with closing(sqlite3.connect(p.database_path)) as db: sid=db.execute('SELECT strategy_version_id FROM search_runs WHERE run_id=?',(first,)).fetchone()[0]
    second=create_search_run(p,sid)
    for n in range(8): prepare(application,name=f'{n}.xlsx')
    snap=app.read_application_snapshot(p).as_dict()
    assert {r['run_id'] for r in snap['runs']}=={first,second.run_id}
    assert len(snap['exports'])==8 and snap['selected_run_id'] is None
    assert snap['report'] is None and all(not r['audited_success'] for r in snap['exports'])


def test_recorded_failure_is_visible_without_claiming_worker_death(application,monkeypatch):
    p,_,_=application; eid=prepare(application)
    def fail(*_): raise exports.WorkbookExportError('render_failed',eid)
    monkeypatch.setattr(exports,'_render',fail)
    with pytest.raises(exports.WorkbookExportError): exports.resume_workbook_export(p,eid)
    entry,=app.list_export_requests(p)
    assert entry.recorded_state=='prepared' and entry.last_error=='render_failed'
    assert entry.worker_status=='unknown' and not entry.audited_success


def test_read_connection_enforces_query_only(application):
    p,_,_=application; before=dump(p)
    with app._read(p) as db:
        with pytest.raises(sqlite3.OperationalError):
            db.execute("UPDATE project_metadata SET theme='NOT ALLOWED'")
    assert dump(p)==before


# Existing fixture deliberately covers two sources and two reporting groups.
from test_strategy_report import prepared, add


def test_cross_source_group_identity_denominators_remain_distinct(prepared):
    from research_y import publication_identity as identity
    f=prepared
    a,b=add(f,'pubmed','123'),add(f,'wos','WOS:123')
    pa=identity.materialise_retrieval(f.project,a,actor='Fixture')
    pb=identity.materialise_retrieval(f.project,b,actor='Fixture')
    identity.associate_retrieval(f.project,a,pb.publication_id,
        expected_source_revision=pa.revision,expected_target_revision=pb.revision,
        actor='Fixture',evidence='Synthetic confirmed match',same_publication_confirmed=True)
    before=dump(f.project)
    data=app.read_application_snapshot(f.project,selected_run_id=f.run).as_dict()
    counts=data['report']['counts']
    assert counts['totals']['global_publication_identities']==1
    assert counts['totals']['group_publication_identity_sum']==2
    assert [s['source_unique_records'] for s in counts['sources']]==[1,1]
    assert counts['totals']['global_unique_publications'] is None
    assert 'PRIVATE TITLE' not in json.dumps(data) and 'PRIVATE ABSTRACT' not in json.dumps(data)
    assert dump(f.project)==before
