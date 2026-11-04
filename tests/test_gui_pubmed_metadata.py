"""P1-06h2: EFetch metadata/abstracts through frozen source and real SQLite.

No live source access in CI. Synthetic EFetch XML flows through the original
parser, audited metadata store, and explicit GUI trust boundaries. A fake
supervisor only models the asynchronous returned/lost-child states.
"""
from contextlib import closing
from datetime import date
import inspect
import json
import sqlite3
from urllib.error import URLError
from urllib.parse import parse_qs
from uuid import uuid4

import pytest

from research_y.projects import create_project, open_project
from research_y.storage import ApprovedTerm, StrategyGroup
from research_y.strategy_admission import commit_approved_strategy
from research_y.pubmed_checkpoint_store import (
    create_pubmed_checkpoint, commit_pubmed_checkpoint_page,
    _set_checkpoint_status,
)
from research_y.pubmed_partition import PubMedPartitionResult, DateWindow
from research_y.pubmed_ids import PubMedIdentifierPage
from research_y.pubmed_probe import PubMedESearchProbeClient
from research_y.pubmed_metadata import PubMedEFetchClient
from research_y.pubmed_metadata_store import missing_pubmed_metadata_pmids
from research_y.pubmed_metadata_gui import (
    inspect_pubmed_metadata, preview_pubmed_metadata,
    run_pubmed_metadata_session, PubMedMetadataGUIError,
)
from research_y.application_worker import OperationStatus
from tools.gui_feasibility.pubmed_host_profile import PubMedHostProfile
from tools.gui_feasibility.real_project_flow import RealProjectFlow, ProjectFlowError
from tools.gui_feasibility.real_project_app import run as gui_main

EMAIL="private@synthetic.example"
KEY="PRIVATE-SYNTHETIC-NCBI-KEY"
TITLE="PRIVATE-LICENSED-SYNTHETIC-ARTICLE"
IDS=tuple(str(1000000+i) for i in range(1,28))
UTC="2026-11-04T20:00:00+00:00"


def _project(tmp_path,*,ids=IDS,identifiers_ready=True):
    project=create_project(tmp_path,"EFetch GUI fixture")
    approved=commit_approved_strategy(
        project,request_id=str(uuid4()),theme="ECMO literature",
        approved_by="Researcher",approval_confirmed=True,
        groups=(StrategyGroup("g-ecmo","Extracorporeal",(
            ApprovedTerm("ECMO","researcher",True),)),))
    with closing(sqlite3.connect(project.database_path)) as db:
        row=db.execute(
            "SELECT query_id,exact_query FROM source_queries "
            "WHERE run_id=? AND source_name='pubmed'",(approved.run_id,)).fetchone()
    qid,query=row
    if identifiers_ready:
        plan=PubMedPartitionResult(
            query,DateWindow(date(2025,1,1),date(2025,1,2)),len(ids),
            "identifiers_reconciled_metadata_pending",(),(),())
        create_pubmed_checkpoint(project,qid,plan,page_size=max(1,len(ids)))
        if ids:
            commit_pubmed_checkpoint_page(
                project,qid,PubMedIdentifierPage(
                    exact_query=query,retstart=0,requested_retmax=len(ids),
                    reported_matches=len(ids),pmids=tuple(ids),
                    accepted_translation=query,warnings=(),review_reasons=(),
                    response_sha256='a'*64,retrieved_at_utc=UTC))
        _set_checkpoint_status(
            project,qid,'identifiers_reconciled_metadata_pending',
            'Synthetic source identifier checkpoint independently reconciled')
    return project,approved.run_id,qid,query


def _flow(tmp_path,*,ids=IDS,profile=True,identifiers_ready=True):
    project,rid,qid,query=_project(
        tmp_path,ids=ids,identifiers_ready=identifiers_ready)
    flow=RealProjectFlow(selected_root=project.root,selected_parent=tmp_path,
                         pubmed_profile=PubMedHostProfile(EMAIL,KEY) if profile else None)
    flow.open_selected()
    flow.select_run(rid)
    return project,flow,rid,qid,query


def _db(project):
    with closing(sqlite3.connect(project.database_path)) as db:
        return dict(
            records=db.execute(
                "SELECT original_metadata_json FROM source_retrievals "
                "WHERE source_name='pubmed' ORDER BY source_record_id").fetchall(),
            membership=db.execute(
                "SELECT COUNT(*) FROM query_retrievals WHERE source_name='pubmed'").fetchone()[0],
            audits=db.execute(
                "SELECT COUNT(*) FROM audit_events "
                "WHERE event_type='pubmed_efetch_metadata_committed'").fetchone()[0],
            query=db.execute(
                "SELECT status,reported_matches FROM source_queries "
                "WHERE source_name='pubmed' LIMIT 1").fetchone())


def _xml(pmids):
    articles=[]
    for index,pmid in enumerate(pmids):
        abstract=("<Abstract><AbstractText>PRIVATE-SYNTHETIC-ABSTRACT</AbstractText>"
                  "</Abstract>" if int(pmid)%2 else "")
        articles.append(
            '<PubmedArticle><MedlineCitation Status="MEDLINE">'
            '<PMID>'+pmid+'</PMID><Article><ArticleTitle>'+TITLE+'</ArticleTitle>'
            '<Journal><Title>Synthetic Journal</Title></Journal>'
            +abstract+
            '<Language>eng</Language></Article></MedlineCitation>'
            '<PubmedData><ArticleIdList><ArticleId IdType="pubmed">'+pmid+
            '</ArticleId></ArticleIdList></PubmedData></PubmedArticle>')
    return ('<?xml version="1.0"?><PubmedArticleSet>'+
            ''.join(articles)+'</PubmedArticleSet>').encode()


class Provider:
    def __init__(self,*,fail_at=None,bad_ids=False):
        self.calls=[]
        self.fail_at=fail_at
        self.bad_ids=bad_ids

    def __call__(self,req,timeout):
        assert req.full_url=='https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi'
        assert req.get_method()=='POST'
        assert timeout==15
        fields=parse_qs(req.data.decode())
        assert fields['db']==['pubmed'] and fields['retmode']==['xml']
        assert fields['tool']==['RESEARCHY'] and fields['email']==[EMAIL]
        assert fields['api_key']==[KEY]
        pmids=tuple(fields['id'][0].split(','))
        assert 1<=len(pmids)<=20
        self.calls.append(pmids)
        if self.fail_at is not None and len(self.calls)==self.fail_at:
            raise URLError("PRIVATE-PROVIDER-TRANSPORT-ERROR")
        return _xml(('99999999',) if self.bad_ids else pmids)


def _client(transport):
    # Synthetic clock advances beyond mandatory pacing intervals.
    clock=[10000.]
    def now():
        clock[0]+=1.
        return clock[0]
    return PubMedEFetchClient(
        PubMedESearchProbeClient(
            email=EMAIL,api_key=KEY,timeout=15,
            clock=now,sleep=lambda _:None,
            transport=lambda r,t:b"NO-ESEARCH-IN-EFETCH"),
        transport=transport)


class Supervisor:
    def __init__(self):
        self.id=str(uuid4())
        self.command=None
        self.state='running'
        self.receipt=None
        self.error=None
        self.calls=0
        self.closed=False

    def submit(self,command):
        assert self.command is None
        assert command.operation=='pubmed_metadata_run'
        self.command=command
        self.calls+=1
        return self.id

    def poll(self,operation_id):
        assert operation_id==self.id
        return OperationStatus(
            self.id,'pubmed_metadata_run',None,self.state,self.error,
            None if self.receipt is None else json.dumps(self.receipt))

    def close(self,*,grace_seconds=0,kill_seconds=2):
        self.closed=True


def test_no_identifiers_or_unreconciled_identifier_stage_never_sends_metadata(
        tmp_path):
    project,flow,rid,qid,query=_flow(tmp_path,identifiers_ready=False)
    try:
        raw=inspect_pubmed_metadata(project,run_id=rid,query_id=qid)
        assert raw['status']=='identifiers_not_acquired'
        assert raw['identifier_count'] is None
        assert raw['no_network_requests'] is True
        with pytest.raises(PubMedMetadataGUIError,match='pubmed_metadata_not_ready'):
            preview_pubmed_metadata(project,run_id=rid,query_id=qid)
        assert _db(project)['records']==[]
    finally:
        flow.close()


def test_zero_identifier_checkpoint_is_explicit_no_efetch_request(tmp_path):
    project,rid,qid,query=_project(tmp_path,ids=())
    state=inspect_pubmed_metadata(project,run_id=rid,query_id=qid)
    assert state['identifier_count']==0
    assert state['metadata_records_pending']==0
    assert state['status']=='no_identifiers'
    assert state['metadata_records_reconciled'] is True
    with pytest.raises(PubMedMetadataGUIError,match='pubmed_metadata_already_acquired'):
        preview_pubmed_metadata(project,run_id=rid,query_id=qid)
    assert _db(project)['records']==[]


def test_read_only_metadata_inspection_on_reopened_project_without_host_credentials(
        tmp_path):
    project,flow,rid,qid,query=_flow(tmp_path,profile=False)
    before=_db(project)
    try:
        state=flow.inspect_stored_pubmed_metadata(qid)['pubmed_metadata']
        assert state['status']=='metadata_not_started'
        assert state['identifier_count']==27
        assert state['metadata_records_committed']==0
        assert state['metadata_records_pending']==27
        assert state['no_network_requests'] is True
        with pytest.raises(ProjectFlowError,match='pubmed_profile_unavailable'):
            flow.offer_pubmed_metadata(qid)
        assert _db(project)==before
    finally:
        flow.close()
    reopened=open_project(project.root)
    assert inspect_pubmed_metadata(
        reopened,run_id=rid,query_id=qid)['metadata_records_pending']==27


def test_consent_gated_session_fetches_source_records_with_abstract_availability(
        tmp_path):
    project,flow,rid,qid,query=_flow(tmp_path)
    provider=Provider()
    supervisor=Supervisor()
    flow._pubmed_metadata_worker.close()
    flow._pubmed_metadata_worker=supervisor
    try:
        before=_db(project)
        offer=flow.offer_pubmed_metadata(qid)
        candidate=offer['pubmed_metadata_offer']
        assert candidate['exact_query']==query
        assert candidate['metadata_records_pending']==27
        assert candidate['max_batch_size']==20
        assert candidate['max_session_batches']==100
        assert _db(project)==before and provider.calls==[]
        flow.dismiss_pubmed_metadata()
        with pytest.raises(ProjectFlowError,match='pubmed_metadata_confirmation_required'):
            flow.confirm_pubmed_metadata()
        flow.offer_pubmed_metadata(qid)
        pending=flow.confirm_pubmed_metadata()
        assert pending['pubmed_metadata_pending'] is True
        assert supervisor.calls==1
        assert supervisor.command.pubmed_source_contact_email==EMAIL
        assert supervisor.command.pubmed_source_api_key==KEY
        assert KEY not in repr(supervisor.command)
        assert KEY not in json.dumps(pending)
        with pytest.raises(ProjectFlowError,match='pubmed_metadata_reconciliation_required'):
            flow.select_run(rid)
        with pytest.raises(ProjectFlowError,match='pubmed_metadata_reconciliation_required'):
            flow.confirm_pubmed_metadata()
        assert flow.poll_pubmed_metadata()['pubmed_metadata_pending']
        assert provider.calls==[]
        result=run_pubmed_metadata_session(
            project,run_id=rid,query_id=qid,
            expected_plan_sha256=supervisor.command.pubmed_source_plan_sha256,
            confirmed=True,client=_client(provider))
        assert result['status']=='metadata_acquired_reconciliation_pending'
        assert result['successful_batches']==2
        assert result['metadata_records_committed']==27
        assert result['metadata_records_pending']==0
        assert result['metadata_records_reconciled'] is True
        assert not result['unknown_inflight_request_possible']
        assert not result['source_retrieval_verified']
        assert len(provider.calls)==2
        assert provider.calls[0]==IDS[:20] and provider.calls[1]==IDS[20:]
        saved=flow.poll_pubmed_metadata()['pubmed_metadata']
        assert saved['abstract_present']==14
        assert saved['abstract_not_supplied']==13
        assert saved['metadata_records_reconciled'] is True
        assert KEY not in json.dumps(saved) and TITLE not in json.dumps(saved)
        assert all(p not in json.dumps(saved) for p in IDS)
        supervisor.state='returned'
        supervisor.receipt=result
        done=flow.reconcile_pubmed_metadata()
        assert done['pubmed_metadata_pending'] is False
        assert done['pubmed_metadata_last_outcome']['successful_batches']==2
        assert done['pubmed_metadata_last_outcome']['whole_search_verified'] is False
        assert done['report']['status']=='incomplete'
        assert done['pubmed_source']['checkpoint']['metadata_records_linked']==27
        assert KEY not in json.dumps(done)
        assert TITLE not in json.dumps(done)
        db=_db(project)
        assert len(db['records'])==db['membership']==27
        assert db['audits']==2
        originals=[json.loads(row[0]) for row in db['records']]
        assert all(x['rights_review_required_for_abstract_redistribution'] for x in originals)
        assert all(x['record']['title']==TITLE for x in originals)
        assert db['query'][0]=='incomplete'
        with pytest.raises(PubMedMetadataGUIError,match='pubmed_metadata_already_acquired'):
            preview_pubmed_metadata(project,run_id=rid,query_id=qid)
    finally:
        flow.close()
    assert supervisor.closed is True


def test_partial_failure_preserves_original_rows_and_requires_new_consent(
        tmp_path):
    project,flow,rid,qid,query=_flow(tmp_path)
    supervisor=Supervisor()
    flow._pubmed_metadata_worker.close()
    flow._pubmed_metadata_worker=supervisor
    provider=Provider(fail_at=2)
    try:
        flow.offer_pubmed_metadata(qid)
        flow.confirm_pubmed_metadata()
        partial=run_pubmed_metadata_session(
            project,run_id=rid,query_id=qid,
            expected_plan_sha256=supervisor.command.pubmed_source_plan_sha256,
            confirmed=True,client=_client(provider))
        assert partial['status']=='incomplete'
        assert partial['successful_batches']==1
        assert partial['metadata_records_committed']==20
        assert partial['metadata_records_pending']==7
        assert partial['unknown_inflight_request_possible'] is True
        assert len(provider.calls)==2
        supervisor.state='returned'
        supervisor.receipt=partial
        outcome=flow.reconcile_pubmed_metadata()
        assert outcome['pubmed_metadata_pending'] is False
        assert outcome['pubmed_metadata_last_outcome']['session_status']=='incomplete'
        assert outcome['pubmed_metadata']['metadata_records_pending']==7
        assert len(_db(project)['records'])==20
        with pytest.raises(ProjectFlowError,match='pubmed_metadata_reconciliation_not_required'):
            flow.reconcile_pubmed_metadata()
    finally:
        flow.close()

    # A NEW local session with an explicit independent consent reuses saved
    # records and never fetches the successful original batch again.
    newflow=RealProjectFlow(
        selected_root=project.root,selected_parent=tmp_path,
        pubmed_profile=PubMedHostProfile(EMAIL,KEY))
    newflow.open_selected();newflow.select_run(rid)
    provider2=Provider()
    supervisor2=Supervisor()
    newflow._pubmed_metadata_worker.close()
    newflow._pubmed_metadata_worker=supervisor2
    try:
        newflow.offer_pubmed_metadata(qid)
        newflow.confirm_pubmed_metadata()
        receipt=run_pubmed_metadata_session(
            project,run_id=rid,query_id=qid,
            expected_plan_sha256=supervisor2.command.pubmed_source_plan_sha256,
            confirmed=True,client=_client(provider2))
        assert receipt['metadata_records_committed']==27
        assert provider2.calls==[IDS[20:]]
        supervisor2.state='returned';supervisor2.receipt=receipt
        newflow.reconcile_pubmed_metadata()
        assert len(_db(project)['records'])==27
        assert _db(project)['audits']==2
    finally:
        newflow.close()


def test_rejected_or_corrupt_efetch_batch_never_persists_its_records(tmp_path):
    project,rid,qid,query=_project(tmp_path)
    proposal=preview_pubmed_metadata(project,run_id=rid,query_id=qid)
    bad=Provider(bad_ids=True)
    receipt=run_pubmed_metadata_session(
        project,run_id=rid,query_id=qid,
        expected_plan_sha256=proposal['plan_sha256'],
        confirmed=True,client=_client(bad))
    assert receipt['status']=='incomplete'
    assert receipt['metadata_records_committed']==0
    assert receipt['metadata_records_pending']==27
    assert len(_db(project)['records'])==0
    assert receipt['source_retrieval_verified'] is False


def test_wrong_source_or_modified_frozen_expression_fails_before_efetch(tmp_path):
    project,flow,rid,qid,query=_flow(tmp_path)
    provider=Provider()
    try:
        with pytest.raises(ProjectFlowError,match='unknown_pubmed_query'):
            flow.offer_pubmed_metadata(str(uuid4()))
        original=flow.offer_pubmed_metadata(qid)['pubmed_metadata_offer']
        with closing(sqlite3.connect(project.database_path)) as db,db:
            db.execute("UPDATE source_queries SET exact_query=? WHERE query_id=?",
                       ('("BAD"[All Fields])',qid))
        with pytest.raises(ProjectFlowError):
            flow.confirm_pubmed_metadata()
        assert provider.calls==[] and len(_db(project)['records'])==0
    finally:
        flow.close()


def test_mismatched_worker_receipt_is_not_treated_as_success_and_lock_remains(tmp_path):
    project,flow,rid,qid,query=_flow(tmp_path)
    supervisor=Supervisor()
    flow._pubmed_metadata_worker.close()
    flow._pubmed_metadata_worker=supervisor
    try:
        flow.offer_pubmed_metadata(qid)
        flow.confirm_pubmed_metadata()
        supervisor.state='returned'
        supervisor.receipt=dict(run_id=rid,query_id=qid,
                                status='metadata_acquired_reconciliation_pending',
                                source_retrieval_verified=False)
        with pytest.raises(ProjectFlowError,match='pubmed_metadata_receipt_invalid'):
            flow.reconcile_pubmed_metadata()
        assert flow.state()['pubmed_metadata_pending'] is True
        supervisor.state='interrupted'
        supervisor.error='worker_interrupted'
        supervisor.receipt=None
        last=flow.reconcile_pubmed_metadata()['pubmed_metadata_last_outcome']
        assert last['worker_state']=='interrupted'
        assert last['successful_batches'] is None
        assert last['whole_search_verified'] is False
        assert len(_db(project)['records'])==0
    finally:
        flow.close()


def test_completed_metadata_is_not_automatically_requeried_and_no_profile_reads(
        tmp_path):
    project,rid,qid,query=_project(tmp_path,ids=IDS[:2])
    preview=preview_pubmed_metadata(project,run_id=rid,query_id=qid)
    done=run_pubmed_metadata_session(
        project,run_id=rid,query_id=qid,
        expected_plan_sha256=preview['plan_sha256'],
        confirmed=True,client=_client(Provider()))
    assert done['status']=='metadata_acquired_reconciliation_pending'
    flow=RealProjectFlow(selected_root=project.root,selected_parent=tmp_path)
    try:
        flow.open_selected();flow.select_run(rid)
        read=flow.inspect_stored_pubmed_metadata(qid)['pubmed_metadata']
        assert read['metadata_records_committed']==2
        assert read['metadata_records_pending']==0
        assert read['metadata_records_reconciled'] is True
        with pytest.raises(ProjectFlowError,match='pubmed_profile_unavailable'):
            flow.offer_pubmed_metadata(qid)
    finally:
        flow.close()


def test_gui_buttons_never_include_efetch_in_probe_automated_route():
    src=inspect.getsource(gui_main)
    for marker in ('pubmed_metadata_read','pubmed_metadata_offer',
                   'pubmed_metadata_confirm','pubmed_metadata_poll',
                   'pubmed_metadata_reconcile'):
        assert "name == '"+marker+"'" in src
    for marker in ('pubmed-metadata-heading','pubmed-metadata-confirm',
                   'pubmed-metadata-progress','pubmed-metadata-saved'):
        assert "data-testid="+marker in src
    assert "await act('pubmed_metadata_poll')" in src
    block=src.split("@app.post('/_probe/start')")[1].split(
        "@app.post('/_probe/stop')")[0]
    assert 'pubmed_metadata' not in block
    assert 'ui.html(' not in src
