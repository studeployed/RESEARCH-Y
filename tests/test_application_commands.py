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
from research_y.storage import ApprovedTerm, StrategyGroup


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
    admission=types.ModuleType('research_y.strategy_admission')
    admission.StrategyAdmissionError=Failure
    admission.commit_approved_strategy=service('admit_strategy',Result())
    from research_y.preflight_review import _review_payload, PRESS_ITEMS
    preflight=types.ModuleType('research_y.preflight_review')
    preflight.PreflightError=Failure
    preflight._review_payload=_review_payload
    preflight.PRESS_ITEMS=PRESS_ITEMS
    preflight.read_preflight=service('preflight_read',{})
    preflight.record_preflight_review=service('preflight_record',{})
    from research_y.pubmed_pilot import PubMedPilotError
    pilot=types.ModuleType('research_y.pubmed_pilot')
    pilot.PubMedPilotError=PubMedPilotError
    pilot.read_pubmed_pilot=service('pubmed_pilot_read',None)
    pilot.probe_pubmed_count_once=service('pubmed_pilot_count',{
        'status':'requested_indeterminate','source_retrieval_verified':False})
    from research_y.wos_starter_pilot import WoSPilotError
    wos=types.ModuleType('research_y.wos_starter_pilot')
    wos.WoSPilotError=WoSPilotError
    wos.read_wos_pilot=service('wos_pilot_read',None)
    wos.probe_wos_starter_once=service('wos_pilot_sample',{
        'status':'requested_indeterminate','source_retrieval_verified':False})
    from research_y.pilot_history import PilotHistoryError
    history=types.ModuleType('research_y.pilot_history')
    history.PilotHistoryError=PilotHistoryError
    history.read_pilot_history=service('pilot_history',{
        'entries':[], 'no_network_requests':True,
        'source_retrieval_verified':False})
    from research_y.wos_acquisition_gui import WoSAcquisitionError, MAX_VERIFY_REQUESTS
    acquisition=types.ModuleType('research_y.wos_acquisition_gui')
    acquisition.WoSAcquisitionError=WoSAcquisitionError
    acquisition.MAX_VERIFY_REQUESTS=MAX_VERIFY_REQUESTS
    acquisition.preview_wos_verification=service('wos_acquisition_verify_plan',{
        'no_network_requests':True,'source_retrieval_verified':False})
    acquisition.pause_wos_verification_session=service('wos_acquisition_pause',{
        'no_network_requests':True,'source_retrieval_verified':False})
    acquisition.run_wos_verification_session=service('wos_acquisition_verify',{
        'source_retrieval_verified':False,'whole_search_verified':False})
    acquisition.preview_wos_acquisition=service('wos_acquisition_preview',{
        'source_retrieval_verified':False})
    acquisition.inspect_wos_acquisition=service('wos_acquisition_read',{
        'source_retrieval_verified':False})
    acquisition.prepare_wos_acquisition=service('wos_acquisition_prepare',{
        'source_retrieval_verified':False})
    acquisition.run_wos_acquisition_session=service('wos_acquisition_tick',{
        'source_retrieval_verified':False})
    from research_y.pubmed_source_gui import PubMedSourceError, _sha, _window
    pubmed_source=types.ModuleType('research_y.pubmed_source_gui')
    pubmed_source.PubMedSourceError=PubMedSourceError
    pubmed_source._sha=_sha
    pubmed_source._window=_window
    pubmed_source.preview_pubmed_source=service('pubmed_identifier_preview',{
        'no_network_requests':True,'source_retrieval_verified':False})
    pubmed_source.inspect_pubmed_source=service('pubmed_identifier_read',{
        'no_network_requests':True,'source_retrieval_verified':False})
    pubmed_source.pause_pubmed_source_session=service('pubmed_identifier_pause',{
        'no_network_requests':True,'source_retrieval_verified':False})
    pubmed_source.run_pubmed_source_session=service('pubmed_identifier_run',{
        'status':'incomplete','source_retrieval_verified':False})
    files=types.ModuleType('research_y.export_files')
    def filename(value, *, workbook=False):
        if value != 'report.xlsx': raise ValueError('invalid synthetic filename')
        return value
    files.filename=filename
    for name,module in [('projects',projects),('application_inspection',inspection),
                        ('workbook_exports',exports),('strategy_admission',admission),
                        ('preflight_review',preflight),('pubmed_pilot',pilot),
                        ('wos_starter_pilot',wos),('pilot_history',history),
                        ('wos_acquisition_gui',acquisition),
                        ('pubmed_source_gui',pubmed_source),
                        ('export_files',files)]:
        monkeypatch.setitem(sys.modules,'research_y.'+name,module)
        monkeypatch.setattr(research_y,name,module,raising=False)
    project=Project(tmp_path,uuid4(),'Synthetic','2026-11-01T00:00:00+00:00')
    return project,calls,inspection,exports,Failure


@pytest.mark.parametrize('operation',sorted(commands.OPERATIONS))
def test_only_named_service_called_identity_arguments_unchanged(services,operation,tmp_path):
    project,calls,_,_,_=services
    kw={}
    if operation=='inspect':
        kw['run_id']=str(uuid4())
    elif operation=='admit_strategy':
        kw.update(admission_request_id=str(uuid4()), admission_theme='Right ventricle',
                  admission_approved_by='Researcher',
                  admission_groups=(StrategyGroup('rv', 'RV',
                      (ApprovedTerm('right ventricle','researcher',True),)),),
                  approval_confirmed=True)
    elif operation=='pilot_history':
        kw['history_before_event_id']=123
    elif operation=='wos_acquisition_preview':
        kw.update(run_id=str(uuid4()),acquisition_query_id=str(uuid4()))
    elif operation=='wos_acquisition_read':
        kw.update(run_id=str(uuid4()),acquisition_query_id=str(uuid4()))
    elif operation in ('wos_acquisition_verify_plan','wos_acquisition_pause'):
        kw.update(run_id=str(uuid4()),acquisition_query_id=str(uuid4()))
    elif operation=='wos_acquisition_verify':
        kw.update(run_id=str(uuid4()),acquisition_query_id=str(uuid4()),
                  acquisition_plan_sha256='a'*64,
                  acquisition_confirmed=True,
                  acquisition_revalidate_quota=False,
                  acquisition_api_key='SYNTHETIC-PRIVATE-STARTER-KEY',
                  verification_expected_requests=24)
    elif operation=='wos_acquisition_prepare':
        kw.update(run_id=str(uuid4()),acquisition_query_id=str(uuid4()),
                  acquisition_plan_sha256='a'*64,
                  acquisition_confirmed=True,
                  acquisition_retention_authorized=True)
    elif operation=='wos_acquisition_tick':
        kw.update(run_id=str(uuid4()),acquisition_query_id=str(uuid4()),
                  acquisition_confirmed=True,acquisition_revalidate_quota=False,
                  acquisition_api_key='SYNTHETIC-PRIVATE-STARTER-KEY')
    elif operation in ('pubmed_identifier_preview','pubmed_identifier_read',
                       'pubmed_identifier_pause'):
        kw.update(run_id=str(uuid4()),pubmed_source_query_id=str(uuid4()))
    elif operation=='pubmed_identifier_run':
        kw.update(run_id=str(uuid4()),pubmed_source_query_id=str(uuid4()),
                  pubmed_source_plan_sha256='a'*64,
                  pubmed_coverage_start='1800-01-01',
                  pubmed_coverage_end='2026-11-04',
                  pubmed_source_confirmed=True,
                  pubmed_source_contact_email='fixture@example.org',
                  pubmed_source_api_key='PRIVATE-PUBMED-KEY')
    elif operation=='pubmed_pilot_read':
        kw.update(pilot_id=str(uuid4()))
    elif operation=='wos_pilot_read':
        kw.update(pilot_id=str(uuid4()))
    elif operation=='wos_pilot_sample':
        kw.update(run_id=str(uuid4()),pilot_id=str(uuid4()),
                  pilot_query_id=str(uuid4()),pilot_plan_sha256='a'*64,
                  pilot_api_key='fixture-private-wos-key-123',
                  pilot_confirmed=True,pilot_wos_revalidate_quota=False)
    elif operation=='pubmed_pilot_count':
        kw.update(run_id=str(uuid4()),pilot_id=str(uuid4()),
                  pilot_query_id=str(uuid4()),pilot_plan_sha256='a'*64,
                  pilot_contact_email='synthetic@example.org',
                  pilot_api_key='fixture-private-key-123',pilot_confirmed=True)
    elif operation in ('preflight_read','preflight_record'):
        kw.update(run_id=str(uuid4()))
        if operation=='preflight_record':
            from research_y.preflight_review import PRESS_ITEMS
            kw.update(review_id=str(uuid4()),review_plan_sha256='a'*64,
                review_reviewer_name='Reviewer',
                review_reviewer_role='researcher_self_check',
                review_items={k:'not_reviewed' for k in PRESS_ITEMS},
                review_note='', review_known_relevant=())
    else:
        kw['export_id']=str(uuid4())
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
    if operation=='preflight_read':
        assert calls[0][1][1] == kw['run_id']
    if operation=='wos_pilot_read':
        assert calls[0][1][1] == kw['pilot_id']
        assert result['pilot'] is None
    if operation=='wos_pilot_sample':
        assert calls[0][2]['pilot_id'] == kw['pilot_id']
        assert calls[0][2]['expected_plan_sha256'] == kw['pilot_plan_sha256']
        assert calls[0][2]['query_id'] == kw['pilot_query_id']
        assert calls[0][2]['confirmed'] is True
        assert calls[0][2]['client']._key == kw['pilot_api_key']
        assert calls[0][2]['client']._budget == 1
        assert calls[0][2]['revalidate_quota'] is False
        assert kw['pilot_api_key'] not in repr(cmd)
    if operation=='wos_acquisition_preview':
        assert calls[0][2]['run_id']==kw['run_id']
        assert calls[0][2]['query_id']==kw['acquisition_query_id']
    if operation in ('wos_acquisition_verify_plan','wos_acquisition_pause'):
        assert calls[0][2]['run_id']==kw['run_id']
        assert calls[0][2]['query_id']==kw['acquisition_query_id']
        assert result['no_network_requests'] is True
    if operation=='wos_acquisition_verify':
        assert calls[0][2]['run_id']==kw['run_id']
        assert calls[0][2]['query_id']==kw['acquisition_query_id']
        assert calls[0][2]['expected_plan_sha256']==kw['acquisition_plan_sha256']
        assert calls[0][2]['expected_requests']==24
        assert calls[0][2]['confirmed'] is True
        assert calls[0][2]['revalidate_quota'] is False
        assert calls[0][2]['client']._budget==512
        assert calls[0][2]['client']._timeout==10
        assert kw['acquisition_api_key'] not in repr(cmd)
    if operation=='wos_acquisition_read':
        assert calls[0][2]['run_id']==kw['run_id']
        assert calls[0][2]['query_id']==kw['acquisition_query_id']
    if operation=='wos_acquisition_prepare':
        assert calls[0][2]['run_id']==kw['run_id']
        assert calls[0][2]['query_id']==kw['acquisition_query_id']
        assert calls[0][2]['expected_plan_sha256']==kw['acquisition_plan_sha256']
        assert calls[0][2]['confirmed'] is True
        assert calls[0][2]['retention_authorized'] is True
    if operation=='wos_acquisition_tick':
        assert calls[0][2]['run_id']==kw['run_id']
        assert calls[0][2]['query_id']==kw['acquisition_query_id']
        assert calls[0][2]['confirmed'] is True
        assert calls[0][2]['revalidate_quota'] is False
        assert calls[0][2]['client']._key==kw['acquisition_api_key']
        assert calls[0][2]['client']._budget==3
        assert calls[0][2]['client']._timeout==10
        assert kw['acquisition_api_key'] not in repr(cmd)
    if operation=='pilot_history':
        assert calls[0][2]['before_event_id']==123
        assert result['no_network_requests'] is True
    if operation in ('pubmed_identifier_preview','pubmed_identifier_read',
                     'pubmed_identifier_pause'):
        assert calls[0][2]['run_id']==kw['run_id']
        assert calls[0][2]['query_id']==kw['pubmed_source_query_id']
        assert result['no_network_requests'] is True
    if operation=='pubmed_identifier_run':
        assert calls[0][2]['run_id']==kw['run_id']
        assert calls[0][2]['query_id']==kw['pubmed_source_query_id']
        assert calls[0][2]['expected_plan_sha256']==kw['pubmed_source_plan_sha256']
        assert calls[0][2]['coverage_start']==kw['pubmed_coverage_start']
        assert calls[0][2]['coverage_end']==kw['pubmed_coverage_end']
        assert calls[0][2]['confirmed'] is True
        assert calls[0][2]['client']._email==kw['pubmed_source_contact_email']
        assert calls[0][2]['client']._api_key==kw['pubmed_source_api_key']
        assert calls[0][2]['client']._timeout==15
        assert kw['pubmed_source_api_key'] not in repr(cmd)
        assert kw['pubmed_source_contact_email'] not in repr(cmd)
    if operation=='pubmed_pilot_read':
        assert calls[0][1][1] == kw['pilot_id']
        assert result['pilot'] is None
    if operation=='pubmed_pilot_count':
        assert calls[0][2]['pilot_id'] == kw['pilot_id']
        assert calls[0][2]['expected_plan_sha256'] == kw['pilot_plan_sha256']
        assert calls[0][2]['query_id'] == kw['pilot_query_id']
        assert calls[0][2]['confirmed'] is True
        assert calls[0][2]['client']._email == kw['pilot_contact_email']
        assert calls[0][2]['client']._api_key == kw['pilot_api_key']
        assert kw['pilot_api_key'] not in repr(cmd)
        assert kw['pilot_contact_email'] not in repr(cmd)
    if operation=='preflight_record':
        assert calls[0][2]['review_id'] == kw['review_id']
        assert calls[0][2]['run_id'] == kw['run_id']
        assert calls[0][2]['press_items'] == kw['review_items']


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


def test_prepare_passes_validated_confirmed_external_identity_to_service(services, tmp_path):
    project, calls, _, _, _ = services
    identity = (12, 340)
    cmd = commands.ApplicationCommand.for_project(
        project, 'prepare_export', run_id=str(uuid4()), export_id=str(uuid4()),
        output_name='report.xlsx', directory=str(tmp_path / 'chosen'),
        expected_directory_identity=identity)
    assert cmd.expected_directory_identity == identity
    commands.execute_command(cmd)
    assert len(calls) == 1 and calls[0][0] == 'prepare_export'
    assert calls[0][2]['directory'] == str(tmp_path / 'chosen')
    assert calls[0][2]['expected_directory_identity'] == identity


@pytest.mark.parametrize('invalid', [
    [], [1, 2], (1,), (1, 2, 3), (True, 2), (1, False),
    (-1, 2), (1, -1), (1.0, 2), ('1', 2), {'a': 1},
])
def test_confirmed_directory_identity_contract_rejects_malformed_values(services, tmp_path, invalid):
    project, calls, *_ = services
    with pytest.raises(commands.ApplicationCommandError, match='^invalid_command$'):
        commands.ApplicationCommand.for_project(
            project, 'prepare_export', run_id=str(uuid4()), export_id=str(uuid4()),
            output_name='report.xlsx', directory=str(tmp_path / 'chosen'),
            expected_directory_identity=invalid)
    assert not calls


def test_confirmed_directory_identity_cannot_be_reused_for_other_commands(services, tmp_path):
    project, calls, *_ = services
    for operation in ('inspect', 'resume_export', 'cancel_export', 'observe_export',
                      'export_report'):
        kw = {'expected_directory_identity': (1, 2)}
        if operation == 'inspect':
            kw['run_id'] = str(uuid4())
        else:
            kw['export_id'] = str(uuid4())
        if operation != 'export_report':
            kw['directory'] = str(tmp_path / 'chosen')
        with pytest.raises(commands.ApplicationCommandError, match='^invalid_command$'):
            commands.ApplicationCommand.for_project(project, operation, **kw)
    with pytest.raises(commands.ApplicationCommandError, match='^invalid_command$'):
        commands.ApplicationCommand.for_project(
            project, 'prepare_export', run_id=str(uuid4()), export_id=str(uuid4()),
            output_name='report.xlsx', expected_directory_identity=(1, 2))
    assert not calls


def test_mutated_command_identity_is_revalidated_at_worker_boundary(services, tmp_path):
    project, calls, *_ = services
    cmd = commands.ApplicationCommand.for_project(
        project, 'prepare_export', run_id=str(uuid4()), export_id=str(uuid4()),
        output_name='report.xlsx', directory=str(tmp_path / 'chosen'),
        expected_directory_identity=(1, 2))
    object.__setattr__(cmd, 'expected_directory_identity', (True, 2))
    with pytest.raises(commands.ApplicationCommandError, match='^invalid_command$'):
        commands.execute_command(cmd)
    assert not calls


def test_strategy_admission_mandatory_explicit_approval_worker_routing(services):
    project, calls, *_ = services
    groups = (StrategyGroup('rv', 'RV', (ApprovedTerm('right ventricle', 'researcher', True),)),)
    payload = dict(admission_request_id=str(uuid4()), admission_theme='RV',
                   admission_approved_by='Reviewer', admission_groups=groups,
                   approval_confirmed=True)
    cmd = commands.ApplicationCommand.for_project(project, 'admit_strategy', **payload)
    assert 'RV' not in repr(cmd) and 'right ventricle' not in repr(cmd)
    commands.execute_command(cmd)
    assert len(calls) == 1 and calls[0][0] == 'admit_strategy'
    assert calls[0][2] == dict(request_id=payload['admission_request_id'],
                               theme='RV', approved_by='Reviewer',
                               groups=groups, approval_confirmed=True)
    assert calls[0][1][0] == project


@pytest.mark.parametrize('change', [
    {'approval_confirmed': False}, {'approval_confirmed': 1},
    {'admission_request_id': 'fake'}, {'admission_request_id': 123},
    {'admission_theme': ' '}, {'admission_groups': ()},
    {'admission_groups': []}, {'admission_approved_by': None},
    {'directory': '/private/outside'}, {'run_id': '123'},
    {'export_id': '123'}, {'output_name': 'report.xlsx'},
    {'admission_groups': (StrategyGroup('g', 'Group',
        (ApprovedTerm('unsafe \\"quote\\"', 'researcher', True),)),)},
])
def test_strategy_admission_rejects_invalid_or_irrelevant_worker_inputs(services, change):
    project, calls, *_ = services
    payload = dict(admission_request_id=str(uuid4()), admission_theme='Theme',
                   admission_approved_by='Researcher',
                   admission_groups=(StrategyGroup('g', 'Group',
                       (ApprovedTerm('one term', 'researcher', True),)),),
                   approval_confirmed=True)
    payload.update(change)
    with pytest.raises(commands.ApplicationCommandError, match='^invalid_command$'):
        commands.ApplicationCommand.for_project(project, 'admit_strategy', **payload)
    assert not calls


def test_admission_parameters_not_valid_for_non_admission_operations(services):
    project, calls, *_ = services
    with pytest.raises(commands.ApplicationCommandError, match='invalid_command'):
        commands.ApplicationCommand.for_project(project, 'inspect',
            admission_request_id=str(uuid4()))
    assert not calls


def test_strategy_admission_error_code_is_not_silent_success_or_private_text(services, monkeypatch):
    project, calls, _, _, Failure = services
    import research_y.strategy_admission as admission
    def failed(*args, **kwargs):
        raise Failure('admission_conflict')
    monkeypatch.setattr(admission, 'commit_approved_strategy', failed)
    command = commands.ApplicationCommand.for_project(project, 'admit_strategy',
        admission_request_id=str(uuid4()), admission_theme='Theme',
        admission_approved_by='Reviewer',
        admission_groups=(StrategyGroup('g','Group',
            (ApprovedTerm('one term','researcher',True),)),),
        approval_confirmed=True)
    with pytest.raises(commands.ApplicationCommandError, match='^admission_conflict$'):
        commands.execute_command(command)


@pytest.mark.parametrize('change', [
    {'review_id':'not-a-uuid'}, {'review_plan_sha256':'short'},
    {'review_reviewer_name':chr(0) + 'bad'}, {'review_reviewer_role':'fake'},
    {'review_items':{}}, {'review_note':'bad' + chr(0) + 'data'},
    {'review_known_relevant':['PMID123']},
    {'directory':'/private/folder'}, {'export_id':'x'},
])
def test_preflight_review_command_strict_input_validation(services, change):
    project, calls, *_ = services
    from research_y.preflight_review import PRESS_ITEMS
    args=dict(run_id=str(uuid4()),review_id=str(uuid4()),
        review_plan_sha256='b'*64, review_reviewer_name='Researcher',
        review_reviewer_role='researcher_self_check',
        review_items={k:'not_reviewed' for k in PRESS_ITEMS},
        review_note='',review_known_relevant=())
    args.update(change)
    with pytest.raises(commands.ApplicationCommandError, match='invalid_command'):
        commands.ApplicationCommand.for_project(project,'preflight_record',**args)
    assert not calls


def test_preflight_read_can_target_exact_review_uuid_without_other_review_fields(services):
    project,calls,*_=services
    review_id=str(uuid4())
    command=commands.ApplicationCommand.for_project(
        project,'preflight_read',run_id=str(uuid4()),review_id=review_id)
    commands.execute_command(command)
    assert calls[0][0]=='preflight_read'
    assert calls[0][2] == {'review_id':review_id}
    for bad in ({'review_id':'fake'}, {'review_note':'secret'}):
        with pytest.raises(commands.ApplicationCommandError, match='invalid_command'):
            commands.ApplicationCommand.for_project(
                project,'preflight_read',run_id=str(uuid4()),**bad)
    with pytest.raises(commands.ApplicationCommandError, match='invalid_command'):
        commands.ApplicationCommand.for_project(
            project,'inspect',run_id=str(uuid4()),review_note='secret')


def _pilot_args():
    return dict(run_id=str(uuid4()),pilot_id=str(uuid4()),
                pilot_query_id=str(uuid4()),pilot_plan_sha256='a'*64,
                pilot_contact_email='synthetic@example.org',
                pilot_api_key='fixture-private-key-123',pilot_confirmed=True)


@pytest.mark.parametrize('edit', [
    {'pilot_id':'not-uuid'}, {'run_id':None}, {'pilot_query_id':None},
    {'pilot_plan_sha256':'A'*64}, {'pilot_plan_sha256':None},
    {'pilot_contact_email':None}, {'pilot_contact_email':'invalid'},
    {'pilot_contact_email':'x@domain.test'+chr(0)},
    {'pilot_api_key':'private'+chr(10)+'secret'},
    {'pilot_api_key':123}, {'pilot_confirmed':False},
    {'pilot_confirmed':1}, {'export_id':'unexpected'},
    {'directory':'/not/allowed'}, {'output_name':'secret.xlsx'},
    {'review_id':str(uuid4())}, {'admission_request_id':str(uuid4())},
])
def test_pilot_command_rejects_unconfirmed_or_malformed_payload(services, edit):
    project,calls,*_ = services
    args=_pilot_args()
    args.update(edit)
    with pytest.raises(commands.ApplicationCommandError,match='^invalid_command$'):
        commands.ApplicationCommand.for_project(project,'pubmed_pilot_count',**args)
    assert calls==[]


@pytest.mark.parametrize('edit', [
    {'pilot_id':'not-uuid'}, {'run_id':str(uuid4())},
    {'pilot_api_key':'private'}, {'pilot_confirmed':True},
    {'pilot_query_id':str(uuid4())}, {'pilot_contact_email':'example@example.org'},
])
def test_observing_pilot_by_id_rejects_network_fields(services,edit):
    project,calls,*_ = services
    args={'pilot_id':str(uuid4())}
    args.update(edit)
    with pytest.raises(commands.ApplicationCommandError,match='^invalid_command$'):
        commands.ApplicationCommand.for_project(project,'pubmed_pilot_read',**args)
    assert calls==[]


def test_non_pilot_commands_reject_pilot_credentials_and_no_repr_echo(services):
    project,calls,*_=services
    key='SECRET-private-api-key-333'
    with pytest.raises(commands.ApplicationCommandError,match='invalid_command'):
        commands.ApplicationCommand.for_project(project,'inspect',
            pilot_api_key=key)
    valid=commands.ApplicationCommand.for_project(project,'pubmed_pilot_count',
                                                  **_pilot_args())
    assert 'synthetic@example.org' not in repr(valid)
    assert 'fixture-private-key' not in repr(valid)
    assert calls==[]


@pytest.mark.parametrize('operation', ['wos_pilot_sample','wos_pilot_read'])
def test_wos_commands_reject_misrouted_secrets_and_unconfirmed_calls(services, operation):
    project,calls,*_=services
    kwargs={'pilot_id':str(uuid4())}
    if operation=='wos_pilot_sample':
        kwargs.update(run_id=str(uuid4()),pilot_query_id=str(uuid4()),
            pilot_plan_sha256='a'*64,pilot_api_key='PRIVATE-TEST-KEY',
            pilot_confirmed=True,pilot_wos_revalidate_quota=False)
        edits=({'pilot_contact_email':'private@example.org'},
               {'pilot_wos_revalidate_quota':None},
               {'pilot_wos_revalidate_quota':1},
               {'pilot_confirmed':False},
               {'pilot_api_key':None},
               {'pilot_api_key':'unsafe\nvalue'})
    else:
        edits=({'pilot_api_key':'PRIVATE-TEST-KEY'},
               {'pilot_wos_revalidate_quota':False},
               {'pilot_query_id':str(uuid4())})
    for edit in edits:
        with pytest.raises(commands.ApplicationCommandError,match='^invalid_command$'):
            commands.ApplicationCommand.for_project(project,operation,**(kwargs|edit))
    assert not calls


@pytest.mark.parametrize('value',[
    True,False,0,-1,1.5,'5',[],{},2**63,None,
])
def test_history_cursor_rejects_unsafe_values(services,value):
    project,calls,*_=services
    if value is None:
        cmd=commands.ApplicationCommand.for_project(
            project,'pilot_history',history_before_event_id=None)
        assert cmd.history_before_event_id is None
    else:
        with pytest.raises(commands.ApplicationCommandError,match='invalid_command'):
            commands.ApplicationCommand.for_project(
                project,'pilot_history',history_before_event_id=value)
    assert not calls


def test_history_cursor_and_pilot_credentials_cannot_be_sent_on_unrelated_command(services):
    project,calls,*_=services
    kwargs=({'history_before_event_id':1,'run_id':str(uuid4())},
            {'history_before_event_id':1,'pilot_api_key':'PRIVATE'},
            {'history_before_event_id':1,'directory':str(project.root)},
            {'history_before_event_id':1,'review_id':str(uuid4())})
    for kw in kwargs:
        with pytest.raises(commands.ApplicationCommandError,match='invalid_command'):
            commands.ApplicationCommand.for_project(project,'pilot_history',**kw)
    with pytest.raises(commands.ApplicationCommandError,match='invalid_command'):
        commands.ApplicationCommand.for_project(
            project,'inspect',history_before_event_id=1)
    assert not calls


@pytest.mark.parametrize('operation,patch',[
    ('wos_acquisition_verify_plan',{'acquisition_api_key':'PRIVATE'}),
    ('wos_acquisition_pause',{'acquisition_confirmed':True}),
    ('wos_acquisition_verify',{'acquisition_confirmed':False}),
    ('wos_acquisition_verify',{'verification_expected_requests':2}),
    ('wos_acquisition_verify',{'verification_expected_requests':513}),
    ('wos_acquisition_verify',{'verification_expected_requests':'24'}),
    ('wos_acquisition_verify',{'verification_expected_requests':True}),
    ('wos_acquisition_verify',{'acquisition_retention_authorized':True}),
    ('wos_acquisition_verify',{'acquisition_api_key':'NO\nGOOD'}),

    ('wos_acquisition_preview',{'acquisition_api_key':'SECRET'}),
    ('wos_acquisition_read',{'acquisition_api_key':'SECRET'}),
    ('wos_acquisition_read',{'acquisition_confirmed':True}),
    ('wos_acquisition_read',{'acquisition_revalidate_quota':False}),
    ('wos_acquisition_prepare',{'acquisition_api_key':'SECRET'}),
    ('wos_acquisition_prepare',{'acquisition_confirmed':False}),
    ('wos_acquisition_prepare',{'acquisition_retention_authorized':False}),
    ('wos_acquisition_prepare',{'acquisition_plan_sha256':'bad'}),
    ('wos_acquisition_tick',{'acquisition_confirmed':False}),
    ('wos_acquisition_tick',{'acquisition_api_key':'BAD\nPRIVATE'}),
    ('wos_acquisition_tick',{'acquisition_retention_authorized':True}),
    ('wos_acquisition_tick',{'acquisition_revalidate_quota':None}),
    ('wos_acquisition_tick',{'acquisition_revalidate_quota':1}),
])
def test_wos_acquisition_command_rejects_unapproved_or_cross_operation_fields(
        services,operation,patch):
    project,calls,*_=services
    base=dict(run_id=str(uuid4()),acquisition_query_id=str(uuid4()))
    if operation=='wos_acquisition_verify':
        base.update(acquisition_plan_sha256='a'*64,acquisition_confirmed=True,
                    acquisition_api_key='SYNTHETIC-PRIVATE-STARTER-KEY',
                    acquisition_revalidate_quota=False,
                    verification_expected_requests=24)
    if operation=='wos_acquisition_prepare':
        base.update(acquisition_plan_sha256='a'*64,
                    acquisition_retention_authorized=True,
                    acquisition_confirmed=True)
    if operation=='wos_acquisition_tick':
        base.update(acquisition_api_key='SYNTHETIC-PRIVATE-STARTER-KEY',
                    acquisition_confirmed=True,acquisition_revalidate_quota=False)
    with pytest.raises(commands.ApplicationCommandError,match='invalid_command'):
        commands.ApplicationCommand.for_project(project,operation,**(base|patch))
    assert not calls


def test_acquisition_key_cannot_be_routed_to_inspection_or_pilot(services):
    project,calls,*_=services
    for operation in ('inspect','pubmed_pilot_read','wos_pilot_read',
                      'pilot_history'):
        kw={'acquisition_api_key':'SECRET'}
        if operation.endswith('_read'):
            kw['pilot_id']=str(uuid4())
        with pytest.raises(commands.ApplicationCommandError,match='invalid_command'):
            commands.ApplicationCommand.for_project(project,operation,**kw)
    assert not calls



@pytest.mark.parametrize('operation', [
    'inspect','wos_acquisition_tick','wos_acquisition_read',
    'wos_acquisition_verify_plan','wos_acquisition_pause',
])
def test_extended_verification_budget_never_routes_through_other_commands(services,operation):
    project,calls,*_=services
    kwargs={'verification_expected_requests':5}
    if operation!='inspect':
        kwargs.update(run_id=str(uuid4()),acquisition_query_id=str(uuid4()))
    if operation=='wos_acquisition_tick':
        kwargs.update(acquisition_confirmed=True,
                      acquisition_revalidate_quota=False,
                      acquisition_api_key='SYNTHETIC-PRIVATE-STARTER-KEY')
    with pytest.raises(commands.ApplicationCommandError,match='invalid_command'):
        commands.ApplicationCommand.for_project(project,operation,**kwargs)
    assert not calls



@pytest.mark.parametrize('operation,changes',[
    ('pubmed_identifier_read',{'pubmed_source_api_key':'SECRET'}),
    ('pubmed_identifier_preview',{'pubmed_source_confirmed':True}),
    ('pubmed_identifier_pause',{'pubmed_source_plan_sha256':'a'*64}),
    ('pubmed_identifier_run',{'pubmed_source_confirmed':False}),
    ('pubmed_identifier_run',{'pubmed_source_api_key':'BAD\nKEY'}),
    ('pubmed_identifier_run',{'pubmed_source_plan_sha256':'invalid'}),
    ('pubmed_identifier_run',{'pubmed_coverage_start':'2026-12-30',
                              'pubmed_coverage_end':'2025-01-01'}),
    ('pubmed_identifier_run',{'pubmed_coverage_start':'2026-11-4'}),
    ('pubmed_identifier_run',{'pubmed_coverage_end':'abc'}),
])
def test_pubmed_source_commands_validate_own_trusted_fields_only(
        services,operation,changes):
    project,calls,*_=services
    attrs=dict(run_id=str(uuid4()),pubmed_source_query_id=str(uuid4()))
    if operation=='pubmed_identifier_run':
        attrs.update(pubmed_source_plan_sha256='a'*64,
                     pubmed_coverage_start='1800-01-01',
                     pubmed_coverage_end='2026-11-04',
                     pubmed_source_confirmed=True,
                     pubmed_source_contact_email='fixture@example.org',
                     pubmed_source_api_key='PRIVATE-PUBMED-KEY')
    with pytest.raises(commands.ApplicationCommandError,match='invalid_command'):
        commands.ApplicationCommand.for_project(project,operation,**(attrs|changes))
    assert not calls


@pytest.mark.parametrize('operation',[
    'inspect','pubmed_pilot_read','wos_acquisition_read',
    'pilot_history','wos_acquisition_verify_plan',
])
def test_pubmed_identifier_key_cannot_be_routed_to_unrelated_commands(
        services,operation):
    project,calls,*_=services
    attrs={'pubmed_source_api_key':'PRIVATE'}
    if operation=='pubmed_pilot_read':
        attrs['pilot_id']=str(uuid4())
    if operation in ('wos_acquisition_read','wos_acquisition_verify_plan'):
        attrs.update(run_id=str(uuid4()),acquisition_query_id=str(uuid4()))
    with pytest.raises(commands.ApplicationCommandError,match='invalid_command'):
        commands.ApplicationCommand.for_project(project,operation,**attrs)
    assert not calls
