"""Export protocol on real SQLite/files, isolated from application capture/rendering.

Only the existing project opener and workbook renderer are substituted here.
The separate integration suite exercises them against actual project databases.
"""
from contextlib import closing, contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4
import json
import os
import shutil
import sqlite3
import subprocess
import sys

import pytest
from research_y import workbook_exports as exports
from research_y.strategy_report import StrategyReport, canonical, digest

P, R, S = (str(UUID(int=i)) for i in (1, 2, 3))
STAMP = '2026-11-01T20:45:00+00:00'


def report_payload(value='original'):
    counts = dict(project_id=P, run_id=R, strategy_version_id=S, stored_run_status='incomplete',
                  revision='a'*64, status='incomplete', queries=[], groups=[], sources=[], totals={}, reviews={}, warnings=[])
    for key in ('verified_complete','deduplication_complete','source_retrieval_verified','candidate_discovery_complete',
                'historical_snapshot','full_checkpoint_validation_performed','export_permissions_verified'):
        counts[key] = False
    return dict(format_version=1, method='strategy-count-report/1', scope='whole_run_strategy_and_counts',
        status='incomplete', captured_at_utc=STAMP, project=dict(project_id=P, name='Protocol fixture'),
        run=dict(run_id=R, strategy_version_id=S, status='incomplete'), counts=counts, queries=[], partitions=[], warnings=[],
        strategy=dict(snapshot=dict(format_version=1, theme=value, logic='OR', approved_by='Fixture',
            groups=[dict(group_id='g', label='Group', group_order=0, terms=[])]), group_index=[['g','Group',0]]))


def install_protocol(root, monkeypatch=None):
    root = Path(root)
    p = SimpleNamespace(root=root, identifier=UUID(P), name='Protocol fixture', created_at_utc=STAMP,
                        database_path=root / 'database.sqlite3')
    @contextmanager
    def transaction(project, *, write=True):
        with closing(sqlite3.connect(project.database_path, timeout=5)) as db, db:
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield db
    def capture(db, project, run_id):
        assert run_id == R
        value = db.execute('SELECT value FROM research').fetchone()[0]
        return StrategyReport(canonical(report_payload(value)))
    def renderer():
        return 'protocol-fixture/1', lambda report: b'NOT-AN-XLSX-PROTOCOL-FIXTURE:' + report.sha256.encode()
    for name, value in (('_transaction',transaction),('_capture',capture),('_renderer',renderer)):
        if monkeypatch is None:
            setattr(exports, name, value)
        else:
            monkeypatch.setattr(exports, name, value)
    return p


@pytest.fixture
def protocol(tmp_path, monkeypatch):
    (tmp_path / 'exports').mkdir()
    with closing(sqlite3.connect(tmp_path / 'database.sqlite3')) as db, db:
        db.executescript('CREATE TABLE audit_events(event_id INTEGER PRIMARY KEY AUTOINCREMENT, occurred_at_utc TEXT, event_type TEXT, details_json TEXT);'
                        'CREATE TABLE search_runs(run_id TEXT PRIMARY KEY,strategy_version_id TEXT); CREATE TABLE research(value TEXT);')
        db.execute('INSERT INTO search_runs VALUES(?,?)', (R,S))
        db.execute('INSERT INTO research VALUES(?)', ('original',))
    return install_protocol(tmp_path, monkeypatch)


def prepare(p, *, name='report.xlsx', directory=None, export_id=None):
    return exports.prepare_workbook_export(p, R, name, export_id=export_id or str(uuid4()), directory=directory)


def load(p, eid):
    with exports._transaction(p, write=False) as db:
        return exports._required(db,p,eid)


def events(p):
    with exports._transaction(p, write=False) as db:
        return [json.loads(r[0]) for r in db.execute('SELECT details_json FROM audit_events ORDER BY event_id')]


def advance(p, eid, target_phase, directory=None):
    cached = None
    for _ in range(12):
        if load(p,eid)['state'] == target_phase:
            return
        _, cached = exports._step(p,eid,directory,cached)
    raise AssertionError('phase not reached')


def test_prepared_snapshot_once_and_retries_do_not_recapture(protocol,monkeypatch):
    p=protocol; first=prepare(p)
    assert first.state=='prepared' and not first.audited_success
    with exports._transaction(p) as db:
        db.execute('UPDATE research SET value="changed"')
    monkeypatch.setattr(exports,'_capture',lambda *a: pytest.fail('unexpected recapture'))
    again=prepare(p,export_id=first.export_id)
    assert again==first
    result=exports.resume_workbook_export(p,first.export_id)
    assert result.audited_success and result.report_sha256==first.report_sha256
    assert 'original' in load(p,first.export_id)['report_json']
    assert 'changed' not in load(p,first.export_id)['report_json']
    assert not result.source_retrieval_verified and result.report_status=='incomplete'


def test_exact_published_retry_and_independent_retained_artifact(protocol):
    p=protocol; first=prepare(p); eid=first.export_id
    done=exports.resume_workbook_export(p,eid)
    before=events(p)
    assert [e['action'] for e in before]==['prepared','staging','staged','publishing','published']
    assert exports.resume_workbook_export(p,eid)==done and events(p)==before
    state=load(p,eid)
    retained=p.root/'exports'/exports.STORE/state['stage']['name']
    final=p.root/'exports'/'report.xlsx'
    assert not os.path.samefile(retained,final)
    original=retained.read_bytes(); final.write_bytes(b'edited workbook')
    assert retained.read_bytes()==original
    with pytest.raises((ValueError,OSError)):
        exports.inspect_workbook_export(p,eid)
    with pytest.raises(exports.WorkbookExportError):
        exports.resume_workbook_export(p,eid)
    assert final.read_bytes()==b'edited workbook'


@pytest.mark.parametrize('phase',['prepared','staging','staged','publishing','published'])
def test_audit_failure_never_reports_success_and_can_recover(protocol,monkeypatch,phase):
    p=protocol; eid=str(uuid4()); original=exports._append
    def broken(db,export_id,previous,action,data):
        if action==phase:
            raise sqlite3.OperationalError('private diagnostic')
        return original(db,export_id,previous,action,data)
    monkeypatch.setattr(exports,'_append',broken)
    with pytest.raises(exports.WorkbookExportError) as err:
        prepare(p,export_id=eid)
        exports.resume_workbook_export(p,eid)
    assert 'private diagnostic' not in str(err.value)
    assert not any(e['action']=='published' for e in events(p))
    monkeypatch.setattr(exports,'_append',original)
    prepare(p,export_id=eid)
    assert exports.resume_workbook_export(p,eid).audited_success


def test_render_failure_is_durable_and_static(protocol,monkeypatch):
    first=prepare(protocol)
    def bad(*a):
        raise RuntimeError('PRIVATE RENDER ERROR')
    monkeypatch.setattr(exports,'_renderer',lambda:('protocol-fixture/1',bad))
    with pytest.raises(exports.WorkbookExportError,match='render_failed'):
        exports.resume_workbook_export(protocol,first.export_id)
    assert load(protocol,first.export_id)['last_error']=='render_failed'
    assert 'PRIVATE' not in canonical(events(protocol))
    assert not (protocol.root/'exports'/'report.xlsx').exists()


@pytest.mark.parametrize('kind',['short-then-fail','permission','flush'])
def test_failed_stage_keeps_snapshot_and_retry_never_overwrites_partial(protocol,monkeypatch,kind):
    p=protocol; first=prepare(p); original=exports.Directory.write_new
    def bad(self,name,data):
        if kind=='short-then-fail':
            original(self,name,data[:5])
        if kind=='flush':
            original(self,name,data)
        raise OSError('disk full or private permission path')
    monkeypatch.setattr(exports.Directory,'write_new',bad)
    with pytest.raises(exports.WorkbookExportError):
        exports.resume_workbook_export(p,first.export_id)
    before={x.name:x.read_bytes() for x in (p.root/'exports'/exports.STORE).iterdir()}
    monkeypatch.setattr(exports.Directory,'write_new',original)
    result=exports.resume_workbook_export(p,first.export_id)
    assert result.audited_success and result.report_sha256==first.report_sha256
    for name,content in before.items():
        assert (p.root/'exports'/exports.STORE/name).read_bytes()==content


@pytest.mark.parametrize('when',['before-prepare','after-prepare','during-link'])
def test_destination_races_do_not_overwrite_other_files(protocol,monkeypatch,when):
    p=protocol; path=p.root/'exports'/'report.xlsx'
    if when=='before-prepare':
        path.write_bytes(b'keep')
        with pytest.raises(exports.WorkbookExportError,match='destination_conflict'):
            prepare(p)
        assert events(p)==[]
        return
    first=prepare(p)
    if when=='after-prepare':
        path.write_bytes(b'keep')
    else:
        original=exports.Directory.publish_link
        def race(self,stage,target):
            (self.path/target).write_bytes(b'keep')
            original(self,stage,target)
        monkeypatch.setattr(exports.Directory,'publish_link',race)
    with pytest.raises(exports.WorkbookExportError,match='destination_conflict'):
        exports.resume_workbook_export(p,first.export_id)
    assert path.read_bytes()==b'keep'
    assert not exports.inspect_workbook_export(p,first.export_id).audited_success


def test_identical_unrelated_destination_is_not_adopted(protocol):
    p=protocol; first=prepare(p); advance(p,first.export_id,'publishing')
    state=load(p,first.export_id)
    data=(p.root/'exports'/exports.STORE/state['stage']['name']).read_bytes()
    (p.root/'exports'/'report.xlsx').write_bytes(data)
    with pytest.raises(exports.WorkbookExportError,match='destination_conflict'):
        exports.resume_workbook_export(p,first.export_id)


def test_no_destructive_fallback_on_unsupported_link(protocol,monkeypatch):
    first=prepare(protocol)
    def unsupported(*a):
        raise OSError('unsupported filesystem')
    monkeypatch.setattr(exports.Directory,'publish_link',unsupported)
    with pytest.raises(exports.WorkbookExportError,match='storage_failed'):
        exports.resume_workbook_export(protocol,first.export_id)
    assert load(protocol,first.export_id)['state']=='publishing'
    assert not (protocol.root/'exports'/'report.xlsx').exists()


def test_external_destination_identity_and_no_absolute_path_in_journal(protocol,tmp_path):
    p=protocol; external=tmp_path.with_name(tmp_path.name+'-external'); external.mkdir()
    first=prepare(p,directory=external)
    with pytest.raises(exports.WorkbookExportError,match='destination_required'):
        exports.resume_workbook_export(p,first.export_id)
    other=tmp_path.with_name(tmp_path.name+'-other'); other.mkdir()
    with pytest.raises(exports.WorkbookExportError,match='directory_changed'):
        exports.resume_workbook_export(p,first.export_id,directory=other)
    result=exports.resume_workbook_export(p,first.export_id,directory=external)
    assert result.audited_success and (external/'report.xlsx').exists()
    assert str(tmp_path) not in canonical(events(p))
    assert not (p.root/'exports'/'report.xlsx').exists()


@pytest.mark.parametrize('phase',['prepared','staging','staged','publishing'])
def test_cancel_is_terminal_idempotent_and_deletes_nothing(protocol,phase):
    p=protocol; first=prepare(p); advance(p,first.export_id,phase)
    before={x: x.read_bytes() for x in (p.root/'exports').rglob('*') if x.is_file()}
    result=exports.cancel_workbook_export(p,first.export_id)
    assert result.state=='cancelled' and not result.audited_success
    assert exports.cancel_workbook_export(p,first.export_id)==result
    with pytest.raises(exports.WorkbookExportError,match='cancelled'):
        exports.resume_workbook_export(p,first.export_id)
    assert all(x.read_bytes()==value for x,value in before.items())


def test_visible_unreceipted_output_requires_recovery_not_cancel(protocol,monkeypatch):
    p=protocol; first=prepare(p); original=exports._append
    def fail_final(db,eid,previous,action,data):
        if action=='published':
            raise sqlite3.OperationalError('failure')
        return original(db,eid,previous,action,data)
    monkeypatch.setattr(exports,'_append',fail_final)
    with pytest.raises(exports.WorkbookExportError):
        exports.resume_workbook_export(p,first.export_id)
    assert (p.root/'exports'/'report.xlsx').exists()
    with pytest.raises(exports.WorkbookExportError):
        exports.cancel_workbook_export(p,first.export_id)
    monkeypatch.setattr(exports,'_append',original)
    assert exports.resume_workbook_export(p,first.export_id).audited_success


def test_staged_artifact_corruption_refuses_regeneration(protocol):
    p=protocol; first=prepare(p); advance(p,first.export_id,'staged'); state=load(p,first.export_id)
    path=p.root/'exports'/exports.STORE/state['stage']['name']; path.write_bytes(b'wrong')
    with pytest.raises(exports.WorkbookExportError,match='artifact_changed'):
        exports.resume_workbook_export(p,first.export_id)
    assert path.read_bytes()==b'wrong'
    assert not (p.root/'exports'/'report.xlsx').exists()


def test_complete_export_survives_project_copy(protocol,tmp_path,monkeypatch):
    p=protocol; first=prepare(p); exports.resume_workbook_export(p,first.export_id)
    copied=tmp_path.parent/(tmp_path.name+'-moved'); shutil.copytree(p.root,copied)
    moved=install_protocol(copied,monkeypatch)
    assert exports.inspect_workbook_export(moved,first.export_id).audited_success
    assert exports.resume_workbook_export(moved,first.export_id).report_sha256==first.report_sha256


@pytest.mark.parametrize('damage',['digest','predecessor','transition','snapshot','extra','future-method'])
def test_corrupt_receipts_fail_closed(protocol,damage):
    p=protocol; first=prepare(p)
    with exports._transaction(p) as db:
        event_id,raw=db.execute('SELECT event_id,details_json FROM audit_events').fetchone()
        event=json.loads(raw)
        if damage=='digest': event['sha256']='f'*64
        else:
            if damage=='predecessor': event['previous_event_id']=event_id
            elif damage=='transition': event['action']='published'
            elif damage=='snapshot': event['data']['report_sha256']='b'*64
            elif damage=='extra': event['data']['extra']='not allowed'
            else: event['method']='future/2'
            event.pop('sha256'); event['sha256']=digest(canonical(event))
        db.execute('UPDATE audit_events SET details_json=? WHERE event_id=?',(canonical(event),event_id))
    with pytest.raises(exports.WorkbookExportError,match='invalid_export'):
        exports.resume_workbook_export(p,first.export_id)
    assert not (p.root/'exports'/'report.xlsx').exists()


def child(p,eid,mode):
    code = r'''
import os,sys,sqlite3
from test_workbook_export_protocol import install_protocol, R
from research_y import workbook_exports as e
p=install_protocol(sys.argv[1]); eid=sys.argv[2]; mode=sys.argv[3]
original=e._append

def append(db,export_id,previous,action,data):
    original(db,export_id,previous,action,data)
    if mode=='before-'+action+'-commit': os._exit(71)
e._append=append
e.prepare_workbook_export(p,R,'report.xlsx',export_id=eid)
if mode=='after-prepared-commit': os._exit(71)
if mode in ('after-staging-commit','after-publishing-commit'):
    target=mode.split('-')[1]; cache=None
    for _ in range(10):
        _,cache=e._step(p,eid,None,cache)
        with e._transaction(p,write=False) as db:
            if e._required(db,p,eid)['state']==target: os._exit(71)
e.resume_workbook_export(p,eid)
if mode=='after-published-commit': os._exit(71)
'''
    env=dict(os.environ)
    env['PYTHONPATH']=os.pathsep.join([str(Path(__file__).parent),str(Path(__file__).parents[1]/'src'),env.get('PYTHONPATH','')])
    return subprocess.Popen([sys.executable,'-c',code,str(p.root),eid,mode],env=env,
                            stdout=subprocess.PIPE,stderr=subprocess.PIPE)


@pytest.mark.parametrize('boundary',['before-prepared-commit','after-prepared-commit','after-staging-commit',
    'before-staged-commit','after-publishing-commit','before-published-commit','after-published-commit'])
def test_actual_child_termination_recovers_each_durable_boundary(protocol,boundary):
    p=protocol; eid=str(uuid4()); proc=child(p,eid,boundary); out,err=proc.communicate(timeout=30)
    assert proc.returncode==71, (out,err)
    if boundary!='after-published-commit':
        assert not any(e['action']=='published' for e in events(p))
    prepare(p,export_id=eid)
    assert exports.resume_workbook_export(p,eid).audited_success
    assert sum(e['action']=='published' for e in events(p))==1


def test_two_process_retries_commit_one_publication(protocol):
    p=protocol; first=prepare(p)
    processes=[child(p,first.export_id,'resume') for _ in range(2)]
    for proc in processes:
        out,err=proc.communicate(timeout=30)
        assert proc.returncode==0, (out,err)
    assert sum(e['action']=='published' for e in events(p))==1
    assert exports.inspect_workbook_export(p,first.export_id).audited_success


def test_two_exports_compete_without_overwriting(protocol):
    p=protocol; a=prepare(p); b=prepare(p)
    result=exports.resume_workbook_export(p,a.export_id)
    original=(p.root/'exports'/'report.xlsx').read_bytes()
    with pytest.raises(exports.WorkbookExportError,match='destination_conflict'):
        exports.resume_workbook_export(p,b.export_id)
    assert exports.inspect_workbook_export(p,a.export_id).audited_success
    assert (p.root/'exports'/'report.xlsx').read_bytes()==original
    assert result.artifact_sha256==digest(original)


def test_publishing_partial_copy_is_retained_and_retried(protocol):
    p=protocol; first=prepare(p); advance(p,first.export_id,'publishing')
    state=load(p,first.export_id); partial=p.root/'exports'/state['publication']['name']
    partial.write_bytes(b'partial')
    assert exports.resume_workbook_export(p,first.export_id).audited_success
    assert partial.read_bytes()==b'partial'


def test_staged_recovery_needs_no_renderer(protocol,monkeypatch):
    p=protocol; first=prepare(p); advance(p,first.export_id,'staged')
    monkeypatch.setattr(exports,'_renderer',lambda:pytest.fail('unexpected re-render'))
    assert exports.resume_workbook_export(p,first.export_id).audited_success


def test_incompatible_renderer_does_not_silently_change_output(protocol,monkeypatch):
    first=prepare(protocol)
    monkeypatch.setattr(exports,'_renderer',lambda:('other/2',lambda _:b'other'))
    with pytest.raises(exports.WorkbookExportError,match='render_failed'):
        exports.resume_workbook_export(protocol,first.export_id)
    assert load(protocol,first.export_id)['state']=='prepared'


def test_changed_request_for_same_id_and_cancelled_success_are_refused(protocol):
    p=protocol; first=prepare(p)
    with pytest.raises(exports.WorkbookExportError,match='invalid_export'):
        prepare(p,name='different.xlsx',export_id=first.export_id)
    exports.resume_workbook_export(p,first.export_id)
    with pytest.raises(exports.WorkbookExportError):
        exports.cancel_workbook_export(p,first.export_id)
    assert exports.inspect_workbook_export(p,first.export_id).audited_success


def test_flush_failure_after_link_requires_recovery(protocol,monkeypatch):
    p=protocol; first=prepare(p); original=exports.Directory.sync
    def fail_after_link(self):
        if (self.path/'report.xlsx').exists():
            raise OSError('directory flush failed')
        return original(self)
    monkeypatch.setattr(exports.Directory,'sync',fail_after_link)
    with pytest.raises(exports.WorkbookExportError,match='storage_failed'):
        exports.resume_workbook_export(p,first.export_id)
    assert (p.root/'exports'/'report.xlsx').exists()
    assert load(p,first.export_id)['state']=='publishing'
    with pytest.raises(exports.WorkbookExportError):
        exports.resume_workbook_export(p,first.export_id)
    monkeypatch.setattr(exports.Directory,'sync',original)
    assert exports.resume_workbook_export(p,first.export_id).audited_success


def test_unknown_id_and_invalid_bytes_cannot_be_published(protocol,monkeypatch):
    with pytest.raises(exports.WorkbookExportError,match='unknown_export'):
        exports.resume_workbook_export(protocol,str(uuid4()))
    first=prepare(protocol)
    monkeypatch.setattr(exports,'_renderer',lambda:('protocol-fixture/1',lambda _:b''))
    with pytest.raises(exports.WorkbookExportError,match='render_failed'):
        exports.resume_workbook_export(protocol,first.export_id)
