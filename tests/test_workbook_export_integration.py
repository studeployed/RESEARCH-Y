"""Full application integration: actual project/capture/renderer/audit and files."""
from contextlib import closing
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from uuid import uuid4
from zipfile import ZipFile
import xml.etree.ElementTree as ET

import pytest
from research_y import workbook_exports as exports
from research_y.projects import create_project, open_project
from research_y.result_counts import read_run_counts
from research_y.storage import ApprovedTerm, StrategyGroup, approve_strategy, create_search_run, plan_source_query


@pytest.fixture
def application(tmp_path):
    p=create_project(tmp_path,'Export integration')
    version=approve_strategy(p,theme='Synthetic strategy',approved_by='Fixture',approval_confirmed=True,
        groups=(StrategyGroup('g','Group',(ApprovedTerm('ECMO','researcher',True),)),))
    run=create_search_run(p,version.strategy_version_id)
    query=plan_source_query(p,run_id=run.run_id,group_id='g',source_name='pubmed',exact_query='"ECMO"[All Fields]')
    return p,run.run_id,query.query_id


def research_dump(p):
    with closing(sqlite3.connect(p.database_path)) as db:
        tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT IN ('audit_events','sqlite_sequence') ORDER BY name")]
        return {name: db.execute('SELECT * FROM "'+name+'" ORDER BY rowid').fetchall() for name in tables}


def test_real_capture_workbook_publication_and_no_research_mutation(application):
    p,run,_=application; eid=str(uuid4()); before=research_dump(p); counts=read_run_counts(p,run).as_dict()
    first=exports.prepare_workbook_export(p,run,'summary.xlsx',export_id=eid)
    done=exports.resume_workbook_export(p,eid)
    assert first.state=='prepared' and not first.audited_success and done.audited_success
    content=(p.root/'exports'/'summary.xlsx').read_bytes()
    assert sha256(content).hexdigest()==done.artifact_sha256
    with ZipFile(BytesIO(content)) as z:
        assert z.testzip() is None
        ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        names=[s.attrib['name'] for s in ET.fromstring(z.read('xl/workbook.xml')).findall('s:sheets/s:sheet',ns)]
        assert 'Search Summary' in names and 'Report Snapshot' in names
        for name in z.namelist():
            if name.startswith('xl/worksheets/sheet') and name.endswith('.xml'):
                assert b'INCOMPLETE' in z.read(name)
    assert research_dump(p)==before
    assert read_run_counts(p,run).as_dict()==counts
    with closing(sqlite3.connect(p.database_path)) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
        assert db.execute('PRAGMA user_version').fetchone()[0]==4
        with pytest.raises(sqlite3.DatabaseError):
            db.execute('DELETE FROM audit_events WHERE event_type LIKE ?', (exports.EVENT+':%',))


def test_resume_after_source_changes_uses_original_capture(application):
    p,run,qid=application; eid=str(uuid4())
    first=exports.prepare_workbook_export(p,run,'frozen.xlsx',export_id=eid)
    with closing(sqlite3.connect(p.database_path)) as db,db:
        db.execute('UPDATE source_queries SET reported_matches=17,status="failed" WHERE query_id=?',(qid,))
    assert exports.prepare_workbook_export(p,run,'frozen.xlsx',export_id=eid)==first
    done=exports.resume_workbook_export(p,eid)
    assert done.report_sha256==first.report_sha256
    with exports._transaction(p,write=False) as db:
        original=json.loads(exports._required(db,p,eid)['report_json'])
    assert original['queries'][0]['reported_matches'] is None
    assert original['queries'][0]['status']=='pending'
    assert read_run_counts(p,run).queries[0]['reported_matches']==17


def test_real_project_reopen_and_relocation(application,tmp_path):
    p,run,_=application; eid=str(uuid4())
    exports.prepare_workbook_export(p,run,'reopen.xlsx',export_id=eid)
    moved=tmp_path/'Moved'; shutil.move(str(p.root),str(moved)); reopened=open_project(moved)
    assert exports.resume_workbook_export(reopened,eid).audited_success
    assert exports.inspect_workbook_export(open_project(moved),eid).audited_success


def test_actual_project_identity_mismatch_refused_before_write(application,tmp_path):
    p,run,_=application; before=p.database_path.read_bytes()
    raw=json.loads(p.manifest_path.read_text()); raw['project_id']=str(uuid4()); p.manifest_path.write_text(json.dumps(raw))
    with pytest.raises(exports.WorkbookExportError):
        exports.prepare_workbook_export(p,run,'wrong.xlsx',export_id=str(uuid4()))
    assert p.database_path.read_bytes()==before and not list((p.root/'exports').iterdir())


def test_unknown_run_and_failed_capture_leave_no_export_receipt(application):
    p,_,_=application; before=research_dump(p)
    with pytest.raises(exports.WorkbookExportError):
        exports.prepare_workbook_export(p,str(uuid4()),'unknown.xlsx',export_id=str(uuid4()))
    assert research_dump(p)==before
    with closing(sqlite3.connect(p.database_path)) as db:
        assert db.execute('SELECT COUNT(*) FROM audit_events WHERE event_type LIKE ?', (exports.EVENT+':%',)).fetchone()[0]==0


def test_real_failed_prepared_audit_rolls_back(application):
    p,run,_=application; before=research_dump(p)
    with closing(sqlite3.connect(p.database_path)) as db,db:
        db.execute("CREATE TRIGGER reject_export BEFORE INSERT ON audit_events WHEN NEW.event_type LIKE 'workbook_export_v1:%' BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
    with pytest.raises(exports.WorkbookExportError,match='journal_failed'):
        exports.prepare_workbook_export(p,run,'failed.xlsx',export_id=str(uuid4()))
    assert research_dump(p)==before and not list((p.root/'exports').iterdir())


@pytest.mark.parametrize('where',['exports','data'])
def test_project_junction_or_symlink_is_rejected(application,tmp_path,where):
    p,run,_=application; real=p.root/where; moved=tmp_path/('real-'+where); real.rename(moved)
    if os.name=='nt':
        subprocess.run(['cmd','/c','mklink','/J',str(real),str(moved)],check=True,capture_output=True)
    else:
        real.symlink_to(moved,target_is_directory=True)
    try:
        with pytest.raises(exports.WorkbookExportError):
            exports.prepare_workbook_export(p,run,'blocked.xlsx',export_id=str(uuid4()))
    finally:
        if os.name=='nt': os.rmdir(real)
        else: real.unlink()
        moved.rename(real)
    assert not (p.root/'exports'/'blocked.xlsx').exists()


@pytest.mark.parametrize('action',['staged','published'])
def test_real_child_crash_recovers_file_and_audit(application,action):
    p,run,_=application; eid=str(uuid4()); before=research_dump(p)
    code=r'''
import os,sys
from research_y import workbook_exports as e
from research_y.projects import open_project
p=open_project(sys.argv[1]); run,eid,action=sys.argv[2:]
original=e._append

def append(db,export_id,previous,kind,data):
    original(db,export_id,previous,kind,data)
    if kind==action: os._exit(73)
e._append=append
e.prepare_workbook_export(p,run,'recovered.xlsx',export_id=eid)
e.resume_workbook_export(p,eid)
'''
    env=dict(os.environ); env['PYTHONPATH']=str(Path(__file__).parents[1]/'src')+os.pathsep+env.get('PYTHONPATH','')
    result=subprocess.run([sys.executable,'-c',code,str(p.root),run,eid,action],env=env,capture_output=True,timeout=45)
    assert result.returncode==73,(result.stdout,result.stderr)
    reopened=open_project(p.root)
    assert not exports.inspect_workbook_export(reopened,eid).audited_success
    assert exports.resume_workbook_export(reopened,eid).audited_success
    assert research_dump(reopened)==before


def test_external_real_workbook_and_journal_path_privacy(application,tmp_path):
    p,run,_=application; external=tmp_path/'external'; external.mkdir(); eid=str(uuid4())
    exports.prepare_workbook_export(p,run,'external.xlsx',export_id=eid,directory=external)
    assert exports.resume_workbook_export(p,eid,directory=external).audited_success
    assert (external/'external.xlsx').read_bytes().startswith(b'PK')
    with closing(sqlite3.connect(p.database_path)) as db:
        receipts=''.join(r[0] for r in db.execute('SELECT details_json FROM audit_events WHERE event_type LIKE ?', (exports.EVENT+':%',)))
    assert str(external) not in receipts and str(p.root) not in receipts
