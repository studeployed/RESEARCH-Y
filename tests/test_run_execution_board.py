"""P1-06i1 combined execution board: real approvals, checkpoints and SQLite.

Every fixture is offline. A source-count reconciliation or metadata commit
does not establish full literature-search completion or unique publications.
"""
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import inspect
import json
import sqlite3
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
from research_y.pubmed_partition import DateWindow, PubMedPartitionResult
from research_y.pubmed_ids import PubMedIdentifierPage
from research_y.pubmed_metadata import parse_efetch_xml
from research_y.pubmed_metadata_store import commit_pubmed_metadata_batch
from research_y.wos_checkpoint_store import create_wos_checkpoint
from research_y.wos_checkpoint_runner import run_wos_checkpoint
from research_y.wos_starter_client import WoSStarterClient, WoSHTTPResponse
from research_y.run_execution_board import (
    read_run_execution_board, ExecutionBoardError,
)
from research_y.application_commands import ApplicationCommand, execute_command
from tools.gui_feasibility.real_project_flow import RealProjectFlow, ProjectFlowError
from tools.gui_feasibility.wos_host_profile import WoSHostProfile
from tools.gui_feasibility.pubmed_host_profile import PubMedHostProfile
from tools.gui_feasibility.real_project_app import run as gui_run

KEY = "PRIVATE-FAKE-STARTER-KEY"
EMAIL = "private@synthetic.example"
UTC = "2026-11-04T22:00:00+00:00"


def _project(tmp_path):
    project = create_project(tmp_path, "Combined source execution fixture")
    approval = commit_approved_strategy(
        project, request_id=str(uuid4()), theme="Right heart research",
        approved_by="Researcher", approval_confirmed=True, groups=(
            StrategyGroup("g-ecmo", "Extracorporeal support", (
                ApprovedTerm("ECMO", "researcher", True),)),
            StrategyGroup("g-rv", "Right ventricle", (
                ApprovedTerm("right ventricle", "researcher", True),)),
        ))
    with closing(sqlite3.connect(project.database_path)) as db:
        saved = {(group, source):(qid, exact) for qid, group, source, exact
                 in db.execute("SELECT query_id,group_id,source_name,exact_query "
                               "FROM source_queries WHERE run_id=?",
                               (approval.run_id,))}
    assert len(saved) == 4
    return project, approval.run_id, saved


def _digest(project):
    return sha256(project.database_path.read_bytes()).hexdigest()


def _pubmed(project, qid, exact, pmids=("111", "222")):
    result = PubMedPartitionResult(
        exact, DateWindow(date(2025,1,1),date(2026,11,4)),
        len(pmids), "identifiers_reconciled_metadata_pending", (), (), ())
    create_pubmed_checkpoint(project, qid, result, page_size=max(1,len(pmids)))
    if pmids:
        page = PubMedIdentifierPage(
            exact_query=exact, retstart=0, requested_retmax=len(pmids),
            reported_matches=len(pmids), pmids=tuple(pmids),
            accepted_translation=exact, warnings=(), review_reasons=(),
            response_sha256="a"*64, retrieved_at_utc=UTC)
        commit_pubmed_checkpoint_page(project, qid, page)
    _set_checkpoint_status(project, qid,
        "identifiers_reconciled_metadata_pending", "Synthetic checked source count")


def _efetch(project, qid, pmids=("111", "222"), *, book_pmid=None):
    records = "".join(
        "<PubmedArticle><MedlineCitation Status='MEDLINE'>"
        f"<PMID>{pmid}</PMID><Article><ArticleTitle>PRIVATE TITLE</ArticleTitle>"
        "<Journal><Title>Private Journal</Title></Journal>"
        + ("<Abstract><AbstractText>PRIVATE ABSTRACT</AbstractText></Abstract>"
           if pmid == pmids[0] else "") +
        "</Article></MedlineCitation></PubmedArticle>"
        for pmid in pmids if pmid != book_pmid)
    if book_pmid is not None:
        records += (
            "<PubmedBookArticle><BookDocument>"
            f"<PMID>{book_pmid}</PMID><ArticleIdList/><Book><Publisher>"
            "<PublisherName>Fixture Press</PublisherName></Publisher><BookTitle>Fixture book</BookTitle>"
            "<PubDate><Year>2025</Year></PubDate></Book><ArticleTitle>Separate chapter</ArticleTitle>"
            "</BookDocument></PubmedBookArticle>")
    parsed = parse_efetch_xml(
        ("<?xml version='1.0'?><PubmedArticleSet>" +
         records + "</PubmedArticleSet>").encode(), pmids,
        retrieved_at_utc=UTC)
    return commit_pubmed_metadata_batch(project, qid, parsed)


class Clock:
    def __init__(self):
        self.instant=datetime.now(timezone.utc)
        self.seconds=0.0

    def now(self):
        return self.instant+timedelta(seconds=self.seconds)

    def monotonic(self):
        return 10000.0+self.seconds

    def sleep(self, seconds):
        self.seconds+=seconds


def _wos(project, qid, exact, *, count=1, clock=None, title="PRIVATE WOS TITLE"):
    create_wos_checkpoint(project, qid, retention_authorized=True)
    clock = clock or Clock()
    calls=[]
    def send(req, timeout):
        fields=parse_qs(req.full_url.split("?",1)[1])
        assert fields["q"] == [exact]
        assert fields["db"] == ["WOS"]
        assert req.get_method() == "GET"
        assert req.get_header("X-apikey") == KEY
        assert timeout==10
        page=int(fields["page"][0]); size=int(fields["limit"][0])
        calls.append((page,size))
        clock.sleep(2)
        hits=[dict(uid=f"WOS:{i+1:09d}",title=title)
              for i in range((page-1)*size,min(page*size,count))]
        body=json.dumps(dict(metadata=dict(total=count,page=page,limit=size),
                             hits=hits)).encode()
        return WoSHTTPResponse(200,dict(
            [("X-RateLimit-Limit-Day","5000"),
             ("X-RateLimit-Remaining-Day",str(4999-len(calls)))]),body)
    client=WoSStarterClient(
        api_key=KEY,request_budget=3,timeout=10,transport=send,
        clock=clock.monotonic,sleep=clock.sleep,utc_now=clock.now)
    result=run_wos_checkpoint(project,qid,client,max_requests=3,now=clock.now)
    assert calls==[(1,50),(1,50),(1,1)]
    assert result.enumeration_reconciled
    return calls


def _row(board,group,source):
    return next(item for item in board["queries"]
                if item["group_id"]==group and item["source_name"]==source)


def test_combined_board_lists_every_approved_or_group_without_inventing_zero(tmp_path):
    p,rid,queries=_project(tmp_path)
    before=_digest(p)
    board=read_run_execution_board(p,rid)
    assert _digest(p)==before
    assert board["method"]=="whole-run-execution-board/1"
    assert board["group_count"]==2 and board["query_count"]==4
    assert {r["group_id"] for r in board["groups"]}=={"g-rv","g-ecmo"}
    assert {q["source_name"] for q in board["queries"]}=={"wos","pubmed"}
    assert all(q["reported_matches"] is None for q in board["queries"])
    assert all(q["identifiers_retrieved"]==0 for q in board["queries"])
    assert all(q["count_reconciliation"]=="unknown" for q in board["queries"])
    assert all(q["whole_search_verified"] is False for q in board["queries"])
    assert _row(board,"g-ecmo","pubmed")["source_stage"]=="pubmed_identifiers_not_started"
    assert _row(board,"g-ecmo","wos")["source_stage"]=="wos_not_started"
    assert board["global_unique_publications"] is None
    assert board["totals"]["global_unique_publications"] is None
    assert board["totals"]["publication_identity_hypotheses"]==0
    assert not board["source_retrieval_verified"]
    assert not board["verified_complete"]
    assert not board["primary_source_enumerations_reconciled"]
    assert not board["available_primary_metadata_acquired"]
    assert board["no_network_requests"] is True


def test_pubmed_identifiers_metadata_and_wos_stages_keep_run_incomplete(tmp_path):
    p,rid,queries=_project(tmp_path)
    pmid,query=queries["g-ecmo","pubmed"]
    wos,wquery=queries["g-ecmo","wos"]
    _pubmed(p,pmid,query)
    without=read_run_execution_board(p,rid)
    q=_row(without,"g-ecmo","pubmed")
    assert q["reported_matches"]==2
    assert q["identifiers_retrieved"]==2 and q["metadata_records_retained"]==0
    assert q["metadata_records_missing"]==2
    assert q["source_stage"]=="pubmed_metadata_needed"
    assert q["next_step"]=="preview_pubmed_metadata"
    assert q["count_reconciliation"]=="equal"
    _efetch(p,pmid)
    _wos(p,wos,wquery)
    board=read_run_execution_board(p,rid)
    q=_row(board,"g-ecmo","pubmed")
    assert q["source_stage"]=="pubmed_metadata_acquired"
    assert q["metadata_records_retained"]==2
    assert q["metadata_records_missing"]==0
    w=_row(board,"g-ecmo","wos")
    assert w["source_stage"]=="wos_enumeration_reconciled_with_warnings"
    assert w["identifiers_retrieved"]==w["metadata_records_retained"]==1
    assert w["reported_matches"]==1 and w["verification_pages"]==1
    assert w["count_reconciliation"]=="equal"
    assert board["totals"]["source_records_by_provider"]=={"pubmed":2,"wos":1}
    assert board["totals"]["source_record_sum"]==3
    assert board["totals"]["publication_identity_hypotheses"]==0
    assert not board["primary_source_enumerations_reconciled"]  # RV group untouched
    assert not board["available_primary_metadata_acquired"]
    assert board["stored_run_status"]=="incomplete"
    assert board["global_unique_publications"] is None
    assert all(g["group_unique_publications"] is None for g in board["groups"])


def test_zero_pubmed_is_real_zero_and_other_missing_queries_remain_unknown(tmp_path):
    p,rid,queries=_project(tmp_path)
    qid,exact=queries["g-ecmo","pubmed"]
    _pubmed(p,qid,exact,pmids=())
    board=read_run_execution_board(p,rid)
    row=_row(board,"g-ecmo","pubmed")
    assert row["reported_matches"]==0
    assert row["count_reconciliation"]=="equal"
    assert row["source_stage"]=="pubmed_no_identifiers"
    assert row["metadata_records_missing"]==0
    assert _row(board,"g-rv","pubmed")["reported_matches"] is None
    assert board["primary_source_enumerations_reconciled"] is False


@pytest.mark.parametrize("case", ["complete", "missing_query", "unknown_count", "failed", "cancelled"])
def test_reopened_run_reconciles_against_approved_query_inventory(tmp_path, case):
    project, run_id, queries = _project(tmp_path)
    clock = Clock()
    for (group, source), (query_id, exact) in queries.items():
        if case == "missing_query" and (group, source) == ("g-rv", "wos"):
            with closing(sqlite3.connect(project.database_path)) as db, db:
                db.execute("DELETE FROM source_queries WHERE query_id=?", (query_id,))
        elif source == "pubmed":
            _pubmed(project, query_id, exact, pmids=("111",))
            _efetch(project, query_id, pmids=("111",))
        else:
            clock.sleep(60)
            _wos(project, query_id, exact, clock=clock)

    pubmed_id, _ = queries["g-rv", "pubmed"]
    with closing(sqlite3.connect(project.database_path)) as db, db:
        if case == "unknown_count":
            db.execute("UPDATE source_queries SET reported_matches=NULL WHERE query_id=?", (pubmed_id,))
        elif case in ("failed", "cancelled"):
            db.execute("UPDATE source_queries SET status=? WHERE query_id=?", (case, pubmed_id))
    reopened = open_project(project.root)
    before = _digest(reopened)
    board = read_run_execution_board(reopened, run_id)
    assert board["primary_source_enumerations_reconciled"] is (case == "complete")
    assert board["available_primary_metadata_acquired"] is (case == "complete")
    assert board["approved_query_inventory_matches"] is (case != "missing_query")
    assert ("approved_query_inventory_unverified" in board["warnings"]) is (case == "missing_query")
    assert board["totals"]["source_records_by_provider"] == {"pubmed": 1, "wos": 1}
    assert not board["verified_complete"]
    assert _digest(reopened) == before


def test_duplicate_group_memberships_are_unions_not_global_unique_publications(tmp_path):
    p,rid,queries=_project(tmp_path)
    for group in ("g-ecmo","g-rv"):
        qid,exact=queries[group,"pubmed"]
        _pubmed(p,qid,exact,pmids=("111",))
        _efetch(p,qid,pmids=("111",))
    board=read_run_execution_board(p,rid)
    assert all(_row(board,g,"pubmed")["metadata_records_retained"]==1
               for g in ("g-ecmo","g-rv"))
    assert board["totals"]["source_records_by_provider"]["pubmed"]==1
    assert board["totals"]["source_record_sum"]==1
    assert board["global_unique_publications"] is None
    assert all(g["group_unique_publications"] is None for g in board["groups"])
    assert board["totals"]["publication_identity_hypotheses"]==0


@pytest.mark.parametrize("damage", ["source", "response_hash", "unreceipted_hash", "timestamp", "rights", "abstract"])
def test_reopened_board_and_resume_require_retained_efetch_evidence(tmp_path, damage):
    from research_y.pubmed_metadata_store import (
        missing_pubmed_metadata_pmids, PubMedMetadataIntegrityError,
    )
    project, run_id, queries = _project(tmp_path)
    query_id, exact = queries["g-ecmo", "pubmed"]
    _pubmed(project, query_id, exact, pmids=("111",))
    _efetch(project, query_id, pmids=("111",))
    with closing(sqlite3.connect(project.database_path)) as db, db:
        raw, = db.execute("SELECT original_metadata_json FROM source_retrievals").fetchone()
        saved = json.loads(raw)
        if damage == "abstract":
            saved["record"]["abstract_sections"] = []
        else:
            key, value = {
                "source": ("source", "unverified import"),
                "response_hash": ("response_sha256", "invalid"),
                "unreceipted_hash": ("response_sha256", "0" * 64),
                "timestamp": ("retrieved_at_utc", "different"),
                "rights": ("rights_review_required_for_abstract_redistribution", False),
            }[damage]
            saved[key] = value
        db.execute("UPDATE source_retrievals SET original_metadata_json=?", (json.dumps(saved),))
    reopened = open_project(project.root)
    before = _digest(reopened)
    with pytest.raises(ExecutionBoardError):
        read_run_execution_board(reopened, run_id)
    with pytest.raises(PubMedMetadataIntegrityError):
        missing_pubmed_metadata_pmids(reopened, query_id)
    assert _digest(reopened) == before


def test_corrupted_provider_checkpoint_or_query_identity_fails_closed(tmp_path):
    p,rid,queries=_project(tmp_path)
    qid,exact=queries["g-ecmo","pubmed"]
    _pubmed(p,qid,exact)
    with closing(sqlite3.connect(p.database_path)) as db,db:
        db.execute("UPDATE source_queries SET exact_query=? WHERE query_id=?",
                   ('("UNAPPROVED"[All Fields])',qid))
    with pytest.raises(ExecutionBoardError,match="run_board_unavailable"):
        read_run_execution_board(p,rid)


def test_shared_pubmed_record_uses_its_original_batch_across_groups(tmp_path):
    from research_y.pubmed_metadata_store import missing_pubmed_metadata_pmids

    project, run_id, queries = _project(tmp_path)
    first, exact = queries["g-ecmo", "pubmed"]
    _pubmed(project, first, exact, pmids=("111",))
    _efetch(project, first, pmids=("111",))
    second, exact = queries["g-rv", "pubmed"]
    _pubmed(project, second, exact)
    _efetch(project, second)

    reopened = open_project(project.root)
    with closing(sqlite3.connect(reopened.database_path)) as db:
        batches = db.execute(
            "SELECT DISTINCT json_extract(details_json, '$.batch_sha256') FROM audit_events "
            "WHERE event_type='pubmed_efetch_metadata_committed'"
        ).fetchall()
    assert len(batches) == 2
    assert missing_pubmed_metadata_pmids(reopened, second) == ()
    board = read_run_execution_board(reopened, run_id)
    assert _row(board, "g-rv", "pubmed")["metadata_records_retained"] == 2
    assert board["totals"]["source_records_by_provider"]["pubmed"] == 2


@pytest.mark.parametrize("purpose", ["verify", "final"])
def test_reopened_board_requires_the_independent_wos_observations(tmp_path, monkeypatch, purpose):
    from dataclasses import replace
    from research_y import wos_checkpoint_store as store

    project, run_id, queries = _project(tmp_path)
    query_id, exact = queries["g-ecmo", "wos"]
    _wos(project, query_id, exact)
    reopened = open_project(project.root)
    before = _digest(reopened)
    original = store._read_observation

    def discrepant_observation(db, attempt_id, checked_query, checked_purpose):
        page = original(db, attempt_id, checked_query, checked_purpose)
        if checked_query == query_id and checked_purpose == purpose:
            return replace(page, reported_matches=page.reported_matches + 1)
        return page

    monkeypatch.setattr(store, "_read_observation", discrepant_observation)
    with pytest.raises(ExecutionBoardError, match="run_board_unavailable"):
        read_run_execution_board(reopened, run_id)
    assert _digest(reopened) == before


def test_two_source_reopen_review_and_published_workbook_preserve_every_membership(tmp_path):
    from openpyxl import load_workbook
    from research_y.provisional_manifest_intent import prepare_manifest_intent
    from research_y.provisional_manifest_stage import stage_manifest_workbook
    from research_y.provisional_manifest_publication import publish_manifest_workbook
    from research_y.publication_identity import materialise_retrieval
    from research_y.publication_results import read_publication_page
    from research_y.publication_review_gui import preview_candidate_review, record_candidate_review

    project, run_id, queries = _project(tmp_path)
    clock = Clock()
    for group in ("g-ecmo", "g-rv"):
        query_id, exact = queries[group, "pubmed"]
        _pubmed(project, query_id, exact, pmids=("111", "222"))
        query_id, exact = queries[group, "wos"]
        clock.sleep(60)
        _wos(project, query_id, exact, clock=clock, title="PRIVATE TITLE")
    project = open_project(project.root)
    partial = read_run_execution_board(project, run_id)
    assert partial["primary_source_enumerations_reconciled"]
    assert not partial["available_primary_metadata_acquired"]
    for group in ("g-ecmo", "g-rv"):
        _efetch(project, queries[group, "pubmed"][0], pmids=("111", "222"), book_pmid="222")

    with closing(sqlite3.connect(project.database_path)) as db:
        originals = dict(db.execute("SELECT source_record_id,retrieval_id FROM source_retrievals"))
    assert set(originals) == {"111", "222", "WOS:000000001"}
    for retrieval_id in originals.values():
        materialise_retrieval(project, retrieval_id, actor="Fixture")
    page = read_publication_page(project, run_id)
    assert len(page["rows"]) == 3
    left, right = originals["111"], originals["WOS:000000001"]
    pair = preview_candidate_review(project, run_id, left, right, run_revision=page["revision"])
    record_candidate_review(project, run_id, left, right, run_revision=page["revision"],
                            expected_revision=pair["revision"], decision="confirmed_match",
                            move_retrieval_id=right, actor="Fixture", evidence="Synthetic paired citation",
                            warnings_acknowledged=True, confirmed=True)
    reviewed = open_project(project.root)
    rows = read_publication_page(reviewed, run_id)["rows"]
    assert len(rows) == 2
    by_title = {row["title"]: row["publication_id"] for row in rows}
    board = read_run_execution_board(reviewed, run_id)
    assert board["available_primary_metadata_acquired"] and not board["verified_complete"]
    assert board["totals"]["source_records_by_provider"] == {"pubmed": 2, "wos": 1}
    export_id = str(uuid4())
    prepare_manifest_intent(reviewed, run_id, "phase-one.xlsx", export_id=export_id,
                            expected_revision=board["source_count_revision"], actor="Fixture", confirmed=True)
    stage_manifest_workbook(reviewed, export_id)
    result = publish_manifest_workbook(reviewed, export_id)
    assert result["audited_publication_success"] and not result["verified_complete"]
    with closing(load_workbook(reviewed.root / "exports" / result["output_name"], read_only=True)) as workbook:
        facts = dict(list(workbook["Evidence & Limits"].values)[3:])
        assert facts["Report status"] == "INCOMPLETE" and facts["Verified unique publications"] == "UNKNOWN"
        identities = list(workbook["Provisional Identities"].values)[3:]
        assert {identity[:2] for identity in identities} == {
            (by_title["PRIVATE TITLE"], 2), (by_title["Separate chapter"], 1)}
        links = list(workbook["Original Source Links"].values)[3:]
        assert {(link[0], link[3]) for link in links} == {
            (left, by_title["PRIVATE TITLE"]), (right, by_title["PRIVATE TITLE"]),
            (originals["222"], by_title["Separate chapter"])}
        members = list(workbook["Query Memberships"].values)[3:]
        assert len(members) == 6
        assert {member[:5] for member in members} == {
            (originals[source_id], run_id, query_id, group, source)
            for (group, source), (query_id, _) in queries.items()
            for source_id in (("111", "222") if source == "pubmed" else ("WOS:000000001",))}


def test_worker_command_is_read_only_and_refuses_cross_operation_parameters(tmp_path):
    p,rid,queries=_project(tmp_path)
    before=_digest(p)
    command=ApplicationCommand.for_project(p,"run_board",run_id=rid)
    response=execute_command(command)
    assert response["query_count"]==4 and response["no_network_requests"]
    assert _digest(p)==before
    for kw in (dict(acquisition_api_key="PRIVATE"),
               dict(pubmed_source_contact_email=EMAIL),
               dict(output_name="out.xlsx"),
               dict(export_id=str(uuid4())),
               dict(run_id=None)):
        with pytest.raises(ValueError):
            ApplicationCommand.for_project(p,"run_board",**(
                dict(run_id=rid)|kw))


def test_graphical_board_refresh_and_source_preview_are_offline(tmp_path):
    p,rid,queries=_project(tmp_path)
    flow=RealProjectFlow(
        selected_root=p.root,selected_parent=tmp_path,
        pubmed_profile=PubMedHostProfile(EMAIL,KEY),
        wos_profile=WoSHostProfile(KEY))
    flow.open_selected()
    flow.select_run(rid)
    try:
        before=_digest(p)
        state=flow.inspect_run_execution_board()
        board=state["run_execution_board"]
        assert board["query_count"]==4
        assert state["run_board_error"] is None
        assert _digest(p)==before
        qid,exact=queries["g-ecmo","pubmed"]
        chosen=flow.choose_run_execution_step(query_id=qid,revision=board["revision"])
        assert chosen["pubmed_source"] is not None
        assert chosen["pubmed_source"]["checkpoint"] is None
        assert _digest(p)==before
        wqid,wquery=queries["g-ecmo","wos"]
        offered=flow.choose_run_execution_step(query_id=wqid,revision=board["revision"])
        assert offered["wos_acquisition_offer"]["exact_query"]==wquery
        assert _digest(p)==before
        flow.dismiss_wos_acquisition()
        with pytest.raises(ProjectFlowError,match="run_board_invalid"):
            flow.choose_run_execution_step(query_id=str(uuid4()),revision=board["revision"])
    finally:
        flow.close()


def test_stale_run_board_cannot_authorize_old_source_step(tmp_path):
    p,rid,queries=_project(tmp_path)
    flow=RealProjectFlow(
        selected_root=p.root,selected_parent=tmp_path,
        pubmed_profile=PubMedHostProfile(EMAIL,KEY),
        wos_profile=WoSHostProfile(KEY))
    flow.open_selected()
    flow.select_run(rid)
    try:
        observed=flow.inspect_run_execution_board()["run_execution_board"]
        qid,exact=queries["g-ecmo","pubmed"]
        _pubmed(p,qid,exact,pmids=("111",))
        before=_digest(p)
        with pytest.raises(ProjectFlowError,match="run_board_stale"):
            flow.choose_run_execution_step(query_id=qid,
                                           revision=observed["revision"])
        assert flow.state()["run_execution_board"] is None
        assert flow.state()["run_board_error"]=="run_board_stale"
        assert _digest(p)==before
        fresh=flow.inspect_run_execution_board()["run_execution_board"]
        assert fresh["revision"]!=observed["revision"]
        assert _row(fresh,"g-ecmo","pubmed")["next_step"]=="preview_pubmed_metadata"
        flow.choose_run_execution_step(query_id=qid,revision=fresh["revision"])
        assert flow.state()["pubmed_metadata_offer"]["metadata_records_pending"]==1
    finally:
        flow.close()


def test_graphical_source_actions_never_automatically_dispatch_provider_requests():
    from desktop_source import project_ui_source
    source = project_ui_source()
    assert "name == 'run_board_refresh'" in source
    assert "name == 'run_board_select'" in source
    assert "data-testid=run-board-heading" in source
    assert "data-testid=run-board-source-row" in source
    assert "data-testid=run-board-next-step" in source
    assert 'ui.html(' not in source
    automated=source.split("@app.post('/_probe/start')")[1].split(
        "@app.post('/_probe/stop')")[0]
    assert "run_board" not in automated
