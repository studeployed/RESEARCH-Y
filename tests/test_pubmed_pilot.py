"""Offline integration tests of one-shot, audited PubMed count-only pilots.

Synthetic ESearch responses only. No live National Center for Biotechnology
Information requests, external keys, retrievals or verified search claims.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
import json
import sqlite3
from threading import Event
from urllib.error import URLError
from urllib.parse import parse_qs
from uuid import uuid4

import pytest

from research_y.projects import create_project, open_project
from research_y.preflight_review import read_preflight
from research_y.pubmed_probe import PubMedESearchProbeClient
from research_y.pubmed_pilot import (
    PubMedPilotError, read_pubmed_pilot, probe_pubmed_count_once,
    REQUEST_EVENT, OUTCOME_EVENT,
)
from research_y.storage import ApprovedTerm, StrategyGroup
from research_y.strategy_admission import commit_approved_strategy


def _fixture(tmp_path):
    project = create_project(tmp_path, "Pilot fixtures")
    admission = commit_approved_strategy(
        project, request_id=str(uuid4()), theme="ECMO", approved_by="Researcher",
        approval_confirmed=True,
        groups=(StrategyGroup("g1", "Extracorporeal support", (
            ApprovedTerm("ECMO", "researcher", True),
            ApprovedTerm("extracorporeal membrane oxygenation",
                         "researcher", True),
        )),),
    )
    preflight = read_preflight(project, admission.run_id)
    source = next(s for s in preflight["sources"] if s["source_name"] == "pubmed")
    query = source["queries"][0]
    return project, admission.run_id, preflight["plan_sha256"], query


def _client(*, expected_query=None, accepted=None, count=17,
            warnings=(), api_key=None, block=None, trace=None, fail=None):
    def transport(request, timeout):
        if trace is not None:
            trace.append(1)
        assert request.full_url.startswith("https://eutils.ncbi.nlm.nih.gov/")
        assert request.get_method() == "POST"
        values = parse_qs(request.data.decode("utf-8"))
        assert values["db"] == ["pubmed"]
        assert values["retmax"] == ["0"]
        assert values["retmode"] == ["json"]
        assert "retstart" not in values
        query = values["term"][0]
        if expected_query is not None:
            assert query == expected_query
        if block is not None:
            ready, release = block
            ready.set()
            assert release.wait(15)
        if fail is not None:
            if fail == "abrupt":
                raise KeyboardInterrupt
            if fail == "network":
                raise URLError("synthetic unreachable")
        response = dict(esearchresult=dict(
            count=str(count), retstart="0", retmax="0", idlist=[],
            querytranslation=query if accepted is None else accepted,
            warninglist=dict(outputmessages=list(warnings)),
            errorlist=dict(phrasesnotfound=[]),
        ))
        return json.dumps(response).encode("utf-8")
    return PubMedESearchProbeClient(email="synthetic@example.org",
                                   api_key=api_key, transport=transport)


def _call(project, run_id, plan_sha, query, client, *, pilot_id=None, **changes):
    args=dict(pilot_id=pilot_id or str(uuid4()), run_id=run_id,
              query_id=query["query_id"], expected_plan_sha256=plan_sha,
              confirmed=True, client=client)
    args.update(changes)
    return probe_pubmed_count_once(project, **args)


def _events(project, pilot_id):
    with closing(sqlite3.connect(project.database_path)) as db:
        return [(k,json.loads(data)) for k,data in db.execute(
            "SELECT event_type,details_json FROM audit_events "
            "WHERE event_type IN (?,?) ORDER BY event_id",
            (REQUEST_EVENT, OUTCOME_EVENT))
            if json.loads(data).get("pilot_id") == pilot_id]


def _counts(project, run_id):
    with closing(sqlite3.connect(project.database_path)) as db:
        return db.execute(
            "SELECT source_name,reported_matches,status FROM source_queries "
            "WHERE run_id=? ORDER BY source_name", (run_id,)).fetchall()


def test_count_only_pilot_is_audited_without_claiming_retrieval_or_changing_source_counts(tmp_path):
    project, run_id, plan_sha, query = _fixture(tmp_path)
    attempts=[]
    client=_client(expected_query=query["exact_query"],count=17003,trace=attempts)
    pilot_id=str(uuid4())
    before=_counts(project,run_id)
    result=_call(project,run_id,plan_sha,query,client,pilot_id=pilot_id)
    assert result["status"]=="count_reported_not_retrieved"
    assert result["reported_matches"]==17003
    assert result["translation_matches_submitted"] is True
    assert result["accepted_translation"]==query["exact_query"]
    assert result["checked_at_utc"]
    assert result["count_only"] is True
    assert result["retrieval_verified"] is False
    assert result["source_retrieval_verified"] is False
    assert result["execution_authorized"] is False
    assert result["search_completed"] is False
    assert result["automatically_retryable"] is False
    assert attempts==[1]
    assert _counts(project,run_id)==before
    assert all(matches is None and state=="pending" for _,matches,state in before)
    assert read_preflight(project,run_id)["provider_counts"] is None
    assert [kind for kind,_ in _events(project,pilot_id)]==[
        REQUEST_EVENT, OUTCOME_EVENT]
    recorded=read_pubmed_pilot(open_project(project.root),pilot_id)
    assert recorded==result or all(recorded[k]==v for k,v in result.items()
                                  if k!="completed_at_utc")
    replay=_call(project,run_id,plan_sha,query,client,pilot_id=pilot_id)
    assert replay==recorded
    assert attempts==[1]
    assert len(_events(project,pilot_id))==2


def test_translation_change_is_a_review_required_count_not_verified_search(tmp_path):
    project,run_id,sha,q=_fixture(tmp_path)
    client=_client(accepted='"ECMO"[Title/Abstract] AND "other"[All Fields]',
                   warnings=("Unrecognised phrase",),count=901)
    result=_call(project,run_id,sha,q,client)
    assert result["status"]=="translation_review_required"
    assert result["reported_matches"]==901
    assert result["translation_matches_submitted"] is False
    assert result["review_reasons"]
    assert result["warnings"]==["Unrecognised phrase"]
    assert result["search_completed"] is False


def test_true_zero_count_is_still_provisional_not_missing_or_completed(tmp_path):
    project,rid,sha,q=_fixture(tmp_path)
    result=_call(project,rid,sha,q,_client(count=0))
    assert result["reported_matches"]==0
    assert result["status"]=="count_reported_not_retrieved"
    assert _counts(project,rid)[0][1] is None


def test_provider_failure_is_audited_as_failure_not_zero(tmp_path):
    project,rid,sha,q=_fixture(tmp_path)
    pilot_id=str(uuid4())
    result=_call(project,rid,sha,q,_client(fail="network"),pilot_id=pilot_id)
    assert result["status"]=="probe_failed"
    assert result["reported_matches"] is None
    assert result["error_code"]=="provider_unavailable"
    assert result["accepted_translation"] is None
    assert len(_events(project,pilot_id))==2
    assert all(matches is None for _,matches,_ in _counts(project,rid))


def test_indeterminate_crash_never_automatically_repeats_network_request(tmp_path):
    project,rid,sha,q=_fixture(tmp_path)
    pilot_id=str(uuid4())
    with pytest.raises(KeyboardInterrupt):
        _call(project,rid,sha,q,_client(fail="abrupt"),pilot_id=pilot_id)
    saved=read_pubmed_pilot(project,pilot_id)
    assert saved["status"]=="requested_indeterminate"
    assert saved["reported_matches"] is None
    trace=[]
    retry=_call(project,rid,sha,q,_client(trace=trace),pilot_id=pilot_id)
    assert retry==saved and trace==[]
    assert len(_events(project,pilot_id))==1
    # A fresh explicit request ID is permitted but must be a separate
    # auditable, confirmed attempt; no covert retry of the ambiguous one.
    next_result=_call(project,rid,sha,q,_client(trace=trace))
    assert next_result["reported_matches"]==17 and trace==[1]


@pytest.mark.parametrize('change,code', [
    ({"confirmed":False},"pilot_confirmation_required"),
    ({"confirmed":1},"pilot_confirmation_required"),
    ({"pilot_id":"not-uuid"},"invalid_identifier"),
    ({"query_id":"not-uuid"},"invalid_identifier"),
    ({"expected_plan_sha256":"a"*64},"pilot_plan_invalid"),
])
def test_invalid_attempt_never_calls_provider_or_writes_receipt(tmp_path, change, code):
    project,rid,sha,q=_fixture(tmp_path)
    trace=[]
    with pytest.raises(PubMedPilotError, match="^"+code+"$"):
        _call(project,rid,sha,q,_client(trace=trace),**change)
    assert trace==[]
    with closing(sqlite3.connect(project.database_path)) as db:
        assert db.execute("SELECT COUNT(*) FROM audit_events WHERE event_type IN (?,?)",
                          (REQUEST_EVENT,OUTCOME_EVENT)).fetchone()[0]==0


def test_unsupported_compiler_plan_or_wrong_query_cannot_be_piloted(tmp_path):
    project,rid,sha,q=_fixture(tmp_path)
    with closing(sqlite3.connect(project.database_path)) as db,db:
        db.execute("UPDATE source_queries SET exact_query=? WHERE query_id=?",
                   ('"ECMO"[Title/Abstract]',q["query_id"]))
    trace=[]
    with pytest.raises(PubMedPilotError,match="pilot_plan_invalid"):
        _call(project,rid,sha,q,_client(trace=trace))
    assert trace==[]
    assert not _events(project,str(uuid4()))


def test_late_run_mutation_marks_pilot_stale_and_never_commits_its_count(tmp_path):
    project,rid,sha,q=_fixture(tmp_path)
    class ChangedRun(Exception):
        pass
    def mutate(request,timeout):
        with closing(sqlite3.connect(project.database_path)) as db,db:
            db.execute("UPDATE search_runs SET status='paused' WHERE run_id=?", (rid,))
        values=parse_qs(request.data.decode("utf-8"))
        assert values["retmax"]==["0"]
        return json.dumps({"esearchresult":{
            "count":"5000","retstart":"0","retmax":"0","idlist":[],
            "querytranslation":values["term"][0]}}).encode()
    client=PubMedESearchProbeClient(email="synthetic@example.org",transport=mutate)
    result=_call(project,rid,sha,q,client)
    assert result["status"]=="stale_plan"
    assert result["reported_matches"] is None
    assert result["source_retrieval_verified"] is False
    assert read_pubmed_pilot(project,result["pilot_id"])["status"]=="stale_plan"


def test_same_uuid_different_plan_identity_is_a_conflict_without_a_second_query(tmp_path):
    project,rid,sha,q=_fixture(tmp_path)
    pilot_id=str(uuid4())
    trace=[]
    client=_client(trace=trace)
    _call(project,rid,sha,q,client,pilot_id=pilot_id)
    with pytest.raises(PubMedPilotError,match="^pilot_conflict$"):
        _call(project,rid,sha,q,client,pilot_id=pilot_id,
              query_id=str(uuid4()))
    assert len(trace)==1
    assert len(_events(project,pilot_id))==2


def test_untrusted_provider_echoing_api_secret_is_not_recorded(tmp_path):
    project,rid,sha,q=_fixture(tmp_path)
    key="private-test-credential-123456"
    pilot_id=str(uuid4())
    result=_call(project,rid,sha,q,
                 _client(api_key=key,accepted='"ECMO"[All Fields] '+key),
                 pilot_id=pilot_id)
    assert result["status"]=="probe_failed"
    assert result["reported_matches"] is None
    serialized=json.dumps(_events(project,pilot_id))
    assert key not in serialized


def test_audit_request_failure_rolls_back_without_querying_network(tmp_path,monkeypatch):
    import research_y.pubmed_pilot as module
    project,rid,sha,q=_fixture(tmp_path)
    before=read_preflight(project,rid)["plan_sha256"]
    original=module._audit
    def fail(*args,**kwargs):
        if kwargs["kind"]==REQUEST_EVENT:
            raise OSError("simulated disk fault")
        return original(*args,**kwargs)
    monkeypatch.setattr(module,"_audit",fail)
    trace=[]
    with pytest.raises(PubMedPilotError,match="^pilot_storage_failed$"):
        _call(project,rid,sha,q,_client(trace=trace))
    assert trace==[] and read_preflight(project,rid)["plan_sha256"]==before
    with closing(sqlite3.connect(project.database_path)) as db:
        assert db.execute("SELECT COUNT(*) FROM audit_events WHERE event_type=?",
                          (REQUEST_EVENT,)).fetchone()[0]==0


def test_outcome_audit_failure_leaves_unresolved_id_without_second_call(tmp_path,monkeypatch):
    import research_y.pubmed_pilot as module
    project,rid,sha,q=_fixture(tmp_path)
    original=module._audit
    pilot_id=str(uuid4())
    def fail(*args,**kwargs):
        if kwargs["kind"]==OUTCOME_EVENT:
            raise OSError("no space for receipt")
        return original(*args,**kwargs)
    monkeypatch.setattr(module,"_audit",fail)
    trace=[]
    with pytest.raises(PubMedPilotError,match="^pilot_storage_failed$"):
        _call(project,rid,sha,q,_client(trace=trace),pilot_id=pilot_id)
    assert trace==[1]
    assert read_pubmed_pilot(project,pilot_id)["status"]=="requested_indeterminate"
    assert _call(project,rid,sha,q,_client(trace=trace),pilot_id=pilot_id)["status"]==(
        "requested_indeterminate")
    assert trace==[1]


def test_concurrent_same_request_can_only_make_one_provider_call(tmp_path):
    project,rid,sha,q=_fixture(tmp_path)
    entered,release=Event(),Event()
    trace=[]
    client=_client(trace=trace,block=(entered,release))
    pilot_id=str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(_call,project,rid,sha,q,client,pilot_id=pilot_id)
        assert entered.wait(10)
        second=pool.submit(_call,project,rid,sha,q,client,pilot_id=pilot_id)
        outcome=second.result(timeout=15)
        assert outcome["status"]=="requested_indeterminate"
        release.set()
        complete=first.result(timeout=15)
    assert complete["status"]=="count_reported_not_retrieved"
    assert trace==[1] and len(_events(project,pilot_id))==2


def test_historical_pilot_remains_readable_after_run_status_changes(tmp_path):
    project,rid,sha,q=_fixture(tmp_path)
    result=_call(project,rid,sha,q,_client())
    with closing(sqlite3.connect(project.database_path)) as db,db:
        db.execute("UPDATE search_runs SET status='paused' WHERE run_id=?", (rid,))
    saved=read_pubmed_pilot(open_project(project.root),result["pilot_id"])
    assert saved["reported_matches"]==17
    assert saved["search_completed"] is False
