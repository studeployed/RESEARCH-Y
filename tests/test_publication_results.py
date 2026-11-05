"""Offline, disk-backed provisional results and trusted-command acceptance.

All publication evidence is synthetic. These tests never contact a provider,
run an LLM, permit licence-restricted abstract export or certify deduplication.
"""
from __future__ import annotations

from contextlib import closing
from hashlib import sha256
import sqlite3
from uuid import uuid4

import pytest

from research_y import publication_identity as identity
from research_y.application_commands import (
    ApplicationCommand, ApplicationCommandError, execute_command)
from research_y.projects import create_project, open_project
from research_y.publication_run_materialisation import (
    preview_run_materialisation, materialise_run_batch)
from research_y.publication_results import (
    PAGE_SIZE, PublicationViewError, read_publication_page, read_publication_detail)


def uid():
    return str(uuid4())


@pytest.fixture
def fixture(tmp_path):
    project = create_project(tmp_path, "Synthetic bibliographic browse")
    run, second_run, strategy = uid(), uid(), uid()
    queries = {}
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("INSERT INTO strategy_versions VALUES(?,?,?,?)",
                   (strategy, 1, project.created_at_utc, "{}"))
        for i, group in enumerate(("g1", "g2")):
            db.execute("INSERT INTO strategy_groups VALUES(?,?,?,?)",
                       (strategy, group, "Clinical " + group, i))
        for run_id in (run, second_run):
            db.execute("INSERT INTO search_runs VALUES(?,?,?,?,?)",
                       (run_id, strategy, project.created_at_utc, "incomplete", None))
            for group in ("g1", "g2"):
                for source in ("pubmed", "wos"):
                    qid = uid()
                    db.execute(
                        "INSERT INTO source_queries(query_id,run_id,strategy_version_id,"
                        "group_id,source_name,exact_query) VALUES(?,?,?,?,?,?)",
                        (qid, run_id, strategy, group, source,
                         '"ventricle"[All Fields]' if source=="pubmed" else 'TS=("ventricle")'),
                    )
                    queries[run_id,group,source] = qid
    return project, run, second_run, queries


def insert(f, *, source="pubmed", number=1, title="Original title",
           groups=("g1",), run=None, abstract="SECRET ABSTRACT MUST NOT BE RETURNED"):
    project, primary, _, queries = f
    run_id = primary if run is None else run
    name = str(number) if source == "pubmed" else "WOS:" + str(number)
    record = (
        {"pmid":name, "title":title, "identifiers":{"doi":["10.1234/same-container"]},
         "abstract_sections":[{"text":abstract}], "abstract_status":"present",
         "publication_types":["Journal Article"], "journal":{"title":"Synthetic journal"}}
        if source == "pubmed" else
        {"uid":name, "title":title, "identifiers":{"doi":"10.1234/same-container"},
         "types":["Article"], "source":{"sourceTitle":"Synthetic journal"}}
    )
    payload = ({"source":"NCBI PubMed EFetch XML","record":record,
                "rights_review_required_for_abstract_redistribution":True}
               if source=="pubmed" else
               {"provider":"wos_starter","database":"WOS","record":record,
                "abstract_status":"not_returned_by_source",
                "rights_status":"licence_review_required"})
    retrieval_id = uid()
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("INSERT INTO source_retrievals VALUES(?,?,?,?,?,?)",
                   (retrieval_id, run_id, source, name, project.created_at_utc,
                    identity._json(payload)))
        for group in groups:
            db.execute("INSERT INTO query_retrievals VALUES(?,?,?,?)",
                       (queries[run_id,group,source],retrieval_id,run_id,source))
    return retrieval_id


def materialise(f):
    project, run, _, _ = f
    plan=preview_run_materialisation(project,run)
    if plan["batch_count"]:
        materialise_run_batch(project,run,expected_revision=plan["revision"],
                              confirmed=True,actor="Fixture")


def audit(project):
    with closing(sqlite3.connect(project.database_path)) as db:
        return db.execute(
            "SELECT event_id,event_type,details_json FROM audit_events ORDER BY event_id"
        ).fetchall()


def test_empty_results_identify_unmaterialised_source_records(fixture):
    project,run,_,_=fixture
    insert(fixture)
    before = sha256(project.database_path.read_bytes()).hexdigest()
    view=read_publication_page(project,run)
    assert view["rows"] == []
    assert view["unmaterialised_source_records"] == 1
    assert view["retrieved_source_records"] == 1
    assert view["provisional_publication_identities"] == 0
    assert view["global_unique_publications"] is None
    assert not view["deduplication_complete"] and not view["verified_complete"]
    assert sha256(project.database_path.read_bytes()).hexdigest() == before


def test_same_title_and_supplement_doi_remain_two_independent_hypotheses(fixture):
    project,run,_,_=fixture
    insert(fixture, source="pubmed",number=123,groups=("g1","g2"),title="Same DOI")
    insert(fixture, source="wos",number=456,groups=("g1","g2"),title="Same DOI")
    materialise(fixture)
    first=read_publication_page(project,run)
    assert len(first["rows"]) == 2
    assert first["provisional_publication_identities"] == 2
    assert {r["title"] for r in first["rows"]} == {"Same DOI"}
    assert all(r["identity_status"]=="provisional_review_required"
               and r["review_required_links"]==1 for r in first["rows"])
    assert all(len(r["group_memberships"])==2 for r in first["rows"])
    assert first["global_unique_publications"] is None


def test_manual_link_preserves_both_originals_and_title_conflict(fixture):
    project,run,_,_=fixture
    left=insert(fixture,number=123,title="Source title A")
    right=insert(fixture,source="wos",number=456,title="Source title B")
    materialise(fixture)
    a,b=identity.read_publication(project, next(
        x["publication_id"] for x in read_publication_page(project,run)["rows"]
        if x["source_names"]==["pubmed"])), identity.read_publication(project, next(
        x["publication_id"] for x in read_publication_page(project,run)["rows"]
        if x["source_names"]==["wos"]))
    identity.associate_retrieval(project,left,b.publication_id,
         expected_source_revision=a.revision,expected_target_revision=b.revision,
         actor="Researcher",evidence="Explicit fixture confirmation",
         same_publication_confirmed=True)
    page=read_publication_page(project,run)
    assert len(page["rows"])==1
    row=page["rows"][0]
    assert row["title"] is None
    assert row["title_status"]=="conflicting_original_titles_unresolved"
    assert row["original_source_records_in_run"]==2
    assert row["confirmed_links"]==1 and row["review_required_links"]==1
    detail=read_publication_detail(project,run,row["publication_id"],
                                   expected_revision=page["revision"])
    assert len(detail["source_retrievals"])==2
    titles={f["value"] for r in detail["source_retrievals"] for f in r["fields"]
            if f["field"]=="title"}
    assert titles=={"Source title A","Source title B"}
    assert all(r["source_record_id"] for r in detail["source_retrievals"])
    assert detail["global_unique_publications"] is None
    assert not detail["abstract_text_displayed"]


def test_local_detail_exposes_metadata_status_rights_but_not_abstract(fixture):
    project,run,_,_=fixture
    insert(fixture,abstract="SENSITIVE ABSTRACT LOCAL ONLY")
    materialise(fixture)
    page=read_publication_page(project,run)
    detail=read_publication_detail(project,run,page["rows"][0]["publication_id"],
                                   expected_revision=page["revision"])
    source=detail["source_retrievals"][0]
    assert source["abstract_status"]=="present"
    assert source["rights_status"]=="abstract_redistribution_review_required"
    assert source["fields"][0]["field"]=="title"
    assert source["memberships"][0]["group_label"]=="Clinical g1"
    assert "SENSITIVE ABSTRACT LOCAL ONLY" not in str(detail)
    assert not detail["redistribution_permission_established"]
    assert detail["suppressed_chosen_fields"] == []
    assert detail["no_network_requests"]


@pytest.mark.parametrize("field", ["abstract", "title"])
def test_arbitrary_chosen_source_path_cannot_leak_abstract_as_citation(fixture, field):
    project, run, _, _ = fixture
    original = insert(fixture, title="Safe citation title",
                      abstract="STRICTLY PRIVATE ABSTRACT CHOICE")
    materialise(fixture)
    before = read_publication_page(project, run)
    publication_id = before["rows"][0]["publication_id"]
    from research_y.publication_fields import select_source_field
    snapshot = identity.read_publication(project, publication_id)
    select_source_field(project, publication_id, field, retrieval_id=original,
        path=("record", "abstract_sections", 0, "text"),
        expected_revision=snapshot.revision, actor="Fixture",
        reason="Demonstrate that a field label cannot redefine a source path")
    page = read_publication_page(project, run)
    detail = read_publication_detail(project, run, publication_id,
                                     expected_revision=page["revision"])
    assert "STRICTLY PRIVATE ABSTRACT CHOICE" not in str(page)
    assert "STRICTLY PRIVATE ABSTRACT CHOICE" not in str(detail)
    assert detail["chosen_source_fields"] == []
    assert detail["suppressed_chosen_fields"] == [
        dict(field=field, reason="not_permitted_citation_source_path")]
    if field == "title":
        assert page["rows"][0]["title"] is None
        assert page["rows"][0]["title_status"] == "chosen_title_not_citation_path"


@pytest.mark.parametrize("source", ["pubmed", "wos"])
def test_untrusted_status_strings_cannot_disclose_text_through_detail(fixture, source):
    project, run, _, _ = fixture
    rid = insert(fixture, source=source)
    with closing(sqlite3.connect(project.database_path)) as db, db:
        metadata = identity._object(db.execute(
            "SELECT original_metadata_json FROM source_retrievals WHERE retrieval_id=?",
            (rid,)).fetchone()[0])
        metadata["rights_status"] = "PRIVATE RIGHTS FIELD DATA"
        metadata["record"]["abstract_status"] = "PRIVATE ABSTRACT AS STATUS"
        db.execute("UPDATE source_retrievals SET original_metadata_json=? "
                   "WHERE retrieval_id=?", (identity._json(metadata), rid))
    materialise(fixture)
    page = read_publication_page(project, run)
    detail = read_publication_detail(project, run, page["rows"][0]["publication_id"],
                                     expected_revision=page["revision"])
    assert "PRIVATE RIGHTS FIELD DATA" not in str(detail)
    assert "PRIVATE ABSTRACT AS STATUS" not in str(detail)
    assert detail["source_retrievals"][0]["abstract_status"] == "not_recorded_or_malformed"
    expected = ("abstract_redistribution_review_required" if source == "pubmed"
                else "rights_not_verified")
    assert detail["source_retrievals"][0]["rights_status"] == expected


def test_keyset_paging_20_then_three_without_hidden_truncation(fixture):
    project,run,_,_=fixture
    for n in range(1,24):
        insert(fixture,number=n,title=f"Research item {n}")
    materialise(fixture)
    first=read_publication_page(project,run)
    assert PAGE_SIZE==20
    assert len(first["rows"])==20 and first["has_more"]
    assert first["next_after_publication_id"] is not None
    second=read_publication_page(open_project(project.root),run,
        after_publication_id=first["next_after_publication_id"],
        expected_revision=first["revision"])
    assert len(second["rows"])==3 and not second["has_more"]
    assert second["next_after_publication_id"] is None
    allids={r["publication_id"] for r in first["rows"]+second["rows"]}
    assert len(allids)==23
    assert first["provisional_publication_identities"]==23
    assert second["revision"]==first["revision"]


def test_stale_list_and_detail_refuse_after_source_status_change(fixture):
    project,run,_,queries=fixture
    insert(fixture)
    materialise(fixture)
    page=read_publication_page(project,run)
    with closing(sqlite3.connect(project.database_path)) as db,db:
        db.execute("UPDATE source_queries SET status='failed' WHERE query_id=?",
                   (queries[run,"g1","pubmed"],))
    with pytest.raises(PublicationViewError) as exc:
        read_publication_detail(project,run,page["rows"][0]["publication_id"],
                                expected_revision=page["revision"])
    assert exc.value.code=="publication_view_stale"
    with pytest.raises(PublicationViewError):
        read_publication_page(project,run,expected_revision=page["revision"])


def test_cross_run_source_is_not_counted_in_selected_run(fixture):
    project,run,other,_=fixture
    a=insert(fixture,number=111)
    b=insert(fixture,number=222,run=other)
    identity.materialise_retrieval(project,a,actor="Fixture")
    later=identity.materialise_retrieval(project,b,actor="Fixture")
    from research_y.publication_candidates import read_candidate, decide_candidate
    candidate=read_candidate(project,a,b)
    decide_candidate(project,a,b,expected_revision=candidate.revision,
                     decision="confirmed_match",actor="Researcher",
                     evidence="Explicit same paper comparison",
                     acknowledged_warnings=candidate.warnings,
                     decision_confirmed=True,move_retrieval_id=a)
    page=read_publication_page(project,run)
    assert len(page["rows"])==1
    assert page["rows"][0]["additional_source_records_in_other_runs"]==1
    assert page["rows"][0]["original_source_records_in_run"]==1
    detail=read_publication_detail(project,run,page["rows"][0]["publication_id"],
                                   expected_revision=page["revision"])
    assert len(detail["source_retrievals"])==2
    assert sum(r["included_in_selected_run"] for r in detail["source_retrievals"])==1
    assert page["provisional_publication_identities"]==1


def test_untrusted_oversize_title_is_not_silently_truncated_or_html_rendered(fixture):
    project,run,_,_=fixture
    title="<script>alert('x')</script>"
    insert(fixture,title=title)
    materialise(fixture)
    page=read_publication_page(project,run)
    assert page["rows"][0]["title"]==title
    assert page["rows"][0]["title_status"]=="same_original_title_in_selected_run"


@pytest.mark.parametrize("bad",["fake", "WOS:99", True, 123])
def test_non_uuid_cursor_or_record_id_fails_closed(fixture,bad):
    project,run,_,_=fixture
    with pytest.raises(PublicationViewError):
        read_publication_page(project,run,after_publication_id=bad)
    with pytest.raises(PublicationViewError):
        read_publication_detail(project,run,bad,expected_revision="a"*64)


def test_unknown_publication_and_other_run_not_displayed(fixture):
    project,run,other,_=fixture
    rid=insert(fixture,run=other)
    identity.materialise_retrieval(project,rid,actor="Fixture")
    page=read_publication_page(project,run)
    assert page["rows"]==[]
    with pytest.raises(PublicationViewError) as exc:
        read_publication_detail(project,run,
             identity.materialise_retrieval(project,rid,actor="Fixture").publication_id,
             expected_revision=page["revision"])
    assert exc.value.code=="publication_view_not_in_run"


def test_command_routing_requires_exact_run_and_does_not_accept_forged_privileges(fixture):
    project,run,_,_=fixture
    insert(fixture)
    preview=execute_command(ApplicationCommand.for_project(
        project,"publication_materialisation_preview",run_id=run))
    assert preview["batch_count"]==1
    with pytest.raises(ApplicationCommandError):
        ApplicationCommand.for_project(project,"publication_materialisation_confirm",
            run_id=run,publication_view_revision=preview["revision"],
            publication_actor="Researcher",publication_confirmed=False)
    with pytest.raises(ApplicationCommandError):
        ApplicationCommand.for_project(project,"publication_page",
             run_id=run,publication_actor="other",publication_view_cursor=None)
    batch=execute_command(ApplicationCommand.for_project(
        project,"publication_materialisation_confirm",run_id=run,
        publication_view_revision=preview["revision"],publication_actor="Researcher",
        publication_confirmed=True))
    assert batch["materialised_in_batch"]==1
    with pytest.raises(ApplicationCommandError):
        execute_command(ApplicationCommand.for_project(
            project,"publication_materialisation_confirm",run_id=run,
            publication_view_revision=preview["revision"],publication_actor="Researcher",
            publication_confirmed=True))
    page=execute_command(ApplicationCommand.for_project(
        project,"publication_page",run_id=run))
    assert len(page["rows"])==1
    detail=execute_command(ApplicationCommand.for_project(
        project,"publication_detail",run_id=run,
        publication_view_id=page["rows"][0]["publication_id"],
        publication_view_revision=page["revision"]))
    assert len(detail["source_retrievals"])==1
    with pytest.raises(ApplicationCommandError):
        ApplicationCommand.for_project(project,"publication_detail",run_id=run,
            publication_view_id=page["rows"][0]["publication_id"],
            publication_view_revision=page["revision"],
            pilot_api_key="FORGED")


def test_trusted_host_flow_requires_preview_and_reconciles_committed_batch(fixture):
    project, run, _, _ = fixture
    insert(fixture, number=123)
    from tools.gui_feasibility.real_project_flow import RealProjectFlow, ProjectFlowError
    flow = RealProjectFlow(selected_root=project.root, selected_parent=project.root.parent)
    flow.project = project
    flow.selected_run_id = run
    flow.snapshot = {"runs": [], "report": None, "exports": []}

    def original_service(name, **kwargs):
        if name == "inspect":
            return {"snapshot":{
                "selected_run_id": run, "report":{"status":"incomplete"},
                "runs": [], "exports": []}}
        return execute_command(ApplicationCommand.for_project(project, name, **kwargs))

    flow._operation = original_service
    try:
        with pytest.raises(ProjectFlowError, match="publication_materialisation_no_work"):
            flow.confirm_publication_materialisation("Researcher")
        preview = flow.offer_publication_materialisation()
        offer = preview["publication_materialisation_offer"]
        assert offer["batch_count"] == 1
        committed = flow.confirm_publication_materialisation("Researcher")
        assert committed["publication_materialisation_last_outcome"]["materialised_in_batch"] == 1
        assert committed["publication_materialisation_offer"] is None
        assert committed["publication_page"] is None
        assert committed["report"]["status"] == "incomplete"
        page_state = flow.inspect_publications()
        page = page_state["publication_page"]
        assert len(page["rows"]) == 1 and not page["verified_complete"]
        record = page["rows"][0]
        opened = flow.inspect_publication_detail(
            publication_id=record["publication_id"], revision=page["revision"])
        assert opened["publication_detail"]["publication"]["publication_id"] == record["publication_id"]
        with pytest.raises(ProjectFlowError, match="publication_view_stale"):
            flow.inspect_publication_detail(publication_id=uid(), revision=page["revision"])
        assert flow.state()["publication_materialisation_last_outcome"] is not None
    finally:
        flow.close()


def test_read_and_navigation_are_unchanged_on_disk(fixture):
    project,run,_,_=fixture
    insert(fixture)
    materialise(fixture)
    before=sha256(project.database_path.read_bytes()).hexdigest()
    page=read_publication_page(project,run)
    read_publication_detail(project,run,page["rows"][0]["publication_id"],
                            expected_revision=page["revision"])
    assert before==sha256(project.database_path.read_bytes()).hexdigest()
