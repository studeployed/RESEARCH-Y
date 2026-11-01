"""Read-model contracts on disk-backed SQLite; application boundaries are stubbed.

Real project/receipt/filesystem acceptance is in test_application_inspection.py.
"""
from contextlib import contextmanager, closing
from dataclasses import FrozenInstanceError
from pathlib import Path
import json
import sqlite3
from types import SimpleNamespace
from uuid import UUID

import pytest
from research_y import application_inspection as app

STAMP = '2026-11-01T22:00:00+00:00'
P, R, S, A, B = [str(UUID(int=i)) for i in range(1, 6)]


@pytest.fixture
def unit(tmp_path, monkeypatch):
    path = tmp_path / 'evidence.sqlite3'
    with closing(sqlite3.connect(path)) as db:
        db.executescript('''
            CREATE TABLE audit_events(event_id INTEGER PRIMARY KEY,occurred_at_utc TEXT,
                                      event_type TEXT,details_json TEXT);
            CREATE TABLE project_metadata(singleton_id INTEGER,theme TEXT,objectives TEXT);
            INSERT INTO project_metadata VALUES(1,'Theme','Objectives');
            CREATE TABLE search_runs(run_id TEXT,strategy_version_id TEXT,created_at_utc TEXT,
                                     status TEXT,completed_at_utc TEXT);
            CREATE TABLE strategy_versions(strategy_version_id TEXT,version_number INTEGER,
                                           approved_at_utc TEXT,snapshot_json TEXT);
            CREATE TABLE strategy_groups(strategy_version_id TEXT,group_id TEXT,label TEXT,group_order INTEGER);
        ''')
    p = SimpleNamespace(root=tmp_path, database_path=path, identifier=UUID(P), name='Project')
    states, calls, connections = {}, [], []
    @contextmanager
    def reader(project):
        assert project is p
        with closing(sqlite3.connect(path, timeout=.1)) as db:
            db.execute('PRAGMA query_only=ON'); db.execute('BEGIN')
            connections.append(db)
            yield db
    def load(db, project, key):
        assert db is connections[-1] and project is p
        calls.append(key)
        return states.get(key)
    monkeypatch.setattr(app, '_read', reader)
    monkeypatch.setattr(app.exports, '_load', load)
    return SimpleNamespace(project=p, states=states, calls=calls, connections=connections)


def event(f, key=A, *, phase='prepared', error=None, kind='project_exports', at=STAMP, event_type=None):
    with closing(sqlite3.connect(f.project.database_path)) as db, db:
        eid = db.execute('INSERT INTO audit_events(occurred_at_utc,event_type,details_json) VALUES(?,?,?)',
            (at, event_type or f'{app.exports.EVENT}:{key}', json.dumps({'at_utc': at}))).lastrowid
    f.states[key] = dict(export_id=key,run_id=R,filename='report.xlsx',destination={'kind':kind},
        state=phase,last_error=error,report_sha256='a'*64,stage=None,event_id=eid,report_json='{}')
    return f.states[key]


def test_empty_inventory_is_not_a_fictional_success(unit):
    assert app.list_export_requests(unit.project) == ()
    assert not unit.calls


def test_all_requests_stable_latest_order_and_no_filesystem_verification(unit, monkeypatch):
    event(unit, A); event(unit, B, phase='cancelled'); event(unit, A, phase='published')
    monkeypatch.setattr(app, '_observe_files', lambda *_: pytest.fail('inventory touched files'))
    entries = app.list_export_requests(unit.project)
    assert [e.export_id for e in entries] == [A,B]
    assert unit.calls == [A,B]
    assert entries[0].first_event_id == 1 and entries[0].last_event_id == 3
    assert entries[0].recorded_state == 'published' and entries[1].recorded_state == 'cancelled'
    for entry in entries:
        assert not entry.audited_success and not entry.files_checked and not entry.source_retrieval_verified
        assert entry.worker_status == 'unknown' and entry.report_status == 'incomplete'
        with pytest.raises(FrozenInstanceError): entry.filename = 'changed.xlsx'


@pytest.mark.parametrize('phase',['prepared','staging','staged','publishing','published','cancelled'])
def test_recorded_phases_preserved_not_inferred_as_live_workers(unit,phase):
    event(unit,phase=phase,error='storage_failed')
    entry, = app.list_export_requests(unit.project)
    assert entry.recorded_state == phase and entry.last_error == 'storage_failed'
    assert not entry.audited_success and entry.worker_status == 'unknown'


@pytest.mark.parametrize('kind',['project_exports','external'])
def test_destination_kind_preserved_without_a_stored_absolute_path(unit,kind):
    state=event(unit,kind=kind)
    state['stage']={'sha256':'b'*64}
    entry,=app.list_export_requests(unit.project)
    assert entry.destination_kind == kind and entry.artifact_sha256 == 'b'*64
    assert str(unit.project.root) not in repr(entry)


@pytest.mark.parametrize('name',['workbook_export_v2:'+A,'workbook_export_v1','workbook_export_bad:'+A])
def test_future_or_malformed_export_namespace_fails_closed(unit,name):
    event(unit,event_type=name)
    with pytest.raises(app.ApplicationInspectionError,match='unsupported_export_journal'):
        app.list_export_requests(unit.project)


def test_similar_nonexport_event_names_not_matched_as_sql_wildcards(unit):
    event(unit,event_type='workbookXexportXv1:'+A)
    assert app.list_export_requests(unit.project) == ()


@pytest.mark.parametrize('bad',['not-an-id',None,True,A.upper(),''])
def test_invalid_requested_identifiers_fail_before_read(unit,monkeypatch,bad):
    # A is numeric-only; use a UUID containing letters for the uppercase case.
    if bad == A.upper(): bad='AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA'
    monkeypatch.setattr(app,'_read',lambda *_:pytest.fail('opened invalid identifier'))
    for call in (app.observe_export_request, app.read_export_report):
        with pytest.raises(app.ApplicationInspectionError,match='invalid_identifier'):
            call(unit.project,bad)
    if bad is not None:  # None deliberately means no selected run.
        with pytest.raises(app.ApplicationInspectionError,match='invalid_identifier'):
            app.read_application_snapshot(unit.project,selected_run_id=bad)


def test_bad_journal_identifier_never_hides_a_request(unit):
    event(unit,event_type=app.exports.EVENT+':bad')
    with pytest.raises(app.ApplicationInspectionError,match='invalid_identifier'):
        app.list_export_requests(unit.project)


def test_unknown_export_is_distinct_from_empty_inventory(unit):
    with pytest.raises(app.ApplicationInspectionError,match='unknown_export'):
        app.observe_export_request(unit.project,A)


@pytest.mark.parametrize('damage',['column-time','body-time','head'])
def test_index_cannot_disagree_with_validated_journal(unit,damage):
    state=event(unit)
    with closing(sqlite3.connect(unit.project.database_path)) as db,db:
        if damage=='column-time': db.execute("UPDATE audit_events SET occurred_at_utc='2026-11-02T00:00:00+00:00'")
        elif damage=='body-time': db.execute("UPDATE audit_events SET details_json='{}'")
        else: state['event_id']=99
    with pytest.raises(app.ApplicationInspectionError,match='invalid_evidence'):
        app.list_export_requests(unit.project)


@pytest.mark.parametrize('bad',[None,'2026-11-01','not a date','2026-11-01T22:00:00+01:00'])
def test_invalid_journal_timestamp_refused(unit,bad):
    event(unit,at=bad)
    with pytest.raises(app.ApplicationInspectionError,match='invalid_evidence'):
        app.list_export_requests(unit.project)


class Target:
    def __init__(self, present=False, same=True, error=None):
        self.present,self.same,self.error=present,same,error
        self.reads=[]
    def exists(self,name): return self.present
    def same_file(self,*_): return self.same
    def read(self,name,**kwargs):
        self.reads.append((name,kwargs))
        if self.error: raise self.error
        return b'artifact'


@pytest.fixture
def files(monkeypatch):
    target=Target()
    @contextmanager
    def store(*_): yield object()
    @contextmanager
    def selected(*_): yield target
    monkeypatch.setattr(app.exports,'_store',store)
    monkeypatch.setattr(app.exports,'_target',selected)
    monkeypatch.setattr(app.exports,'_read_artifact',lambda *_:b'artifact')
    return target


@pytest.mark.parametrize('phase,present,expected',[
    ('prepared',False,'not_yet_staged'),('cancelled',True,'recorded_cancelled'),
    ('staging',False,'staging_receipt_required'),('staged',False,'ready_to_publish'),
    ('staged',True,'destination_conflict'),('publishing',False,'publication_pending'),
    ('publishing',True,'published_receipt_missing'),('published',False,'published_file_missing'),
    ('published',True,'published_verified')])
def test_observation_never_promotes_an_unreceipted_file(unit,files,phase,present,expected):
    state=event(unit,phase=phase)
    if phase!='prepared': state['stage']={'sha256':'b'*64,'size':8}
    state['publication']={'name':'owned.part'}
    files.present=present
    before=unit.project.database_path.read_bytes()
    observed=app.observe_export_request(unit.project,A)
    assert observed.outcome==expected
    assert observed.audited_success == (expected=='published_verified')
    assert not observed.request.audited_success and not observed.source_retrieval_verified
    assert unit.project.database_path.read_bytes()==before


@pytest.mark.parametrize('failure,expected',[
    (FileNotFoundError('PRIVATE PATH'),'retained_artifact_missing'),
    (app.ExportFileError('PRIVATE PATH'),'retained_artifact_changed'),
    (PermissionError('PRIVATE PATH'),'storage_unavailable')])
def test_missing_or_damaged_original_prevents_success(unit,files,monkeypatch,failure,expected):
    state=event(unit,phase='published'); state['stage']={'sha256':'b'*64,'size':8}
    def fail(*_): raise failure
    monkeypatch.setattr(app.exports,'_read_artifact',fail)
    observed=app.observe_export_request(unit.project,A)
    assert observed.outcome==expected and not observed.audited_success
    assert 'PRIVATE PATH' not in repr(observed)


@pytest.mark.parametrize('code,expected',[('destination_required','destination_confirmation_required'),
                                        ('directory_changed','destination_directory_changed')])
def test_external_selection_is_not_invented(unit,files,monkeypatch,code,expected):
    state=event(unit,phase='published',kind='external'); state['stage']={'sha256':'b'*64,'size':8}
    @contextmanager
    def fail(*_):
        raise app.exports.WorkbookExportError(code,A)
        yield
    monkeypatch.setattr(app.exports,'_target',fail)
    observed=app.observe_export_request(unit.project,A)
    assert observed.outcome==expected and not observed.audited_success


def test_unrelated_identical_output_is_not_adopted(unit,files):
    state=event(unit,phase='publishing'); state['stage']={'sha256':'b'*64,'size':8}; state['publication']={'name':'owned.part'}
    files.present=True; files.same=False
    assert app.observe_export_request(unit.project,A).outcome=='destination_conflict'
    assert not files.reads


@pytest.mark.parametrize('failure,expected',[(app.ExportFileError('PRIVATE'),'destination_changed'),
                                           (PermissionError('PRIVATE'),'destination_unavailable')])
def test_unreadable_output_never_passes(unit,files,failure,expected):
    state=event(unit,phase='published'); state['stage']={'sha256':'b'*64,'size':8}
    files.present=True; files.error=failure
    observed=app.observe_export_request(unit.project,A)
    assert observed.outcome==expected and not observed.audited_success
    assert 'PRIVATE' not in repr(observed)


def test_repeated_observation_rechecks_files_not_previous_success(unit,files):
    state=event(unit,phase='published'); state['stage']={'sha256':'b'*64,'size':8}; files.present=True
    assert app.observe_export_request(unit.project,A).audited_success
    files.error=app.ExportFileError('Changed')
    assert not app.observe_export_request(unit.project,A).audited_success


def test_snapshot_is_immutable_and_never_selects_latest_implicitly(unit,monkeypatch):
    monkeypatch.setattr(app,'_runs',lambda _:[])
    result=app.read_application_snapshot(unit.project)
    data=result.as_dict()
    assert data['selected_run_id'] is None and data['report'] is None
    assert data['runs']==[] and data['exports']==[]
    assert data['last_successful_source_checkpoint'] is None
    assert data['checkpoint_verification']=='not_performed'
    assert not data['source_retrieval_verified'] and not data['gui_implemented']
    assert result.location==unit.project.root and str(result.location) not in result.payload_json
    data['project']['name']='changed'
    assert result.as_dict()['project']['name']=='Project'
    with pytest.raises(FrozenInstanceError): result.payload_json='{}'


def test_last_audit_is_not_a_verified_source_checkpoint(unit,monkeypatch):
    event(unit); monkeypatch.setattr(app,'_runs',lambda _:[])
    data=app.read_application_snapshot(unit.project).as_dict()
    assert data['last_recorded_audit_event']['event_id']==1
    assert data['last_successful_source_checkpoint'] is None
    assert 'last_audit_event_is_not_a_source_checkpoint' in data['warnings']


def test_unknown_run_is_not_a_zero_result(unit,monkeypatch):
    monkeypatch.setattr(app,'_runs',lambda _:[])
    with pytest.raises(app.ApplicationInspectionError,match='unknown_run'):
        app.read_application_snapshot(unit.project,selected_run_id=R)


def test_selected_capture_and_inventory_use_exact_same_connection(unit,monkeypatch):
    import research_y.strategy_report as reports
    event(unit)
    seen=[]
    def runs(db): seen.append(db); return [{'run_id':R}]
    def capture(db,p,r,stamp):
        assert p is unit.project and r==R
        seen.append(db)
        return SimpleNamespace(as_dict=lambda: {'status':'incomplete','reported':None})
    monkeypatch.setattr(app,'_runs',runs); monkeypatch.setattr(reports,'_capture',capture)
    result=app.read_application_snapshot(unit.project,selected_run_id=R).as_dict()
    assert seen==[unit.connections[0],unit.connections[0]]
    assert len(unit.connections)==1
    assert result['report']=={'status':'incomplete','reported':None}
    assert len(result['exports'])==1


def test_project_setup_corruption_not_replaced_by_empty_text(unit,monkeypatch):
    monkeypatch.setattr(app,'_runs',lambda _:[])
    with closing(sqlite3.connect(unit.project.database_path)) as db,db:
        db.execute('UPDATE project_metadata SET theme=NULL')
    with pytest.raises(app.ApplicationInspectionError,match='invalid_evidence'):
        app.read_application_snapshot(unit.project)


def test_no_filter_argument_can_change_search_count_scope(unit):
    with pytest.raises(TypeError): app.read_application_snapshot(unit.project,filter='english')


def run_rows(f):
    with closing(sqlite3.connect(f.project.database_path)) as db,db:
        db.execute('INSERT INTO search_runs VALUES(?,?,?,?,?)',(R,S,STAMP,'pending',None))
        db.execute('INSERT INTO strategy_versions VALUES(?,?,?,?)',(S,1,STAMP,json.dumps({'theme':'Stored theme'})))
        db.execute('INSERT INTO strategy_groups VALUES(?,?,?,?)',(S,'g','Group',0))


def test_run_catalogue_reuses_strategy_validator_without_invented_names(unit,monkeypatch):
    import research_y.strategy_report as reports
    run_rows(unit); validated=[]
    monkeypatch.setattr(reports,'_strategy',lambda data,groups:validated.append((data,groups)))
    with app._read(unit.project) as db: result=app._runs(db)
    assert result[0]['run_id']==R and result[0]['strategy_version_id']==S
    assert result[0]['strategy_theme']=='Stored theme' and result[0]['version_number']==1
    assert result[0]['completed_at_utc'] is None and not result[0]['source_retrieval_verified']
    assert 'name' not in result[0] and validated==[({'theme':'Stored theme'},[('g','Group',0)])]


@pytest.mark.parametrize('table,column,value',[
    ('search_runs','run_id','broken'),('search_runs','strategy_version_id','broken'),
    ('search_runs','created_at_utc','yesterday'),('search_runs','status','fake'),
    ('search_runs','completed_at_utc','2026-11-01'),('strategy_versions','version_number',0),
    ('strategy_versions','version_number',1.5),('strategy_versions','approved_at_utc',None)])
def test_bad_run_metadata_refused_not_filled_in(unit,monkeypatch,table,column,value):
    import research_y.strategy_report as reports
    run_rows(unit); monkeypatch.setattr(reports,'_strategy',lambda *_:None)
    with closing(sqlite3.connect(unit.project.database_path)) as db,db:
        db.execute(f'UPDATE {table} SET {column}=?',(value,))
    with app._read(unit.project) as db,pytest.raises(app.ApplicationInspectionError): app._runs(db)


def test_retained_export_report_is_not_a_new_capture(unit,monkeypatch):
    state=event(unit); state['report_json']='{"frozen":"prior-state"}'
    monkeypatch.setattr(app,'StrategyReport',lambda raw:json.loads(raw))
    assert app.read_export_report(unit.project,A)=={'frozen':'prior-state'}


@pytest.mark.parametrize('number,expected',[(sqlite3.SQLITE_BUSY,'project_busy'),
    (sqlite3.SQLITE_LOCKED,'project_busy'),(sqlite3.SQLITE_BUSY | 256,'project_busy'),
    (sqlite3.SQLITE_CORRUPT,'project_unavailable'),(None,'project_unavailable')])
def test_read_boundary_sanitises_sqlite_errors(monkeypatch,number,expected):
    import research_y.result_counts as counts
    from contextlib import nullcontext
    error=sqlite3.OperationalError('PRIVATE FILE OR SQL TEXT'); error.sqlite_errorcode=number
    @contextmanager
    def bad(*_):
        raise error
        yield
    monkeypatch.setattr(app,'project_guard',lambda _:nullcontext())
    monkeypatch.setattr(counts,'_read_connection',bad)
    with pytest.raises(app.ApplicationInspectionError) as raised:
        with app._read(object()): pass
    assert raised.value.code==expected and 'PRIVATE' not in str(raised.value)


@pytest.mark.parametrize('error',[PermissionError('PRIVATE'),ValueError('PRIVATE'),TypeError('PRIVATE'),
                                  KeyError('PRIVATE'),AttributeError('PRIVATE'),RecursionError('PRIVATE')])
def test_read_boundary_sanitises_project_and_evidence_errors(monkeypatch,error):
    import research_y.result_counts as counts
    from contextlib import nullcontext
    @contextmanager
    def bad(*_):
        raise error
        yield
    monkeypatch.setattr(app,'project_guard',lambda _:nullcontext())
    monkeypatch.setattr(counts,'_read_connection',bad)
    with pytest.raises(app.ApplicationInspectionError,match='invalid_evidence') as raised:
        with app._read(object()): pass
    assert 'PRIVATE' not in str(raised.value)


def test_read_boundary_preserves_specific_inspection_failure(monkeypatch):
    import research_y.result_counts as counts
    from contextlib import nullcontext
    monkeypatch.setattr(app,'project_guard',lambda _:nullcontext())
    monkeypatch.setattr(counts,'_read_connection',lambda _:nullcontext(object()))
    with pytest.raises(app.ApplicationInspectionError,match='unknown_run'):
        with app._read(object()): raise app.ApplicationInspectionError('unknown_run')
