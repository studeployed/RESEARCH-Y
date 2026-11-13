from contextlib import closing
import sqlite3
from uuid import uuid4

import pytest

from research_y import publication_identity as identity
from research_y.conference_project import admit_extraction, preview_extraction
from research_y.projects import open_project
from test_conference_jats import XML
from test_publication_identity import store, db_rows


def test_confirmed_abstracts_remain_distinct_after_reopen_with_original_container(store):
    project, ids = store
    original = db_rows(project, "source_retrievals")
    primary = db_rows(project, "query_retrievals"), db_rows(project, "source_queries")
    options = dict(terms=["right ventricle", "ECMO"], landing_url="https://example.test/supp",
                   pdf_url="https://example.test/supp.pdf", pdf_pages={"a":8})
    preview = preview_extraction(project, ids[0], XML, **options)
    locators = [a["locator"] for a in preview["extraction"]["abstracts"]]
    args = dict(locators=locators, expected_revision=preview["revision"], actor="Reviewer",
                confirmed=True, retention_authorized=True, **options)
    for key in ("confirmed","retention_authorized"):
        with pytest.raises(ValueError):
            admit_extraction(project, ids[0], XML, **{**args,key:False})
    assert not db_rows(project, "containers")
    result = admit_extraction(project, ids[0], XML, **args)
    reopened = open_project(project.root)
    assert admit_extraction(reopened, ids[0], XML, **args) == result
    assert result["selected_count"] == result["extracted_count"] == 2
    a, b = [identity.read_publication(reopened, row["publication_id"]) for row in result["admitted"]]
    assert a.publication_id != b.publication_id
    ar, br = [v.retrievals[0]["original_metadata"] for v in (a,b)]
    assert ar["record"]["title"] == br["record"]["title"]
    assert ar["record"]["pdf_page"] == 8 and ar["record"]["printed_first_page"] == "S3"
    assert ar["original_retrieval_id"] == br["original_retrieval_id"] == ids[0]
    assert ar["record"]["individual_dois"] == [] and br["record"]["individual_dois"] == ["10.1234/report"]
    assert len(db_rows(project, "publication_containers")) == 2
    assert set(original) <= set(db_rows(project, "source_retrievals"))
    assert (db_rows(project,"query_retrievals"),db_rows(project,"source_queries")) == primary
    with pytest.raises(identity.StalePublicationError):
        admit_extraction(project, ids[0], XML.replace(b"Rehabilitation.", b"Revised."), **args)


def test_second_abstract_failure_rolls_back_whole_selected_batch(store):
    project, ids = store
    view = preview_extraction(project, ids[0], XML)
    locators = [a["locator"] for a in view["extraction"]["abstracts"]]
    tables = ("source_retrievals","containers","publications","publication_containers","audit_events")
    before = [db_rows(project,t) for t in tables]
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute("CREATE TRIGGER fail_second BEFORE INSERT ON publication_containers "
                   "WHEN (SELECT COUNT(*) FROM publication_containers)>0 BEGIN SELECT RAISE(ABORT,'fixture'); END")
    with pytest.raises(sqlite3.IntegrityError):
        admit_extraction(project,ids[0],XML,locators=locators,expected_revision=view["revision"],
                         actor="Reviewer", confirmed=True, retention_authorized=True)
    assert [db_rows(project,t) for t in tables] == before


def test_supplementary_abstracts_preserve_reconciled_primary_counts_and_reviewed_workbook(tmp_path):
    from research_y.run_execution_board import read_run_execution_board
    from research_y.workbook_exports import prepare_workbook_export
    from test_reviewed_master import populated, decide
    project, run, _, ids = populated(tmp_path)
    decide(project,ids["111"],ids["WOS:000000001"],"confirmed_match")
    decide(project,ids["111"],ids["222"],"rejected_match")
    before = read_run_execution_board(project,run)
    assert before["reconciled_primary_run_unique_publications"] == 2
    view = preview_extraction(project,ids["111"],XML)
    admit_extraction(project,ids["111"],XML,locators=[a["locator"] for a in view["extraction"]["abstracts"]],
                     expected_revision=view["revision"],actor="Reviewer",confirmed=True,retention_authorized=True)
    after = read_run_execution_board(open_project(project.root),run)
    assert after["source_count_revision"] == before["source_count_revision"]
    assert after["reconciled_primary_run_unique_publications"] == 2
    assert after["supplementary_source_records"] == {"conference_jats":2}
    assert after["reviewed_retained_master"] == before["reviewed_retained_master"]
    report = prepare_workbook_export(project,run,"Reviewed.xlsx",export_id=str(uuid4()),
                                     reviewed_revision=after["source_count_revision"])
    assert report.export_id
