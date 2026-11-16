from contextlib import closing
import sqlite3
from uuid import uuid4

import pytest

from research_y import master_results, project_documents, publication_identity as identity, study_classification
from research_y.publication_fields import select_source_field
from research_y.projects import open_project
from research_y.publication_review_gui import (preview_candidate_review, record_candidate_review,
    preview_candidate_reversal, confirm_candidate_reversal, PublicationReviewError)
from research_y.result_counts import read_run_counts
from test_reviewed_master import populated


def preview(project,run,left,right):
    return preview_candidate_review(project,run,left,right,run_revision=read_run_counts(project,run).revision)


def move(project,run,left,right,plan):
    return record_candidate_review(project,run,left,right,run_revision=plan["run_revision"],
             expected_revision=plan["revision"],decision="confirmed_match",move_retrieval_id=left,actor="Reviewer",
             evidence="Compared both originals and reviewed their existing annotations",warnings_acknowledged=True,confirmed=True)


def undo(project,run,rid):
    plan=preview_candidate_reversal(project,run,rid,run_revision=read_run_counts(project,run).revision)
    return confirm_candidate_reversal(project,run,rid,run_revision=plan["run_revision"],expected_revision=plan["revision"],
                                      actor="Reviewer",evidence="Confirmed distinct publication",confirmed=True)


def test_rejecting_an_annotated_pair_returns_the_reopened_review_revision(tmp_path):
    project, run, _, ids = populated(tmp_path)
    left, right = ids["111"], ids["222"]
    pub = identity.materialise_retrieval(project, left, actor="Reviewer")
    select_source_field(project, pub.publication_id, "title", retrieval_id=left, path=("record", "title"),
                        expected_revision=pub.revision, actor="Reviewer", reason="Checked title")
    plan = preview(project, run, left, right)
    result = record_candidate_review(project, run, left, right, run_revision=plan["run_revision"],
        expected_revision=plan["revision"], decision="rejected_match", move_retrieval_id=None, actor="Reviewer",
        evidence="Distinct articles", warnings_acknowledged=True, confirmed=True)
    reopened = preview(open_project(project.root), run, left, right)
    assert reopened["status"] == "rejected_match"
    assert reopened["revision"] == result["resulting_candidate_revision"]


@pytest.mark.parametrize("specialist", ["society", "conference"])
def test_shared_link_reversal_checks_where_the_other_supporting_original_is_now(tmp_path, specialist):
    project, run, _, ids = populated(tmp_path)
    journal, other = ids["111"], ids["222"]
    target = identity.materialise_retrieval(project, journal, actor="Reviewer").publication_id
    if specialist == "society":
        from research_y.society_sources import record_society_visit, import_guidance
        from test_society_sources import register, visit_args
        org = register(project)
        req = visit_args(org)
        visit = record_society_visit(project, **req)
        originals = [import_guidance(project, run_id=run, request_id=str(uuid4()), visit_event_id=visit["event_id"],
            record=dict(title=title, document_types=["guideline"], landing_url=req["pages"][0]["url"]),
            roles={"issuing": [org["society_id"]]}, actor="Reviewer", confirmed=True) for title in ("First", "Second")]
        table = "publication_organisations"
    else:
        from research_y.conference_project import preview_extraction, admit_extraction
        from test_conference_jats import XML
        offer = preview_extraction(project, journal, XML)
        originals = admit_extraction(project, journal, XML, locators=[a["locator"] for a in offer["extraction"]["abstracts"]],
            expected_revision=offer["revision"], actor="Reviewer", confirmed=True, retention_authorized=True)["admitted"]
        table = "publication_containers"
    first, second = [original["retrieval_id"] for original in originals]
    for moving, destination in ((first, journal), (second, journal), (first, other)):
        move(project, run, moving, destination, preview(project, run, moving, destination))
    undo(project, run, second)
    with closing(sqlite3.connect(project.database_path)) as db:
        assert db.execute(f"SELECT COUNT(*) FROM {table} WHERE publication_id=?", (target,)).fetchone() == (0,)
        assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone() == (2,)


def test_sole_annotated_original_keeps_accessible_provenance_and_restores_field_on_split(tmp_path):
    from research_y.bibliographic_import import admit_records
    project,run,_,ids=populated(tmp_path)
    donor=admit_records(project,run,"Researcher's import",manual=dict(title="Original citation"),indices=[0],
                        revision=None,actor="Reviewer",confirmed=True)["admitted"][0]
    left,original=donor["retrieval_id"],donor["publication_id"]
    right=ids["111"]
    target=identity.materialise_retrieval(project,right,actor="Reviewer").publication_id
    for pid,rid in ((original,left),(target,right)):
        select_source_field(project,pid,"title",retrieval_id=rid,path=("record","title"),
                            expected_revision=identity.read_publication(project,pid).revision,actor="R",reason="Checked source")
    labels=study_classification.read_classification(project,original)
    study_classification.review_classification(project,original,dimension="language",labels=["English"],actor="Reviewer",
                 rationale="Read manuscript",expected_revision=labels["revision"],confirmed=True)
    old=preview(project,run,left,right)
    doc=tmp_path/"Original.pdf"
    doc.write_bytes(b"%PDF-1.4\nSynthetic original")
    attached=project_documents.attach_pdf(project,original,doc,actor="Researcher",source_url=None,permission_confirmed=True)
    with pytest.raises(PublicationReviewError,match="stale"):
        move(project,run,left,right,old)
    offer=preview(project,run,left,right)
    p=offer["move_dispositions"][left]
    assert p["sole_source"] and p["classifications"]==p["documents"]==1 and p["keep_target_fields"]==["title"]
    move(project,run,left,right,offer)
    reopened=open_project(project.root)
    assert not identity.read_publication(reopened,original).active
    with closing(master_results.MasterResults.capture(reopened,run)) as master:
        record=master.detail(reopened,target)
        assert record["chosen_fields"]["title"]["provenance"]["retrieval_id"]==right
        historical,=record["prior_identity_evidence"]
        assert historical["origin"]==original and historical["prior_fields"]==["title"]
        assert historical["classifications"][0]["dimension"]=="language"
        assert historical["documents"][0]["document_id"]==attached["document_id"]
    undo(reopened,run,left)
    restored=identity.read_publication(reopened,original)
    assert restored.active and restored.chosen_fields["title"]["value"]=="Original citation"
    assert project_documents.list_attachments(reopened,original)[0]["verified_provenance"]
    assert study_classification.read_classification(reopened,original)["decisions"]["language"]["actor"]=="Reviewer"


def test_society_roles_and_conference_container_follow_original_and_reverse(tmp_path):
    from research_y.society_sources import record_society_visit, import_guidance
    from research_y.conference_project import preview_extraction,admit_extraction
    from test_conference_jats import XML
    from test_society_sources import register,visit_args
    project,run,_,ids=populated(tmp_path)
    right=ids["111"]
    target=identity.materialise_retrieval(project,right,actor="Reader").publication_id
    org=register(project)
    req=visit_args(org)
    visit=record_society_visit(project,**req)
    guidance=import_guidance(project,run_id=run,request_id=str(uuid4()),visit_event_id=visit["event_id"],
        record=dict(title="Society guidance",document_types=["guideline"],landing_url=req["pages"][0]["url"]),
        roles={"issuing":[org["society_id"]]},actor="Reader",confirmed=True)
    opts=dict(pdf_url="https://example.test/supp.pdf",pdf_pages={"a":8})
    conf=preview_extraction(project,right,XML,**opts)
    receipt=admit_extraction(project,right,XML,locators=[conf["extraction"]["abstracts"][0]["locator"]],
                  expected_revision=conf["revision"],actor="Reader",confirmed=True,retention_authorized=True,**opts)
    abstract=receipt["admitted"][0]
    for record,table,column,key in ((guidance,"publication_organisations","organisation_id",org["society_id"]),
                                    (abstract,"publication_containers","container_id",receipt["container_id"])):
        left,origin=record["retrieval_id"],record["publication_id"]
        prior=identity.read_publication(project,origin)
        select_source_field(project,origin,"title",retrieval_id=left,path=("record","title"),expected_revision=prior.revision,
                            actor="Reader",reason="Used original title")
        plan=preview(project,run,left,right)
        assert plan["move_dispositions"][left]["apply_fields"]==["title"]
        move(project,run,left,right,plan)
        with closing(sqlite3.connect(project.database_path)) as db:
            assert list(db.execute(f"SELECT publication_id FROM {table} WHERE {column}=?",(key,)))==[(target,)]
        assert identity.read_publication(project,target).chosen_fields["title"]["provenance"]["retrieval_id"]==left
        undo(project,run,left)
        with closing(sqlite3.connect(project.database_path)) as db:
            assert list(db.execute(f"SELECT publication_id FROM {table} WHERE {column}=?",(key,)))==[(origin,)]
        assert identity.read_publication(project,origin).chosen_fields["title"]["provenance"]["retrieval_id"]==left
