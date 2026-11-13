from contextlib import closing

import pytest

from research_y.desktop.actions import perform_action
from research_y.conference_review import read_tasks
from research_y.desktop.flow import RealProjectFlow, ProjectFlowError
from research_y.projects import open_project
from research_y.study_classification import read_classification
from test_conference_jats import XML
from test_reviewed_master import populated


def test_desktop_official_guidance_and_native_extraction_end_to_end(tmp_path):
    project,run,_,ids=populated(tmp_path)
    with closing(RealProjectFlow()) as flow:
        flow.open_native_folder(project.root)
        flow.select_run(run)
        def action(operation, **data):
            return perform_action(flow,"specialist",dict(action=operation,data=data))["specialist"]
        options=action("directory",terms=["ECMO"])
        assert options["suggestions"][0]["name"]=="Extracorporeal Life Support Organization"
        assert flow.official_society_url("suggestion",options["suggestions"][0]["name"]) == options["suggestions"][0]["official_url"]
        with pytest.raises(ProjectFlowError):
            flow.official_society_url("suggestion","unlisted")
        st=action("society_save",name="Example Society",official_url="https://society.example",actor="Reviewer")
        oid=st["society"]["society_id"]
        assert flow.official_society_url("selected",oid) == "https://society.example"
        st=action("society_visit",url="https://society.example/guidance",examined_on="2026-11-13",
                  method="manual_browse",terms=["rehabilitation"],outcome="guidance_found",
                  limitations="One official library",actor="Reviewer")
        eid=st["visits"][-1]["event_id"]
        st=action("society_guidance",visit_id=eid,record={"title":"Example guidance",
                  "document_types":["clinical practice guideline"],"landing_url":"https://society.example/guidance"},
                  roles={"issuing":[oid]},actor="Reviewer")
        gid=st["guidance_receipt"]["publication_id"]
        repeated=action("society_guidance",visit_id=eid,record={"title":"Example guidance",
                  "document_types":["clinical practice guideline"],"landing_url":"https://society.example/guidance"},
                  roles={"issuing":[oid]},actor="Reviewer")
        assert repeated["guidance_receipt"]["publication_id"]==gid
        page=flow.inspect_publications()["publication_page"]
        for row in page["rows"]:
            detail=flow.inspect_publication_detail(publication_id=row["publication_id"],revision=page["revision"])["publication_detail"]
            if any(s["retrieval_id"]==ids["111"] for s in detail["source_retrievals"]):
                break
        assert any(s["retrieval_id"]==ids["111"] for s in detail["source_retrievals"])
        path=tmp_path/"résumé [1].xml"
        path.write_bytes(XML)
        st=flow.preview_native_conference(path,source_id=ids["111"],terms=["ECMO","right ventricle"],
                 landing_url=None,pdf_url="https://example.test/supp.pdf",pdf_pages={"a":8})["specialist"]
        prev=st["conference"]
        assert prev["total"]==2 and prev["unresolved_total"]==1 and "text" not in prev["abstracts"][0]
        locators=[r["locator"] for r in prev["abstracts"]]
        entry = dict(retrieval_id=ids["111"], revision=prev["revision"],
                     locator=prev["unresolved"][0]["locator"], actor="Reviewer")
        for _ in range(2):
            tasks = action("conference_queue_block",**entry)["conference_tasks"]["tasks"]
            assert len(tasks) == 1 and tasks[0]["decision"] is None
        assert tasks[0]["document_sha256"] and tasks[0]["original_current"]
        action("conference_finish_task",retrieval_id=ids["111"],task_id=tasks[0]["task_id"],
               actor="Reviewer",disposition="not_an_individual_abstract",note="Collection heading verified")
        st=action("conference_detail",locator=locators[0],revision=prev["revision"])
        assert st["conference"]["detail"]["pdf_page"]==8
        with pytest.raises(ProjectFlowError):
            action("conference_admit",revision=prev["revision"],locators=locators,actor="Reviewer",retention_authorized=False)
        saved=action("conference_admit",revision=prev["revision"],locators=locators,actor="Reviewer",retention_authorized=True)
        assert saved["conference_receipt"]["selected_count"]==2
        page=flow.inspect_publications()["publication_page"]
        queue = flow.inspect_study_queue(False,False,False)["study_queue"]
        other = next(row for row in queue["rows"] if row["publication_id"] != gid)
        flow.open_queued_study(other["publication_id"],other["revision"])
        flow.inspect_publication_detail(publication_id=gid,revision=page["revision"])
        target = action("enrichment_offer")["enrichment"]["target"]
        assert target["publication_id"] == gid and target["status"] == "missing_doi"
    assert read_classification(open_project(project.root),gid)["current"]["format"]==["society web document"]
    saved = read_tasks(open_project(project.root), ids["111"])["tasks"]
    assert len(saved) == 1 and saved[0]["decision"]["note"] == "Collection heading verified"
