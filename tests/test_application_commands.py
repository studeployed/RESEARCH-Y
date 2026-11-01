"""Allowlisted command routing: adapters use substitute service boundaries here."""
from dataclasses import dataclass, replace
from pathlib import Path
import sqlite3
import sys
import types
from uuid import uuid4

import pytest
import research_y
from research_y import application_commands as commands


@pytest.fixture
def services(monkeypatch, tmp_path):
    calls=[]
    @dataclass(frozen=True)
    class Project:
        root: Path
        identifier: object
        name: str
        created_at_utc: str
    @dataclass(frozen=True)
    class Result:
        audited_success: bool = False
        state: str = 'prepared'
        source_retrieval_verified: bool = False
    class Failure(ValueError):
        def __init__(self,code): self.code=code
    class Snapshot:
        location=tmp_path
        def as_dict(self): return {'verified_complete':False,'reported':None,'retrieved':0}
    def service(name, result):
        def run(*a,**kw):
            calls.append((name,a,kw))
            return result
        return run
    projects=types.ModuleType('research_y.projects'); projects.Project=Project
    inspection=types.ModuleType('research_y.application_inspection')
    inspection.ApplicationInspectionError=Failure
    inspection.read_application_snapshot=service('inspect',Snapshot())
    inspection.read_export_report=service('export_report',Snapshot())
    inspection.observe_export_request=service('observe_export',Result())
    exports=types.ModuleType('research_y.workbook_exports'); exports.WorkbookExportError=Failure
    exports.prepare_workbook_export=service('prepare_export',Result())
    exports.resume_workbook_export=service('resume_export',Result())
    exports.cancel_workbook_export=service('cancel_export',Result(state='cancelled'))
    files=types.ModuleType('research_y.export_files')
    def filename(value, *, workbook=False):
        if value != 'report.xlsx': raise ValueError('invalid synthetic filename')
        return value
    files.filename=filename
    for name,module in [('projects',projects),('application_inspection',inspection),('workbook_exports',exports),('export_files',files)]:
        monkeypatch.setitem(sys.modules,'research_y.'+name,module)
        monkeypatch.setattr(research_y,name,module,raising=False)
    project=Project(tmp_path,uuid4(),'Synthetic','2026-11-01T00:00:00+00:00')
    return project,calls,inspection,exports,Failure


@pytest.mark.parametrize('operation',sorted(commands.OPERATIONS))
def test_only_named_service_called_identity_arguments_unchanged(services,operation,tmp_path):
    project,calls,_,_,_=services
    kw={}
    if operation=='inspect': kw['run_id']=str(uuid4())
    else: kw['export_id']=str(uuid4())
    if operation=='prepare_export': kw.update(run_id=str(uuid4()),output_name='report.xlsx')
    if operation in ('prepare_export','resume_export','cancel_export','observe_export'):
        kw['directory']=str(tmp_path/'chosen')
    cmd=commands.ApplicationCommand.for_project(project,operation,**kw)
    result=commands.execute_command(cmd)
    assert len(calls)==1 and calls[0][0]==operation
    assert calls[0][1][0]==project
    assert not result.get('source_retrieval_verified',False)
    if operation in ('resume_export','cancel_export','observe_export','export_report'):
        assert calls[0][1][1]==kw['export_id']
    if operation=='prepare_export':
        assert calls[0][1][1:]==(kw['run_id'],'report.xlsx')
        assert calls[0][2]['export_id']==kw['export_id']
    if 'directory' in kw: assert calls[0][2]['directory']==kw['directory']
    if operation=='inspect':
        assert calls[0][2]['selected_run_id']==kw['run_id']
        assert result['snapshot']['reported'] is None and result['snapshot']['retrieved']==0


def test_no_implicit_run_selection_or_progress(services):
    p,calls,_,_,_=services
    commands.execute_command(commands.ApplicationCommand.for_project(p,'inspect'))
    assert calls[0][2]=={'selected_run_id':None}


@pytest.mark.parametrize('operation', ['prepare_export','resume_export','cancel_export','observe_export','export_report'])
def test_export_id_mandatory_never_generated(services,operation):
    p,calls,*_=services
    with pytest.raises(commands.ApplicationCommandError,match='invalid_command'):
        commands.ApplicationCommand.for_project(p,operation)
    assert not calls


@pytest.mark.parametrize('operation,kw', [
    ('inspect',{'directory':'/unexpected'}),
    ('inspect',{'output_name':'report.xlsx'}),
    ('prepare_export',{'export_id':str(uuid4()),'output_name':'report.xlsx'}),
    ('prepare_export',{'export_id':str(uuid4()),'run_id':str(uuid4()),'output_name':'../x.xlsx'}),
    ('resume_export',{'export_id':str(uuid4()),'run_id':str(uuid4())}),
    ('cancel_export',{'export_id':str(uuid4()),'output_name':'report.xlsx'}),
    ('export_report',{'export_id':str(uuid4()),'directory':'/unexpected'}),
    ('shell',{}),
])
def test_irrelevant_or_unsafe_parameters_rejected_before_service(services,operation,kw):
    p,calls,*_=services
    with pytest.raises(commands.ApplicationCommandError):
        commands.ApplicationCommand.for_project(p,operation,**kw)
    assert not calls


@pytest.mark.parametrize('code', ['project_busy','invalid_evidence','unknown_export','secret-code'])
def test_service_error_allowlist_no_arbitrary_echo(services,monkeypatch,code):
    p,_,inspection,_,Failure=services
    def fail(*a,**kw): raise Failure(code)
    monkeypatch.setattr(inspection,'read_application_snapshot',fail)
    with pytest.raises(commands.ApplicationCommandError) as error:
        commands.execute_command(commands.ApplicationCommand.for_project(p,'inspect'))
    assert error.value.code==(code if code!='secret-code' else 'operation_failed')
    assert 'secret' not in str(error.value)


@pytest.mark.parametrize('number,expected', [(5,'project_busy'),(6,'project_busy'),(261,'project_busy'),(11,'project_unavailable')])
def test_sqlite_busy_distinguished(services,monkeypatch,number,expected):
    p,_,inspection,_,_=services
    def fail(*a,**kw):
        error=sqlite3.OperationalError('PRIVATE database path'); error.sqlite_errorcode=number; raise error
    monkeypatch.setattr(inspection,'read_application_snapshot',fail)
    with pytest.raises(commands.ApplicationCommandError,match=expected):
        commands.execute_command(commands.ApplicationCommand.for_project(p,'inspect'))


def test_wrong_project_and_command_types_rejected(services):
    with pytest.raises(commands.ApplicationCommandError): commands.ApplicationCommand.for_project({},'inspect')
    with pytest.raises(commands.ApplicationCommandError): commands.execute_command({})


def test_unexpected_error_is_static(services,monkeypatch):
    p,_,inspection,_,_=services
    def fail(*a,**kw): raise RuntimeError('PRIVATE_SECRET')
    monkeypatch.setattr(inspection,'read_application_snapshot',fail)
    with pytest.raises(commands.ApplicationCommandError,match='operation_failed'):
        commands.execute_command(commands.ApplicationCommand.for_project(p,'inspect'))
