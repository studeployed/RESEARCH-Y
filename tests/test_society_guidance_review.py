from uuid import uuid4

import pytest

from research_y.publication_identity import materialise_retrieval, read_publication, reverse_association
from research_y.society_guidance_review import suggest_societies, relate_guidance, attach_journal_manifestation
from research_y.society_sources import record_society_visit, import_guidance, list_societies
from test_publication_identity import store,db_rows
from test_society_sources import register,visit_args


def test_suggestions_use_bounded_terms_and_require_researcher_confirmation(store):
    project,_ = store
    options=suggest_societies(["venovenous ECMO","intensive care","ARDS"])
    assert len(options)==3 and all(o["researcher_confirmation_required"] for o in options)
    assert options[0]["official_url"].startswith("https://www.elso.org/")
    assert options[0]["matched_terms"]==["venovenous ECMO"] and list_societies(project)==[]
    assert suggest_societies(["ECMOLOGY"]) == []


def test_explicit_version_and_journal_manifestation_keep_sources_distinct(store):
    project,ids = store
    society=register(project)
    visit=record_society_visit(project,**visit_args(society))
    pubs=[]
    for edition in ("first","second"):
        receipt=import_guidance(project,request_id=str(uuid4()),run_id=db_rows(project,"search_runs")[0][0],
                visit_event_id=visit["event_id"],record={"title":"Guidance","edition":edition,
                "landing_url":"https://society.example/guidance","document_types":["guideline"]},
                roles={"issuing":[society["society_id"]]},actor="Reviewer",confirmed=True)
        pubs.append(read_publication(project,receipt["publication_id"]))
    first,second=pubs
    args=dict(request_id=str(uuid4()),publication_id=second.publication_id,other_publication_id=first.publication_id,
              expected_revision=second.revision,other_revision=first.revision,actor="Reviewer",
              relation="supersedes",rationale="Explicit edition statement",confirmed=True)
    relation=relate_guidance(project,**args)
    assert relate_guidance(project,**args)==relation
    with pytest.raises(ValueError,match="cycle"):
        relate_guidance(project,**{**args,"request_id":str(uuid4()),"publication_id":first.publication_id,
                         "other_publication_id":second.publication_id,"expected_revision":first.revision,
                         "other_revision":second.revision})
    journal=materialise_retrieval(project,ids[0],actor="Reviewer")
    primary=db_rows(project,"query_retrievals"),db_rows(project,"source_queries")
    attach_args=dict(society_publication_id=second.publication_id,journal_retrieval_id=ids[0],
                     society_revision=second.revision,journal_revision=journal.revision,
                     actor="Reviewer",rationale="Same verified edition with stated joint publication",confirmed=True)
    combined=attach_journal_manifestation(project,**attach_args)
    assert combined.publication_id==second.publication_id and {r["source_name"] for r in combined.retrievals}=={"society","pubmed"}
    assert attach_journal_manifestation(project,**attach_args).revision==combined.revision
    assert read_publication(project,first.publication_id).active
    assert primary==(db_rows(project,"query_retrievals"),db_rows(project,"source_queries"))
    roles=db_rows(project,"publication_organisations")
    entry=next(r for r in combined.retrievals if r["retrieval_id"]==ids[0])
    restored=reverse_association(project,ids[0],entry["association_event_id"],
                  expected_current_revision=combined.revision,
                  expected_restored_revision=read_publication(project,journal.publication_id).revision,
                  actor="Reviewer",evidence="Correcting a manifestation association")
    assert restored.publication_id==journal.publication_id
    assert {r["source_name"] for r in read_publication(project,second.publication_id).retrievals}=={"society"}
    assert roles==db_rows(project,"publication_organisations")
