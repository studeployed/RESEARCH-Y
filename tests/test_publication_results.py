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
    PAGE_SIZE, PublicationViewError, read_publication_page, read_publication_detail,
    read_publication_page_detail)


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
    with pytest.raises(PublicationViewError) as missing_revision:
        read_publication_page(project, run,
            after_publication_id=first["next_after_publication_id"])
    assert missing_revision.value.code == "publication_view_invalid"
    with pytest.raises(ApplicationCommandError):
        ApplicationCommand.for_project(project, "publication_page",
            run_id=run, publication_view_cursor=first["next_after_publication_id"])
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


def test_single_snapshot_page_detail_matches_original_paths_without_second_count(
        fixture, monkeypatch):
    """Exactly one FULL original projection validates the shown page and detail."""
    from research_y import result_counts
    project, run, _, _ = fixture
    for n in range(1, 24):
        insert(fixture, number=n, title=f"Synthetic research item {n}")
    materialise(fixture)
    first = read_publication_page(project, run)
    second = read_publication_page(project, run,
        after_publication_id=first["next_after_publication_id"],
        expected_revision=first["revision"])
    target = second["rows"][0]["publication_id"]
    ordinary = read_publication_detail(project, run, target,
        expected_revision=second["revision"])
    before_audit = audit(project)
    before_bytes = sha256(project.database_path.read_bytes()).hexdigest()
    original_projection = result_counts._snapshot
    called = []
    def counted(*args, **kwargs):
        called.append("full-original-validation")
        return original_projection(*args, **kwargs)
    monkeypatch.setattr(result_counts, "_snapshot", counted)
    combined = read_publication_page_detail(
        open_project(project.root), run, target,
        after_publication_id=first["next_after_publication_id"],
        expected_revision=first["revision"])
    assert called == ["full-original-validation"]
    assert combined["method"] == "provisional-publication-page-detail/1"
    assert combined["page"] == second
    assert combined["detail"] == ordinary
    assert combined["revision"] == first["revision"]
    assert combined["global_unique_publications"] is None
    assert combined["deduplication_complete"] is False
    assert combined["verified_complete"] is False
    assert combined["source_retrieval_verified"] is False
    assert combined["no_network_requests"] is True
    assert audit(project) == before_audit
    assert sha256(project.database_path.read_bytes()).hexdigest() == before_bytes


def test_single_snapshot_detail_rejects_row_not_on_canonical_page(fixture):
    project, run, _, _ = fixture
    for n in range(1, 24):
        insert(fixture, number=n)
    materialise(fixture)
    first = read_publication_page(project, run)
    second = read_publication_page(project, run,
        after_publication_id=first["next_after_publication_id"],
        expected_revision=first["revision"])
    target = second["rows"][0]["publication_id"]
    with pytest.raises(PublicationViewError, match="publication_view_stale"):
        read_publication_page_detail(
            project, run, target,
            after_publication_id=None, expected_revision=first["revision"])
    assert read_publication_page_detail(
        project, run, target,
        after_publication_id=first["next_after_publication_id"],
        expected_revision=first["revision"])["detail"]["publication"]["publication_id"] == target


def test_single_snapshot_detail_rejects_stale_original_query_and_leaks_no_abstract(
        fixture):
    project, run, _, queries = fixture
    insert(fixture, abstract="SYNTHETIC HIDDEN ABSTRACT")
    materialise(fixture)
    first = read_publication_page(project, run)
    publication_id = first["rows"][0]["publication_id"]
    combined = read_publication_page_detail(
        project, run, publication_id,
        after_publication_id=None, expected_revision=first["revision"])
    assert "SYNTHETIC HIDDEN ABSTRACT" not in identity._json(combined)
    assert combined["detail"]["abstract_text_displayed"] is False
    assert combined["detail"]["redistribution_permission_established"] is False
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute("UPDATE source_queries SET status='failed' WHERE query_id=?",
                   (queries[run, "g1", "pubmed"],))
    with pytest.raises(PublicationViewError, match="publication_view_stale"):
        read_publication_page_detail(project, run, publication_id,
            after_publication_id=None, expected_revision=first["revision"])


def test_single_snapshot_command_rejects_unapproved_actor_and_bogus_cursor(fixture):
    project, run, _, _ = fixture
    insert(fixture)
    materialise(fixture)
    page = read_publication_page(project, run)
    pub_id = page["rows"][0]["publication_id"]
    command = ApplicationCommand.for_project(
        project, "publication_page_detail", run_id=run,
        publication_view_id=pub_id,
        publication_view_revision=page["revision"])
    combined = execute_command(command)
    assert combined["page"] == page
    assert combined["detail"]["publication"]["publication_id"] == pub_id
    for extra in (
        dict(publication_actor="Unapproved"),
        dict(publication_confirmed=True),
        dict(publication_view_cursor="not-uuid"),
        dict(pilot_api_key="SYNTHETIC FORGED KEY"),
        dict(output_name="forged.xlsx"),
    ):
        with pytest.raises(ApplicationCommandError, match="invalid_command"):
            ApplicationCommand.for_project(
                project, "publication_page_detail", run_id=run,
                publication_view_id=pub_id,
                publication_view_revision=page["revision"], **extra)



def test_full_original_provisional_manifest_xlsx_preserves_unlinked_scope(fixture):
    """Original workbook lists every current run source without metadata export."""
    from io import BytesIO
    from zipfile import ZipFile
    from openpyxl import load_workbook
    from research_y import result_counts
    from research_y.provisional_manifest_workbook import render_provisional_manifest

    project, run, other, _ = fixture
    linked = insert(fixture, number=100, title="PRIVATE TITLE =SCARY",
                    groups=("g1", "g2"), abstract="SECRET ABSTRACT")
    unlinked = insert(fixture, source="wos", number=201, groups=("g2",))
    outside = insert(fixture, source="wos", number=301, run=other)
    original = identity.materialise_retrieval(project, linked, actor="Fixture")
    identity.materialise_retrieval(project, outside, actor="Fixture")
    before = sha256(project.database_path.read_bytes()).hexdigest()
    original_counts = result_counts.read_run_counts(project, run)
    raw = render_provisional_manifest(open_project(project.root), run)
    assert raw.startswith(b"PK")
    assert sha256(project.database_path.read_bytes()).hexdigest() == before
    with ZipFile(BytesIO(raw)) as zipped:
        text = "\n".join(
            zipped.read(name).decode("utf-8") for name in zipped.namelist()
            if name.startswith("xl/worksheets/") or
               name.startswith("xl/sharedStrings"))
        assert "PRIVATE TITLE =SCARY" not in text
        assert "SECRET ABSTRACT" not in text
        assert "10.1234/same-container" not in text
        assert "WOS:201" not in text
    wb = load_workbook(BytesIO(raw), read_only=True, data_only=False)
    try:
        assert wb.sheetnames == [
            "Evidence & Limits", "Provisional Identities",
            "Original Source Links", "Query Memberships"]
        facts = dict((row[0], row[1]) for row in list(
            wb["Evidence & Limits"].values)[3:])
        assert facts["Selected run ID"] == run
        assert facts["Original count revision (SHA-256)"] == original_counts.revision
        assert facts["Verified unique publications"] == "UNKNOWN"
        assert facts["Report status"] == "INCOMPLETE"
        assert facts["Unmaterialised original run source records"] == 1
        assert facts["Provisional publication identities in run"] == 1
        pubs = list(wb["Provisional Identities"].values)[3:]
        assert len(pubs) == 1
        assert pubs[0][0] == original.publication_id
        assert pubs[0][1:6] == (1, 0, 0, 1, 2)
        source_rows = list(wb["Original Source Links"].values)[3:]
        assert len(source_rows) == 2
        assert {r[0] for r in source_rows} == {linked, unlinked}
        assert {r[3] for r in source_rows} == {original.publication_id, "Unknown"}
        assert next(r for r in source_rows if r[0] == unlinked)[5].startswith(
            "UNMATERIALISED")
        members = list(wb["Query Memberships"].values)[3:]
        assert len(members) == 3
        assert {(row[0], row[3]) for row in members} == {
            (linked, "g1"), (linked, "g2"), (unlinked, "g2")}
        assert all(row[1] == run for row in members)
        assert all(
            cell.data_type != "f" for ws in wb.worksheets for row in ws
            for cell in row)
    finally:
        wb.close()


def test_provisional_manifest_includes_original_historical_source_after_review(fixture):
    from io import BytesIO
    from openpyxl import load_workbook
    from research_y.publication_candidates import read_candidate, decide_candidate
    from research_y.provisional_manifest_workbook import render_provisional_manifest
    project, run, other, _ = fixture
    a = insert(fixture, number=111, groups=("g1",))
    b = insert(fixture, number=222, source="wos", run=other)
    first = identity.materialise_retrieval(project, a, actor="Fixture")
    second = identity.materialise_retrieval(project, b, actor="Fixture")
    candidate = read_candidate(project, a, b)
    decide_candidate(
        project, a, b, expected_revision=candidate.revision,
        decision="confirmed_match", actor="Researcher",
        evidence="Synthetic explicit cross-run comparison",
        acknowledged_warnings=candidate.warnings,
        decision_confirmed=True, move_retrieval_id=a)
    before = sha256(project.database_path.read_bytes()).hexdigest()
    raw = render_provisional_manifest(project, run)
    wb = load_workbook(BytesIO(raw), read_only=True)
    try:
        pubs = list(wb["Provisional Identities"].values)[3:]
        assert len(pubs) == 1
        assert pubs[0][1:3] == (1, 1)
        assert pubs[0][0] == second.publication_id
        originals = list(wb["Original Source Links"].values)[3:]
        assert len(originals) == 2
        assert {(row[0], row[4]) for row in originals} == {
            (a, True), (b, False)}
        assert all(row[3] == second.publication_id for row in originals)
        members = list(wb["Query Memberships"].values)[3:]
        assert len(members) == 2
        assert {row[1] for row in members} == {run, other}
    finally:
        wb.close()
    assert sha256(project.database_path.read_bytes()).hexdigest() == before


def test_provisional_manifest_is_all_or_failure_for_limits_and_corrupt_original(
        fixture, monkeypatch):
    from research_y import provisional_manifest_workbook as manifest
    project, run, _, _ = fixture
    linked = insert(fixture, number=1101)
    insert(fixture, number=1102)
    identity.materialise_retrieval(project, linked, actor="Fixture")
    before = sha256(project.database_path.read_bytes()).hexdigest()
    with monkeypatch.context() as patched:
        patched.setattr(manifest, "ROW_LIMIT", 4)
        with pytest.raises(manifest.WorkbookLimitError):
            manifest.render_provisional_manifest(project, run)
    with monkeypatch.context() as patched:
        patched.setattr(manifest, "MAX_ARTIFACT_BYTES", 50)
        with pytest.raises(manifest.WorkbookLimitError):
            manifest.render_provisional_manifest(project, run)
    assert sha256(project.database_path.read_bytes()).hexdigest() == before
    assert not list((project.root / "exports").glob("*.xlsx"))
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute("UPDATE source_retrievals SET original_metadata_json='[]' "
                   "WHERE retrieval_id=?", (linked,))
    corrupted = sha256(project.database_path.read_bytes()).hexdigest()
    with pytest.raises(manifest.ProvisionalManifestError):
        manifest.render_provisional_manifest(project, run)
    assert sha256(project.database_path.read_bytes()).hexdigest() == corrupted


def test_provisional_manifest_revalidates_one_original_count_snapshot(fixture, monkeypatch):
    from research_y import result_counts
    from research_y.provisional_manifest_workbook import render_provisional_manifest
    project, run, _, _ = fixture
    insert(fixture, number=1103)
    before = sha256(project.database_path.read_bytes()).hexdigest()
    original = result_counts._snapshot
    called = []
    def witnessed(*args, **kwargs):
        called.append(1)
        return original(*args, **kwargs)
    with monkeypatch.context() as patched:
        patched.setattr(result_counts, "_snapshot", witnessed)
        raw = render_provisional_manifest(project, run)
    assert raw.startswith(b"PK")
    assert called == [1]
    assert sha256(project.database_path.read_bytes()).hexdigest() == before


def test_failed_provisional_workbook_cleans_every_temporary_xml_file(fixture, monkeypatch):
    """Repeated early aborts must not leak OpenPyXL write-only sheet files.

    This observes actual tempfile creation, registry cleanup and physical
    deletion, rather than assuming Workbook.close() releases worksheet XML.
    """
    from pathlib import Path
    from openpyxl.worksheet import _writer as xml_writer
    from research_y import provisional_manifest_workbook as manifest

    project, run, _, _ = fixture
    linked = insert(fixture, number=991, groups=("g1", "g2"))
    insert(fixture, source="wos", number=992, groups=("g2",))
    identity.materialise_retrieval(project, linked, actor="Fixture")
    original_database = sha256(project.database_path.read_bytes()).hexdigest()
    original_temps = set(xml_writer.ALL_TEMP_FILES)
    created = []
    create_original = xml_writer.create_temporary_file

    def observe_created(*args, **kwargs):
        filename = create_original(*args, **kwargs)
        created.append(filename)
        return filename

    with monkeypatch.context() as patch:
        patch.setattr(xml_writer, "create_temporary_file", observe_created)
        patch.setattr(manifest, "ROW_LIMIT", 4)
        for _ in range(3):
            with pytest.raises(manifest.WorkbookLimitError):
                manifest.render_provisional_manifest(project, run)
            assert set(xml_writer.ALL_TEMP_FILES) == original_temps
            assert all(not Path(filename).exists() for filename in created)

    # A failure during cell serialization (rather than just an explicit row
    # limit) must also discard all already opened worksheet XML writers.
    normal_literal = manifest._literal
    calls = 0

    def interrupted_literal(cell, value):
        nonlocal calls
        calls += 1
        if calls == 46:
            raise manifest.WorkbookLimitError("Synthetic interrupted writer")
        return normal_literal(cell, value)

    with monkeypatch.context() as patch:
        patch.setattr(xml_writer, "create_temporary_file", observe_created)
        patch.setattr(manifest, "_literal", interrupted_literal)
        with pytest.raises(manifest.WorkbookLimitError, match="Synthetic interrupted"):
            manifest.render_provisional_manifest(project, run)
    assert calls == 46
    assert len(created) >= 16  # Four independent sheets, four aborted renders.
    assert set(xml_writer.ALL_TEMP_FILES) == original_temps
    assert all(not Path(filename).exists() for filename in created)
    assert sha256(project.database_path.read_bytes()).hexdigest() == original_database
    assert not list((project.root / "exports").glob("*.xlsx"))


def test_manifest_export_intent_requires_exact_revision_and_researcher_consent(fixture):
    """A source-free durable approval does not generate or publish an XLSX."""
    from research_y import result_counts
    from research_y.provisional_manifest_intent import (
        preview_manifest_intent, prepare_manifest_intent, inspect_manifest_intent,
        METHOD,
    )
    project, run, _, _ = fixture
    a = insert(fixture, number=12001, groups=("g1", "g2"),
               title="PRIVATE AUTHOR TITLE", abstract="PRIVATE ABSTRACT TEXT")
    insert(fixture, number=12002, source="wos", groups=("g2",))
    identity.materialise_retrieval(project, a, actor="Fixture")
    source_digest = sha256(project.database_path.read_bytes()).hexdigest()
    preview = preview_manifest_intent(project, run)
    assert preview["method"] == METHOD
    assert preview["selected_run_original_sources"] == 2
    assert preview["provisional_publication_identities"] == 1
    assert preview["unmaterialised_original_sources"] == 1
    assert preview["global_unique_publications"] is None
    assert preview["source_retrieval_verified"] is False
    assert preview["deduplication_complete"] is False
    assert preview["workbook_published"] is False
    assert sha256(project.database_path.read_bytes()).hexdigest() == source_digest

    request = uid()
    kwargs = dict(export_id=request, expected_revision=preview["original_revision"],
                  actor="Synthetic researcher", confirmed=True)
    receipt = prepare_manifest_intent(project, run, "provisional.xlsx", **kwargs)
    assert receipt["state"] == "authorised_not_rendered"
    assert receipt["explicit_confirmation_recorded"] is True
    assert receipt["workbook_published"] is False
    assert receipt["output_bytes_written"] is False
    assert receipt["workbook_rendered"] is False
    assert receipt["source_records"] == 2
    assert receipt["provisional_identities"] == 1
    assert receipt["unmaterialised_originals"] == 1
    assert receipt["current_revision_matches"] is True
    assert receipt == inspect_manifest_intent(open_project(project.root), request)
    assert prepare_manifest_intent(project, run, "provisional.xlsx", **kwargs) == receipt
    assert "Synthetic researcher" not in repr(receipt)
    assert "PRIVATE AUTHOR TITLE" not in repr(receipt)
    assert not list((project.root / "exports").glob("*.xlsx"))
    with closing(sqlite3.connect(project.database_path)) as db:
        events = db.execute(
            "SELECT event_type,details_json FROM audit_events WHERE "
            "event_type=?", ("provisional_manifest_intent_v1:" + request,)
        ).fetchall()
        assert len(events) == 1
        assert events[0][0].endswith(request)
        assert "PRIVATE AUTHOR TITLE" not in events[0][1]
        assert "PRIVATE ABSTRACT TEXT" not in events[0][1]
        assert "source_record_id" not in events[0][1]
    assert result_counts.read_run_counts(project, run).revision == preview["original_revision"]


def test_manifest_export_intent_stale_revision_and_replay_never_reconsent(fixture):
    from research_y.provisional_manifest_intent import (
        preview_manifest_intent, prepare_manifest_intent, inspect_manifest_intent,
        ManifestIntentError,
    )
    project, run, other, _ = fixture
    insert(fixture, number=12003)
    old = preview_manifest_intent(project, run)
    insert(fixture, number=12004)
    request = uid()
    with pytest.raises(ManifestIntentError, match="stale_original_revision"):
        prepare_manifest_intent(
            project, run, "old.xlsx", export_id=request,
            expected_revision=old["original_revision"], actor="Fixture",
            confirmed=True)
    with pytest.raises(ManifestIntentError, match="intent_not_found"):
        inspect_manifest_intent(project, request)
    new = preview_manifest_intent(project, run)
    consent = prepare_manifest_intent(
        project, run, "new.xlsx", export_id=request,
        expected_revision=new["original_revision"], actor="Fixture",
        confirmed=True)
    assert consent["current_revision_matches"] is True
    insert(fixture, number=12005)
    old_consent = inspect_manifest_intent(project, request)
    assert old_consent["state"] == "stale_reapproval_required"
    assert old_consent["current_revision_matches"] is False
    assert old_consent["approved_original_revision"] == new["original_revision"]
    assert old_consent["workbook_published"] is False
    assert prepare_manifest_intent(
        project, run, "new.xlsx", export_id=request,
        expected_revision=new["original_revision"], actor="Fixture",
        confirmed=True) == old_consent
    for alter in (
        dict(output_name="other.xlsx"),
        dict(run_id=other),
        dict(actor="Another researcher"),
        dict(expected_revision="1" * 64),
    ):
        kwargs = dict(run_id=run, output_name="new.xlsx", export_id=request,
                      expected_revision=new["original_revision"], actor="Fixture",
                      confirmed=True)
        kwargs.update(alter)
        with pytest.raises(ManifestIntentError, match="intent_conflict"):
            prepare_manifest_intent(project, **kwargs)
    # A new ID is the only way to request a revision-accurate new approval.
    fresh = preview_manifest_intent(project, run)
    after = prepare_manifest_intent(
        project, run, "fresh.xlsx", export_id=uid(),
        expected_revision=fresh["original_revision"],
        actor="Fixture", confirmed=True)
    assert after["current_revision_matches"] is True
    assert after["audit_event_id"] != consent["audit_event_id"]


def test_manifest_export_intent_refuses_unconfirmed_inputs_and_existing_destination(fixture):
    from research_y.provisional_manifest_intent import (
        preview_manifest_intent, prepare_manifest_intent, ManifestIntentError,
    )
    project, run, _, _ = fixture
    insert(fixture, number=12006)
    baseline = preview_manifest_intent(project, run)
    request = uid()
    original = sha256(project.database_path.read_bytes()).hexdigest()
    for patch in (
        dict(confirmed=False), dict(confirmed=1), dict(actor=""),
        dict(actor="Researcher\nIMPLICIT"), dict(output_name="../escape.xlsx"),
        dict(output_name="report.csv"), dict(export_id="not-a-uuid"),
        dict(expected_revision="invalid"), dict(run_id="bad-run-id"),
    ):
        kwargs = dict(run_id=run, output_name="pending.xlsx",
                      export_id=request, expected_revision=baseline["original_revision"],
                      actor="Fixture", confirmed=True)
        kwargs.update(patch)
        with pytest.raises(ManifestIntentError):
            prepare_manifest_intent(project, **kwargs)
    assert sha256(project.database_path.read_bytes()).hexdigest() == original

    # Existing visible files are never overwritten or adopted as an approval.
    existing = project.root / "exports" / "pending.xlsx"
    existing.write_bytes(b"EXISTING CONTENT NOT AN EXPORT")
    with pytest.raises(ManifestIntentError, match="destination_conflict"):
        prepare_manifest_intent(
            project, run, "pending.xlsx", export_id=request,
            expected_revision=baseline["original_revision"],
            actor="Fixture", confirmed=True)
    assert existing.read_bytes() == b"EXISTING CONTENT NOT AN EXPORT"
    with closing(sqlite3.connect(project.database_path)) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM audit_events WHERE event_type=?",
            ("provisional_manifest_intent_v1:" + request,)
        ).fetchone()[0] == 0


def test_manifest_export_intent_audit_is_append_only_and_fails_closed_on_tampering(fixture):
    from research_y.provisional_manifest_intent import (
        preview_manifest_intent, prepare_manifest_intent,
        inspect_manifest_intent, ManifestIntentError,
    )
    project, run, _, _ = fixture
    insert(fixture, number=12007)
    prev = preview_manifest_intent(project, run)
    request = uid()
    before = prepare_manifest_intent(
        project, run, "audit.xlsx", export_id=request,
        expected_revision=prev["original_revision"],
        actor="Researcher", confirmed=True)
    with closing(sqlite3.connect(project.database_path)) as db, db:
        trigger = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' "
            "AND name='immutable_audit_events_update'"
        ).fetchone()
        assert trigger is not None and "append-only" in trigger[0]
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute("UPDATE audit_events SET details_json='{}' "
                       "WHERE event_id=?", (before["audit_event_id"],))
        # Deliberately corrupt ONLY this disposable fixture, then restore the
        # exact original append-only protection before exercising the service.
        db.execute("DROP TRIGGER immutable_audit_events_update")
        db.execute("UPDATE audit_events SET details_json='{}' "
                   "WHERE event_id=?", (before["audit_event_id"],))
        db.execute(trigger[0])
        assert db.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' "
            "AND name='immutable_audit_events_update'"
        ).fetchone() == trigger
    unreadable = sha256(project.database_path.read_bytes()).hexdigest()
    with pytest.raises(ManifestIntentError, match="invalid_intent_receipt"):
        inspect_manifest_intent(project, request)
    with pytest.raises(ManifestIntentError, match="invalid_intent_receipt"):
        prepare_manifest_intent(
            project, run, "audit.xlsx", export_id=request,
            expected_revision=prev["original_revision"],
            actor="Researcher", confirmed=True)
    assert sha256(project.database_path.read_bytes()).hexdigest() == unreadable



def test_manifest_intent_read_services_refuse_legacy_schema_without_migration(fixture):
    """Opening/inspection is not a schema migration or data backup request.

    Exercise a deliberately downgraded user_version on the synthetic project,
    after an actual immutable intent exists. All three services must refuse
    without any SQLite write, backup or appended migration audit event.
    """
    from research_y.schema import SCHEMA_VERSION
    from research_y.provisional_manifest_intent import (
        preview_manifest_intent, prepare_manifest_intent,
        inspect_manifest_intent, ManifestIntentError,
    )
    project, run, _, _ = fixture
    insert(fixture, number=12008)
    preview = preview_manifest_intent(project, run)
    export_id = uid()
    prepare_manifest_intent(
        project, run, "approved.xlsx", export_id=export_id,
        expected_revision=preview["original_revision"],
        actor="Researcher", confirmed=True)
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute(f"PRAGMA user_version={SCHEMA_VERSION - 1}")
    before = sha256(project.database_path.read_bytes()).hexdigest()
    backups_before = sorted((project.root / "backups").iterdir())
    with closing(sqlite3.connect(project.database_path)) as db:
        audits_before = db.execute(
            "SELECT COUNT(*) FROM audit_events"
        ).fetchone()[0]

    for check in (
        lambda: preview_manifest_intent(project, run),
        lambda: inspect_manifest_intent(project, export_id),
        lambda: prepare_manifest_intent(
            project, run, "new.xlsx", export_id=uid(),
            expected_revision=preview["original_revision"],
            actor="Researcher", confirmed=True),
    ):
        with pytest.raises(ManifestIntentError, match="source_evidence_unavailable"):
            check()
        assert sha256(project.database_path.read_bytes()).hexdigest() == before
        assert sorted((project.root / "backups").iterdir()) == backups_before
    with closing(sqlite3.connect(project.database_path)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION - 1
        assert db.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == audits_before


def test_manifest_stage_is_audited_private_and_reopen_verified(fixture):
    """Only the approved exact original revision creates an internal stage."""
    from io import BytesIO
    from openpyxl import load_workbook
    from research_y import result_counts
    from research_y.provisional_manifest_intent import (
        preview_manifest_intent, prepare_manifest_intent)
    from research_y.provisional_manifest_stage import (
        stage_manifest_workbook, inspect_manifest_stage, resume_manifest_stage,
        STORE, METHOD)
    project, run, _, _ = fixture
    linked = insert(fixture, number=23001, groups=("g1", "g2"),
                    title="PRIVATE DO NOT EXPORT", abstract="PRIVATE ABSTRACT")
    unlinked = insert(fixture, number=23002, source="wos", groups=("g2",))
    identity.materialise_retrieval(project, linked, actor="Fixture")
    with closing(sqlite3.connect(project.database_path)) as db:
        sources_before = db.execute(
            "SELECT * FROM source_retrievals ORDER BY retrieval_id").fetchall()
        members_before = db.execute(
            "SELECT * FROM query_retrievals ORDER BY retrieval_id,query_id").fetchall()
    offered = preview_manifest_intent(project, run)
    request = uid()
    prepare_manifest_intent(
        project, run, "internal-approval.xlsx", export_id=request,
        expected_revision=offered["original_revision"],
        actor="Synthetic researcher", confirmed=True)
    before = inspect_manifest_stage(project, request)
    assert before["state"] == "not_staged"
    assert before["workbook_staged"] is False
    assert before["workbook_published"] is False

    staged = stage_manifest_workbook(project, request)
    assert staged["method"] == METHOD
    assert staged["state"] == "staged"
    assert staged["workbook_staged"] is True
    assert staged["retained_artifact_verified"] is True
    assert staged["current_original_revision_matches"] is True
    assert staged["audited_publication_success"] is False
    assert staged["workbook_published"] is False
    assert staged["global_unique_publications"] is None
    assert staged["source_retrieval_verified"] is False
    assert staged["deduplication_complete"] is False
    assert not (project.root / "exports" / "internal-approval.xlsx").exists()

    store = project.root / "exports" / STORE
    files = list(store.glob("retained-*.xlsx"))
    assert len(files) == 1
    artifact = files[0].read_bytes()
    assert sha256(artifact).hexdigest() == staged["staged_artifact_sha256"]
    assert len(artifact) == staged["staged_artifact_bytes"]
    workbook = load_workbook(BytesIO(artifact), read_only=True, data_only=False)
    try:
        assert workbook.sheetnames == [
            "Evidence & Limits", "Provisional Identities",
            "Original Source Links", "Query Memberships"]
        assert len(list(workbook["Original Source Links"].values)[3:]) == 2
        assert len(list(workbook["Query Memberships"].values)[3:]) == 3
        assert len(list(workbook["Provisional Identities"].values)[3:]) == 1
        assert all(cell.data_type != "f" for ws in workbook.worksheets
                   for row in ws for cell in row)
    finally:
        workbook.close()
    assert b"PRIVATE DO NOT EXPORT" not in artifact
    assert b"PRIVATE ABSTRACT" not in artifact

    assert stage_manifest_workbook(project, request) == staged
    assert resume_manifest_stage(project, request) == staged
    assert inspect_manifest_stage(open_project(project.root), request) == staged
    assert len(list(store.glob("retained-*.xlsx"))) == 1
    with closing(sqlite3.connect(project.database_path)) as db:
        assert db.execute("SELECT * FROM source_retrievals "
                          "ORDER BY retrieval_id").fetchall() == sources_before
        assert db.execute("SELECT * FROM query_retrievals "
                          "ORDER BY retrieval_id,query_id").fetchall() == members_before
        event_ids = db.execute(
            "SELECT event_id FROM audit_events WHERE event_type=? ORDER BY event_id",
            ("provisional_manifest_stage_v1:" + request,)
        ).fetchall()
        assert len(event_ids) == 2
    assert result_counts.read_run_counts(project, run).revision == offered["original_revision"]


def test_manifest_stage_recovery_of_missing_file_matches_original_digest(fixture):
    """Crash after staging intent, before write, can recover *exact* bytes."""
    from research_y.provisional_manifest_intent import (
        preview_manifest_intent, prepare_manifest_intent)
    from research_y import provisional_manifest_stage as stage
    project, run, _, _ = fixture
    item = insert(fixture, number=23003)
    identity.materialise_retrieval(project, item, actor="Fixture")
    approved = preview_manifest_intent(project, run)
    export_id = uid()
    prepare_manifest_intent(project, run, "staging.xlsx", export_id=export_id,
                            expected_revision=approved["original_revision"],
                            actor="Researcher", confirmed=True)
    with stage.result_counts._read_connection(project) as db:
        consent = stage._intent(db, project, export_id)
    data = stage._render(project, consent)
    _, pending = stage._writer(project, export_id, content=data)
    assert pending["phase"] == "staging"
    assert stage.inspect_manifest_stage(project, export_id)["state"] == (
        "staging_interrupted")
    # Simulate restart without a file: the source revision + complete digest
    # must match the PREVIOUS immutable staging receipt before exclusive write.
    recovered = stage.resume_manifest_stage(open_project(project.root), export_id)
    assert recovered["workbook_staged"] is True
    assert recovered["staged_artifact_sha256"] == sha256(data).hexdigest()
    assert stage.inspect_manifest_stage(project, export_id) == recovered
    assert not (project.root / "exports" / "staging.xlsx").exists()
    with closing(sqlite3.connect(project.database_path)) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM audit_events WHERE event_type=?",
            ("provisional_manifest_stage_v1:" + export_id,)
        ).fetchone()[0] == 2


def test_manifest_stage_existing_non_directory_is_not_missing(fixture):
    """A hostile regular-file replacement for the private store fails closed.

    Unlike a genuinely absent directory after a staging intent, an existing
    non-directory cannot be treated as recoverable missing storage on Windows
    or Linux. The original file must remain byte-identical.
    """
    from research_y.provisional_manifest_intent import (
        preview_manifest_intent, prepare_manifest_intent)
    from research_y import provisional_manifest_stage as stage
    project, run, _, _ = fixture
    rid = insert(fixture, number=23008)
    identity.materialise_retrieval(project, rid, actor="Fixture")
    preview = preview_manifest_intent(project, run)
    export_id = uid()
    prepare_manifest_intent(
        project, run, "guarded-stage.xlsx", export_id=export_id,
        expected_revision=preview["original_revision"],
        actor="Researcher", confirmed=True)
    with stage.result_counts._read_connection(project) as db:
        approval = stage._intent(db, project, export_id)
    raw = stage._render(project, approval)
    stage._writer(project, export_id, content=raw)
    private = project.root / "exports" / stage.STORE
    assert not private.exists()
    assert stage.inspect_manifest_stage(project, export_id)["state"] == (
        "staging_interrupted")
    private.write_bytes(b"AN UNRELATED ORDINARY FILE")
    with pytest.raises(stage.ManifestStageError, match="stage_artifact_changed"):
        stage.inspect_manifest_stage(project, export_id)
    with pytest.raises(stage.ManifestStageError, match="stage_artifact_changed"):
        stage.resume_manifest_stage(project, export_id)
    assert private.read_bytes() == b"AN UNRELATED ORDINARY FILE"
    assert not (project.root / "exports" / "guarded-stage.xlsx").exists()


def test_manifest_stage_partial_or_changed_file_never_overwritten(fixture):
    from research_y.provisional_manifest_intent import (
        preview_manifest_intent, prepare_manifest_intent)
    from research_y import provisional_manifest_stage as stage
    project, run, _, _ = fixture
    item = insert(fixture, number=23004)
    identity.materialise_retrieval(project, item, actor="Fixture")
    offered = preview_manifest_intent(project, run)
    export_id = uid()
    prepare_manifest_intent(project, run, "pending.xlsx", export_id=export_id,
                            expected_revision=offered["original_revision"],
                            actor="Researcher", confirmed=True)
    with stage.result_counts._read_connection(project) as db:
        consent = stage._intent(db, project, export_id)
    original = stage._render(project, consent)
    _, pending = stage._writer(project, export_id, content=original)
    with stage._store(project, create=True) as store:
        store.write_new(pending["artifact"]["name"], b"PARTIAL FILE DATA")
    file = project.root / "exports" / stage.STORE / pending["artifact"]["name"]
    with pytest.raises(stage.ManifestStageError, match="stage_artifact_changed"):
        stage.inspect_manifest_stage(project, export_id)
    with pytest.raises(stage.ManifestStageError, match="stage_artifact_changed"):
        stage.resume_manifest_stage(project, export_id)
    with pytest.raises(stage.ManifestStageError, match="stage_artifact_changed"):
        stage.stage_manifest_workbook(project, export_id)
    assert file.read_bytes() == b"PARTIAL FILE DATA"
    with closing(sqlite3.connect(project.database_path)) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM audit_events WHERE event_type=?",
            ("provisional_manifest_stage_v1:" + export_id,)
        ).fetchone()[0] == 1


def test_manifest_stage_fences_changed_original_evidence_and_rejects_legacy(fixture):
    from research_y.schema import SCHEMA_VERSION
    from research_y.provisional_manifest_intent import (
        preview_manifest_intent, prepare_manifest_intent)
    from research_y import provisional_manifest_stage as stage
    project, run, _, queries = fixture
    insert(fixture, number=23005)
    offered = preview_manifest_intent(project, run)
    export_id = uid()
    prepare_manifest_intent(project, run, "fenced.xlsx", export_id=export_id,
                            expected_revision=offered["original_revision"],
                            actor="Researcher", confirmed=True)
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute("UPDATE source_queries SET status='failed' WHERE query_id=?",
                   (queries[run, "g1", "pubmed"],))
    with pytest.raises(stage.ManifestStageError, match="stage_revision_stale"):
        stage.stage_manifest_workbook(project, export_id)
    asserted = stage.inspect_manifest_stage(project, export_id)
    assert asserted["state"] == "stale_reapproval_required"
    assert asserted["workbook_staged"] is False
    assert not list((project.root / "exports").glob("*.xlsx"))

    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute(f"PRAGMA user_version={SCHEMA_VERSION-1}")
    database_before = sha256(project.database_path.read_bytes()).hexdigest()
    backups_before = list((project.root / "backups").iterdir())
    with pytest.raises((stage.ManifestStageError, ValueError)):
        stage.inspect_manifest_stage(project, export_id)
    with pytest.raises((stage.ManifestStageError, ValueError)):
        stage.stage_manifest_workbook(project, export_id)
    assert sha256(project.database_path.read_bytes()).hexdigest() == database_before
    assert list((project.root / "backups").iterdir()) == backups_before


def test_manifest_stage_commit_window_rejects_source_change_after_render(fixture, monkeypatch):
    """Race before staging event cannot authorise a different source revision."""
    from research_y.provisional_manifest_intent import (
        preview_manifest_intent, prepare_manifest_intent)
    from research_y import provisional_manifest_stage as stage
    project, run, _, queries = fixture
    item = insert(fixture, number=23006)
    identity.materialise_retrieval(project, item, actor="Fixture")
    offer = preview_manifest_intent(project, run)
    export_id = uid()
    prepare_manifest_intent(project, run, "concurrent.xlsx", export_id=export_id,
                            expected_revision=offer["original_revision"],
                            actor="Researcher", confirmed=True)
    actual = stage._render

    def changed_after_render(project_arg, original_approval):
        raw = actual(project_arg, original_approval)
        with closing(sqlite3.connect(project.database_path)) as db, db:
            db.execute("UPDATE source_queries SET status='failed' WHERE query_id=?",
                       (queries[run, "g1", "pubmed"],))
        return raw

    with monkeypatch.context() as patched:
        patched.setattr(stage, "_render", changed_after_render)
        with pytest.raises(stage.ManifestStageError, match="stage_revision_stale"):
            stage.stage_manifest_workbook(project, export_id)
    assert not list((project.root / "exports").glob("*.xlsx"))
    with closing(sqlite3.connect(project.database_path)) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM audit_events WHERE event_type=?",
            ("provisional_manifest_stage_v1:" + export_id,)
        ).fetchone()[0] == 0


def test_manifest_stage_recovery_normalises_changed_workbook_and_zip_clock(fixture, monkeypatch):
    """A later-day retry has the EXACT immutable staged digest, not a new ZIP.

    Drive two deliberately distinct, readable generated XLSX packages whose
    OpenPyXL core XML and ZIP entry timestamps differ, without sleeping or
    depending on runner wall-clock speed. Only the approved original consent
    time may determine the persisted archive's normalized metadata.
    """
    from io import BytesIO
    from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED
    from xml.etree import ElementTree as ET
    from openpyxl import load_workbook
    from research_y.provisional_manifest_intent import (
        preview_manifest_intent, prepare_manifest_intent)
    from research_y import provisional_manifest_stage as stage

    project, run, _, _ = fixture
    record = insert(fixture, number=23007)
    identity.materialise_retrieval(project, record, actor="Fixture")
    preview = preview_manifest_intent(project, run)
    export_id = uid()
    prepare_manifest_intent(
        project, run, "time-safe.xlsx", export_id=export_id,
        expected_revision=preview["original_revision"],
        actor="Researcher", confirmed=True)
    with stage.result_counts._read_connection(project) as db:
        approval = stage._intent(db, project, export_id)

    original_render = stage.render_provisional_manifest
    early = original_render(project, run)

    def advanced_zip_and_core_clock(raw):
        output = BytesIO()
        with ZipFile(BytesIO(raw)) as source, ZipFile(
                output, "w", compression=ZIP_DEFLATED) as target:
            for member in source.infolist():
                data = source.read(member)
                if member.filename == "docProps/core.xml":
                    root = ET.fromstring(data)
                    for field in ("created", "modified"):
                        node = root.find("{" + stage._CORE_NS + "}" + field)
                        assert node is not None
                        node.text = "2048-11-12T21:45:06Z"
                    data = ET.tostring(root, encoding="utf-8",
                                       xml_declaration=True)
                altered = ZipInfo(member.filename, (2048, 11, 12, 21, 45, 6))
                altered.compress_type = ZIP_DEFLATED
                target.writestr(altered, data)
        return output.getvalue()

    late = advanced_zip_and_core_clock(early)
    assert late != early
    assert stage._stable_package(early, approval) == (
        stage._stable_package(late, approval))
    # Create one durable staging receipt but interrupt before file creation.
    immutable = stage._stable_package(early, approval)
    _, pending = stage._writer(project, export_id, content=immutable)
    assert pending["phase"] == "staging"
    assert stage.inspect_manifest_stage(project, export_id)["state"] == (
        "staging_interrupted")

    with monkeypatch.context() as patch:
        patch.setattr(stage, "render_provisional_manifest",
                      lambda *_: advanced_zip_and_core_clock(
                          original_render(project, run)))
        resumed = stage.resume_manifest_stage(project, export_id)
    assert resumed["state"] == "staged"
    assert resumed["staged_artifact_sha256"] == sha256(immutable).hexdigest()
    retained = list((project.root / "exports" / stage.STORE).glob("*.xlsx"))
    assert len(retained) == 1
    assert retained[0].read_bytes() == immutable
    workbook = load_workbook(BytesIO(immutable), read_only=True)
    try:
        assert workbook.sheetnames == [
            "Evidence & Limits", "Provisional Identities",
            "Original Source Links", "Query Memberships"]
    finally:
        workbook.close()
    assert not (project.root / "exports" / "time-safe.xlsx").exists()



def _consented_staged_manifest(fixture, *, number=24001, output="approved-manifest.xlsx"):
    """Original retained source, explicit approval, verified private XLSX stage."""
    from research_y.provisional_manifest_intent import (
        preview_manifest_intent, prepare_manifest_intent,
    )
    from research_y.provisional_manifest_stage import stage_manifest_workbook
    project, run, _, _ = fixture
    rid = insert(fixture, number=number,
                 title="RESTRICTED ORIGINAL TITLE",
                 abstract="RESTRICTED ORIGINAL ABSTRACT")
    identity.materialise_retrieval(project, rid, actor="Fixture")
    offer = preview_manifest_intent(project, run)
    export_id = uid()
    prepared = prepare_manifest_intent(
        project, run, output, export_id=export_id,
        expected_revision=offer["original_revision"],
        actor="Researcher", confirmed=True)
    assert prepared["explicit_confirmation_recorded"] is True
    staged = stage_manifest_workbook(project, export_id)
    assert staged["state"] == "staged"
    assert staged["workbook_published"] is False
    return project, run, rid, export_id, offer


def test_manifest_publication_requires_stage_then_reopened_audited_success(fixture):
    from io import BytesIO
    from zipfile import ZipFile
    from openpyxl import load_workbook
    from research_y import provisional_manifest_publication as publication
    project, run, rid, export_id, offer = _consented_staged_manifest(fixture)
    with closing(sqlite3.connect(project.database_path)) as db:
        original = db.execute(
            "SELECT * FROM source_retrievals ORDER BY retrieval_id").fetchall()
        memberships = db.execute(
            "SELECT * FROM query_retrievals ORDER BY query_id").fetchall()
    assert publication.inspect_manifest_publication(project, export_id)["state"] == (
        "not_published")
    visible = project.root / "exports" / "approved-manifest.xlsx"
    assert not visible.exists()
    result = publication.publish_manifest_workbook(project, export_id)
    assert result["method"] == publication.METHOD
    assert result["state"] == "published_verified"
    assert result["workbook_published"] is True
    assert result["audited_publication_success"] is True
    assert result["historical_artifact_verified"] is True
    assert result["current_original_revision_matches"] is True
    assert result["approved_original_revision"] == offer["original_revision"]
    assert result["global_unique_publications"] is None
    assert result["deduplication_complete"] is False
    assert result["verified_complete"] is False
    assert result["source_retrieval_verified"] is False
    assert visible.is_file()
    assert publication.inspect_manifest_publication(
        open_project(project.root), export_id) == result
    assert publication.publish_manifest_workbook(project, export_id) == result
    assert publication.resume_manifest_publication(project, export_id) == result

    with closing(sqlite3.connect(project.database_path)) as db:
        assert db.execute(
            "SELECT * FROM source_retrievals ORDER BY retrieval_id").fetchall() == original
        assert db.execute(
            "SELECT * FROM query_retrievals ORDER BY query_id").fetchall() == memberships
        assert db.execute(
            "SELECT COUNT(*) FROM audit_events WHERE event_type=?",
            ("provisional_manifest_publish_v1:" + export_id,)
        ).fetchone()[0] == 2
    with publication.Directory(project.root / "exports") as exports:
        approved, stage_receipt, published, _ = _publication_receipts(
            publication, project, export_id)
        assert exports.same_file(published["copy_name"], visible.name) is True
    raw = visible.read_bytes()
    assert sha256(raw).hexdigest() == stage_receipt["artifact"]["sha256"]
    with ZipFile(BytesIO(raw)) as archive:
        contents = b"".join(
            archive.read(name) for name in archive.namelist()
            if name.startswith("xl/worksheets/"))
        assert b"RESTRICTED ORIGINAL TITLE" not in contents
        assert b"RESTRICTED ORIGINAL ABSTRACT" not in contents
    wb = load_workbook(BytesIO(raw), read_only=True, data_only=False)
    try:
        assert wb.sheetnames == [
            "Evidence & Limits", "Provisional Identities",
            "Original Source Links", "Query Memberships",
        ]
        facts = dict(list(wb["Evidence & Limits"].values)[3:])
        assert facts["Report status"] == "INCOMPLETE"
        assert facts["Verified unique publications"] == "UNKNOWN"
    finally:
        wb.close()


def _publication_receipts(publication, project, export_id):
    with publication.result_counts._read_connection(project) as db:
        approved = publication.stage._intent(db, project, export_id)
        stage_receipt = publication.stage._load(db, project, approved)
        published = publication._load(db, approved, stage_receipt)
    return approved, stage_receipt, published, project


def test_manifest_publication_crash_after_intent_before_any_file_recovers(fixture):
    from research_y import provisional_manifest_publication as publication
    project, _, _, export_id, _ = _consented_staged_manifest(
        fixture, number=24002, output="crash-before-copy.xlsx")
    assert publication._begin(project, export_id) == "publishing"
    pending = publication.inspect_manifest_publication(project, export_id)
    assert pending["state"] == "publishing_interrupted"
    assert pending["workbook_published"] is False
    assert not (project.root / "exports" / "crash-before-copy.xlsx").exists()
    reopened = publication.resume_manifest_publication(
        open_project(project.root), export_id)
    assert reopened["state"] == "published_verified"
    assert reopened["audited_publication_success"] is True
    assert publication.inspect_manifest_publication(project, export_id) == reopened
    assert publication.publish_manifest_workbook(project, export_id) == reopened


def test_manifest_publication_crash_after_copy_then_link_recovers(fixture):
    from research_y import provisional_manifest_publication as publication
    project, _, _, export_id, _ = _consented_staged_manifest(
        fixture, number=24003, output="crash-after-copy.xlsx")
    publication._begin(project, export_id)
    approved, staged, pending, _ = _publication_receipts(
        publication, project, export_id)
    with publication.stage._store(project) as store:
        artifact = staged["artifact"]
        raw = store.read(
            artifact["name"], digest=artifact["sha256"], size=artifact["size"])
    with publication.Directory(project.root / "exports") as dest:
        dest.write_new(pending["copy_name"], raw)
    midway = publication.inspect_manifest_publication(project, export_id)
    assert midway["state"] == "publishing_copy_ready"
    assert midway["workbook_published"] is False
    done = publication.resume_manifest_publication(project, export_id)
    assert done["state"] == "published_verified"
    with publication.Directory(project.root / "exports") as dest:
        assert dest.same_file(pending["copy_name"], approved["output_name"])


def test_manifest_publication_crash_after_visible_hardlink_before_receipt(fixture):
    from research_y import provisional_manifest_publication as publication
    project, _, _, export_id, _ = _consented_staged_manifest(
        fixture, number=24004, output="crash-after-visible.xlsx")
    publication._begin(project, export_id)
    approved, staged, pending, _ = _publication_receipts(
        publication, project, export_id)
    artifact = staged["artifact"]
    with publication.stage._store(project) as source:
        raw = source.read(artifact["name"],
                          digest=artifact["sha256"], size=artifact["size"])
    with publication.Directory(project.root / "exports") as dest:
        dest.write_new(pending["copy_name"], raw)
        dest.flush(pending["copy_name"])
        dest.publish_link(pending["copy_name"], approved["output_name"])
    observed = publication.inspect_manifest_publication(project, export_id)
    assert observed["state"] == "awaiting_publication_receipt"
    assert observed["workbook_published"] is False
    assert observed["audited_publication_success"] is False
    done = publication.resume_manifest_publication(
        open_project(project.root), export_id)
    assert done["state"] == "published_verified"
    assert done["audited_publication_success"] is True
    with closing(sqlite3.connect(project.database_path)) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM audit_events WHERE event_type=?",
            ("provisional_manifest_publish_v1:" + export_id,)
        ).fetchone()[0] == 2


def test_manifest_publication_does_not_adopt_unrelated_identical_file(fixture):
    from research_y import provisional_manifest_publication as publication
    project, _, _, export_id, _ = _consented_staged_manifest(
        fixture, number=24005, output="unrelated-identical.xlsx")
    publication._begin(project, export_id)
    approved, staged, pending, _ = _publication_receipts(
        publication, project, export_id)
    artifact = staged["artifact"]
    with publication.stage._store(project) as source:
        raw = source.read(artifact["name"],
                          digest=artifact["sha256"], size=artifact["size"])
    # Another creator's byte-identical *separate file* must not substitute
    # for this specific request's durable destination-side copy.
    final = project.root / "exports" / approved["output_name"]
    final.write_bytes(raw)
    before = sha256(final.read_bytes()).hexdigest()
    with pytest.raises(publication.ManifestPublicationError,
                       match="publication_destination_conflict"):
        publication.resume_manifest_publication(project, export_id)
    assert sha256(final.read_bytes()).hexdigest() == before
    assert not (project.root / "exports" / pending["copy_name"]).exists()
    with closing(sqlite3.connect(project.database_path)) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM audit_events WHERE event_type=?",
            ("provisional_manifest_publish_v1:" + export_id,)
        ).fetchone()[0] == 1


def test_manifest_publication_rejects_changed_copy_without_overwriting(fixture):
    from research_y import provisional_manifest_publication as publication
    project, _, _, export_id, _ = _consented_staged_manifest(
        fixture, number=24006, output="corrupt-copy.xlsx")
    publication._begin(project, export_id)
    _, _, pending, _ = _publication_receipts(publication, project, export_id)
    with publication.Directory(project.root / "exports") as dest:
        dest.write_new(pending["copy_name"], b"NOT THE APPROVED WORKBOOK")
    copy = project.root / "exports" / pending["copy_name"]
    with pytest.raises(publication.ManifestPublicationError,
                       match="publication_artifact_changed"):
        publication.inspect_manifest_publication(project, export_id)
    with pytest.raises(publication.ManifestPublicationError,
                       match="publication_artifact_changed"):
        publication.resume_manifest_publication(project, export_id)
    assert copy.read_bytes() == b"NOT THE APPROVED WORKBOOK"
    assert not (project.root / "exports" / "corrupt-copy.xlsx").exists()


def test_manifest_publication_stale_source_and_stale_historical_display(fixture):
    from research_y import provisional_manifest_publication as publication
    project, run, _, queries = fixture
    rid = insert(fixture, number=24007)
    identity.materialise_retrieval(project, rid, actor="Fixture")
    from research_y.provisional_manifest_intent import (
        preview_manifest_intent, prepare_manifest_intent)
    offer = preview_manifest_intent(project, run)
    export_id = uid()
    prepare_manifest_intent(project, run, "stale-before.xlsx", export_id=export_id,
                            expected_revision=offer["original_revision"],
                            actor="Researcher", confirmed=True)
    publication.stage.stage_manifest_workbook(project, export_id)
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute(
            "UPDATE source_queries SET status='failed' WHERE query_id=?",
            (queries[run, "g1", "pubmed"],))
    before = publication.inspect_manifest_publication(project, export_id)
    assert before["state"] == "stale_reapproval_required"
    assert before["workbook_published"] is False
    with pytest.raises(publication.ManifestPublicationError,
                       match="publication_revision_stale"):
        publication.publish_manifest_workbook(project, export_id)
    assert not (project.root / "exports" / "stale-before.xlsx").exists()
    # A previously published original snapshot remains demonstrably historical
    # if the source evolves afterward, not silently made current or complete.
# Restore source state in the same disposable fixture only to exercise a
    # separate valid approval and the historical inspection transition.
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute(
            "UPDATE source_queries SET status='pending' WHERE query_id=?",
            (queries[run, "g1", "pubmed"],))
    fresh = preview_manifest_intent(project, run)
    subsequent = uid()
    prepare_manifest_intent(project, run, "stale-after.xlsx",
                            export_id=subsequent, expected_revision=fresh["original_revision"],
                            actor="Researcher", confirmed=True)
    publication.stage.stage_manifest_workbook(project, subsequent)
    assert publication.publish_manifest_workbook(
        project, subsequent)["state"] == "published_verified"
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute(
            "UPDATE source_queries SET status='failed' WHERE query_id=?",
            (queries[run, "g1", "pubmed"],))
    historical = publication.inspect_manifest_publication(project, subsequent)
    assert historical["state"] == "published_previous_revision"
    assert historical["historical_artifact_verified"] is True
    assert historical["audited_publication_success"] is False
    assert historical["workbook_published"] is True
    assert historical["verified_complete"] is False
    with pytest.raises(publication.ManifestPublicationError,
                       match="publication_revision_stale"):
        publication.publish_manifest_workbook(project, subsequent)


def test_manifest_publication_refuses_changed_source_between_intent_and_link(
        fixture):
    from research_y import provisional_manifest_publication as publication
    project, run, _, queries = fixture
    rid = insert(fixture, number=24008)
    identity.materialise_retrieval(project, rid, actor="Fixture")
    from research_y.provisional_manifest_intent import (
        preview_manifest_intent, prepare_manifest_intent)
    offer = preview_manifest_intent(project, run)
    export_id = uid()
    prepare_manifest_intent(project, run, "race.xlsx", export_id=export_id,
                            expected_revision=offer["original_revision"],
                            actor="Researcher", confirmed=True)
    publication.stage.stage_manifest_workbook(project, export_id)
    publication._begin(project, export_id)
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute(
            "UPDATE source_queries SET status='failed' WHERE query_id=?",
            (queries[run, "g1", "pubmed"],))
    with pytest.raises(publication.ManifestPublicationError,
                       match="publication_revision_stale"):
        publication.resume_manifest_publication(project, export_id)
    assert not (project.root / "exports" / "race.xlsx").exists()
    with closing(sqlite3.connect(project.database_path)) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM audit_events WHERE event_type=?",
            ("provisional_manifest_publish_v1:" + export_id,)
        ).fetchone()[0] == 1
