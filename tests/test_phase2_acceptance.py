"""Published source denominators and specialist outcomes on one reopened project."""
from uuid import uuid4

from research_y.conference_project import admit_extraction, preview_extraction
from research_y.crossref_metadata import inspect_enrichment
from research_y.projects import open_project
from research_y.publication_results import read_publication_page
from research_y.run_execution_board import read_run_execution_board
from research_y.society_sources import import_guidance, record_society_visit
from research_y.study_classification import read_classification
from research_y.study_review_queue import read_study_page
from research_y.workbook_exports import prepare_workbook_export
from test_conference_jats import XML
from test_reviewed_master import populated, decide
from test_society_sources import register, visit_args


def test_joint_specialist_sources_preserve_primary_workbook_and_attributable_labels(tmp_path):
    project, run, _, ids = populated(tmp_path)
    decide(project, ids["111"], ids["WOS:000000001"], "confirmed_match")
    decide(project, ids["111"], ids["222"], "rejected_match")
    primary = read_run_execution_board(project,run)
    options = dict(terms=["right ventricle","ECMO"], pdf_url="https://example.test/supplement.pdf",
                   pdf_pages={"a":8})
    preview = preview_extraction(project,ids["111"],XML,**options)
    items = preview["extraction"]["abstracts"]
    assert [a["matched_terms"] for a in items] == [["right ventricle"],["ECMO"]]
    accepted = admit_extraction(project,ids["111"],XML,locators=[a["locator"] for a in items],
                                expected_revision=preview["revision"],actor="Reviewer",confirmed=True,
                                retention_authorized=True,**options)
    org = register(project)
    visit = record_society_visit(project,**visit_args(org))
    guidance = import_guidance(project,run_id=run,request_id=str(uuid4()),visit_event_id=visit["event_id"],
                    record={"title":"Official rehabilitation guidance","document_types":["clinical practice guideline"],
                            "landing_url":"https://society.example/guidance"},
                    roles={"issuing":[org["society_id"]]},actor="Reviewer",confirmed=True)
    project = open_project(project.root)
    board = read_run_execution_board(project,run)
    assert board["source_count_revision"] == primary["source_count_revision"]
    assert board["reconciled_primary_run_unique_publications"] == 2
    assert board["supplementary_source_records"] == {"conference_jats":2,"society":1}
    assert prepare_workbook_export(project,run,"Reviewed.xlsx",export_id=str(uuid4()),
                                   reviewed_revision=board["source_count_revision"]).export_id
    results = read_publication_page(project,run)
    titles = {r["publication_id"]:r["title"] for r in results["rows"]}
    for child in accepted["admitted"]:
        pid = child["publication_id"]
        assert titles[pid] == "Short abstract"
        assert read_classification(project,pid)["current"]["format"] == ["conference abstract"]
    pid = guidance["publication_id"]
    assert titles[pid] == "Official rehabilitation guidance"
    labels = read_classification(project,pid)
    assert labels["current"]["design"] == ["guideline"]
    assert labels["current"]["format"] == ["society web document"]
    assert labels["evidence"]["design"][0]["path"] == ["record","document_types",0]
    assert inspect_enrichment(project,pid)["target"]["status"] == "missing_doi"
    assert read_study_page(project,run,only_review=False)["examined"] == 5
