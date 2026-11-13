from contextlib import closing

import pytest

from research_y.desktop.actions import perform_action
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
        st=action("society_save",name="Example Society",official_url="https://society.example",actor="Reviewer")
        oid=st["society"]["society_id"]
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
        path=tmp_path/"source.xml"
        path.write_bytes(XML)
        st=flow.preview_native_conference(path,source_id=ids["111"],terms=["ECMO","right ventricle"],
                 landing_url=None,pdf_url="https://example.test/supp.pdf",pdf_pages={"a":8})["specialist"]
        prev=st["conference"]
        assert prev["total"]==2 and prev["unresolved_total"]==1 and "text" not in prev["abstracts"][0]
        locators=[r["locator"] for r in prev["abstracts"]]
        st=action("conference_detail",locator=locators[0],revision=prev["revision"])
        assert st["conference"]["detail"]["pdf_page"]==8
        with pytest.raises(ProjectFlowError):
            action("conference_admit",revision=prev["revision"],locators=locators,actor="Reviewer",retention_authorized=False)
        saved=action("conference_admit",revision=prev["revision"],locators=locators,actor="Reviewer",retention_authorized=True)
        assert saved["conference_receipt"]["selected_count"]==2
        page=flow.inspect_publications()["publication_page"]
        flow.inspect_publication_detail(publication_id=gid,revision=page["revision"])
        assert action("enrichment_offer")["enrichment"]["target"]["status"]=="missing_doi"
    assert read_classification(open_project(project.root),gid)["current"]["format"]==["society web document"]
