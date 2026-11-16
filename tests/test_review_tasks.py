from contextlib import closing
from uuid import uuid4

import pytest

from research_y import conference_review, review_tasks
from research_y.desktop.actions import perform_action
from research_y.desktop.flow import ProjectFlowError, RealProjectFlow
from research_y.projects import open_project, _validated_project_connection
from research_y.society_sources import record_society_visit, import_guidance
from test_reviewed_master import populated, decide
from test_society_sources import register, visit_args


def test_queue_reviews_source_conflict_and_preserves_current_selection_and_history(tmp_path):
    project,run,_,ids=populated(tmp_path)
    from research_y.bibliographic_import import admit_records
    entry=admit_records(project,run,"Local citation",manual=dict(title="Corrected citation",type="CONF"),
                        indices=[0],revision=None,actor="Reader",confirmed=True)["admitted"][0]
    decide(project,ids["111"],entry["retrieval_id"],"confirmed_match")
    other=admit_records(project,run,"Catalogue",manual=dict(title="Alternate citation",type="JOUR"),
                        indices=[0],revision=None,actor="Reader",confirmed=True)["admitted"][0]
    decide(project,ids["111"],other["retrieval_id"],"confirmed_match")
    with closing(RealProjectFlow()) as flow:
        flow.open_native_folder(project.root)
        flow.select_run(run)
        def act(operation,**data):
            return perform_action(flow,"review_tasks",dict(operation=operation,data=data))["review_tasks"]
        page=act("page",category="metadata_conflict")
        row,=page["rows"]
        selected={k:row[k] for k in ("id","revision")}
        with pytest.raises(ProjectFlowError):
            act("confirm",**selected,actor="R",note="Premature")
        case=act("open",**selected)["detail"]
        field=case["conflicts"][0]
        source=next(s for s in case["sources"] if s["fields"][field]["status"]=="present")
        updated=act("field",**selected,source=source["id"],field=field,actor="Reader",note="Compared the citations")
        with pytest.raises(ProjectFlowError):
            act("open",**selected)
        updated_row,=updated["rows"]
        selected={k:updated_row[k] for k in ("id","revision")}
        case=act("open",**selected)["detail"]
        assert case["chosen"][field]==source["id"]
        act("classify",**selected,decision=dict(dimension="language",labels=["English"],actor="Reader",
            rationale="Checked the original",revision=case["classification"]["revision"]))
        assert act("confirm",**selected,actor="Reader",note="Compared both originals")["rows"]==[]
        tags=act("page",category="source_tags")
        assert tags["rows"][0]["id"] == row["id"]
    reopened=open_project(project.root)
    with _validated_project_connection(reopened) as db:
        assert db.execute("SELECT json_extract(details_json,'$.note') FROM audit_events WHERE event_type=?",
                          (review_tasks.REVIEWED,)).fetchone()[0]=="Compared both originals"
    assert not review_tasks.read_page(reopened,run,"metadata_conflict")["rows"]


def test_follow_up_reopens_precise_society_and_conference_tasks(tmp_path):
    project,run,_,ids=populated(tmp_path)
    org=register(project)
    with closing(RealProjectFlow()) as flow:
        flow.open_native_folder(project.root)
        flow.select_run(run)
        def act(operation,**data):
            return perform_action(flow,"review_tasks",dict(operation=operation,data=data))
        def societies():
            return act("page",category="society")["review_tasks"]["rows"]
        assert societies()[0]["reasons"]==["unvisited"]
        assert act("open",id=org["society_id"])["specialist"]["society"]["name"]==org["name"]
        request=visit_args(org)
        record_society_visit(project,**dict(request,outcome="unavailable"))
        assert societies()[0]["reasons"]==["unavailable"]
        visit=record_society_visit(project,**dict(request,request_id=str(uuid4())))
        assert societies()[0]["visits"]==[visit["event_id"]]
        import_guidance(project,request_id=str(uuid4()),run_id=run,visit_event_id=visit["event_id"],
            record=dict(title="Official guideline",document_types=["guideline"],landing_url=request["pages"][0]["url"]),
            roles={"issuing":[org["society_id"]]},actor="Reader",confirmed=True)
        assert not societies()
        # Society guidance has no abstract. The acknowledgement survives reopening.
        missing=act("page",category="missing_abstract")["review_tasks"]["rows"]
        row=next(r for r in missing if r["title"]=="Official guideline")
        selected={k:row[k] for k in ("id","revision")}
        act("open",**selected)
        act("confirm",**selected,actor="Reader",note="Official document supplies no abstract")
        task=conference_review.queue_block(project,ids["111"],dict(source_sha256="a"*64,
             unresolved=[dict(locator="section-2",reason="Collection heading")]),"section-2","Reader")
        work=act("page",category="conference")["review_tasks"]["rows"]
        assert work[0]["id"]==task and work[0]["locator"]=="section-2"
        with pytest.raises(ProjectFlowError):
            act("finish",id=task+1,actor="Reader",note="Wrong task",disposition="reviewed_in_source")
        assert not act("finish",id=task,actor="Reader",note="Checked collection heading",
                       disposition="not_an_individual_abstract")["review_tasks"]["rows"]
    reopened=open_project(project.root)
    assert row["id"] not in [r["id"] for r in review_tasks.read_page(reopened,run,"missing_abstract")["rows"]]
    assert conference_review.read_tasks(reopened,ids["111"])["tasks"][0]["decision"]["note"]=="Checked collection heading"


def test_export_uses_reviewed_authors_and_pages_and_keeps_original_alternatives(tmp_path):
    import json
    from openpyxl import load_workbook
    from research_y import bibliographic_import, master_results, master_exports
    project,run,_,ids=populated(tmp_path)
    originals=[]
    for name,start,end in [("River, Alex",12,16),("Hill, Lee",22,26)]:
        payload=f"TY  - JOUR\nTI  - Citation\nAU  - {name}\nSP  - {start}\nEP  - {end}\nER  - \n".encode()
        source=bibliographic_import.admit_records(project,run,"Local",payload=payload,indices=[0],
               revision=bibliographic_import.preview_ris(payload)["sha256"],actor="Reader",confirmed=True)["admitted"][0]
        decide(project,ids["111"],source["retrieval_id"],"confirmed_match")
        originals.append(source["retrieval_id"])
    with closing(RealProjectFlow()) as flow:
        flow.open_native_folder(project.root)
        flow.select_run(run)
        for field in ("authors","pages"):
            row,=flow.review_task_action("page",dict(category="metadata_conflict"))["review_tasks"]["rows"]
            selected=dict(id=row["id"],revision=row["revision"])
            flow.review_task_action("open",selected)
            flow.review_task_action("field",dict(**selected,field=field,source=originals[1],actor="Reader",note="Compared originals"))
    with closing(master_results.MasterResults.capture(project,run)) as master:
        for suffix in ("ris","xlsx"):
            master_exports.export_results(project,master,tmp_path/("Verified."+suffix),master_results.DEFAULT,scope="entire")
    ris=(tmp_path/"Verified.ris").read_text(encoding="utf-8")
    assert "AU  - Hill, Lee" in ris and "AU  - River, Alex" not in ris and "SP  - 22\nEP  - 26" in ris
    with closing(load_workbook(tmp_path/"Verified.xlsx",read_only=True)) as book:
        values=[v for values in book["Master Results"].values for v in values if isinstance(v,str)]
        choices=[json.loads(v) for v in values if v.startswith("{") and '"retrieval_id"' in v]
        assert {"retrieval_id":originals[1],"value":["Hill, Lee"]} in choices
        assert {"retrieval_id":originals[1],"value":"22-26"} in choices
        assert "River, Alex" in str(list(book["Source Records"].values))
