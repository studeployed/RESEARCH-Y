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
