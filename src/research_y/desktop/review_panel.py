"""Researcher follow-up across classification, identity and specialist evidence."""
from research_y.desktop.study_panel import render_study_panel


def render_review_tasks(ui,state,act,memory):
    page=state.get("review_tasks")
    categories={"missing_abstract":"Missing abstracts","metadata_conflict":"Conflicting citation metadata",
                "source_tags":"Apparently conflicting source tags","conference":"Incomplete conference extraction",
                "society":"Unresolved society source tasks (project-wide)"}
    def send(operation,**data):
        return act("review_tasks",dict(operation=operation,data=data))
    with ui.expansion("Review queues",value=bool(page)):
        ui.button("Open potential duplicates",on_click=lambda:act("candidate_queue_refresh"))
        ui.button("Open uncertain classifications",on_click=lambda:act("study_queue",dict(after=None,
                  only_review=True,hide_non_english=False,hide_non_human_only=False)))
        category=ui.select(categories,label="Follow-up category",value=page["category"] if page else "missing_abstract")
        ui.button("Read follow-up tasks",on_click=lambda:send("page",category=category.value))
        if not page:
            return
        kind=page["category"]
        ui.label(f'{categories[kind]} · {len(page["rows"])} outstanding on this page · {page["examined"]} examined')
        for row in page["rows"]:
            if kind == "conference":
                ui.label(f'{row["title"]} · {row["locator"]} · {row["reason"]} · document {row["document_sha256"]}')
                actor=ui.input("Reviewer", value=state.get('researcher_name', ''))
                note=ui.input("What did you verify in the source?")
                choice=ui.select(["reviewed_in_source","not_an_individual_abstract"],label="Outcome")
                ui.button("Record extraction review",on_click=lambda r=row,a=actor,n=note,c=choice:
                          send("finish",id=r["id"],actor=a.value,note=n.value,disposition=c.value))
            elif kind == "society":
                ui.label(", ".join(row["reasons"]))
                ui.button("Review "+row["title"],on_click=lambda r=row:send("open",id=r["id"]))
            else:
                ui.button("Inspect "+str(row["title"]),on_click=lambda r=row:send("open",id=r["id"],revision=r["revision"]))
        if page["next_after"] is not None:
            ui.button("Next follow-up page",on_click=lambda:send("page",category=kind,after=page["next_after"]))
        case=page.get("detail")
        if not case:
            return
        selected=dict(id=case["id"],revision=case["revision"])
        ui.label(str(case["title"]))
        actor=ui.input("Researcher reviewing evidence", value=state.get('researcher_name', ''))
        note=ui.input("Evidence and reason for this decision")
        for source in case["sources"]:
            ui.label(source["source"]+" "+source["record_id"]+" · "+
                     ("abstract supplied" if source["abstract_present"] else "abstract unavailable"))
            for field in case["conflicts"]:
                evidence=source["fields"][field]
                chosen=" · researcher-selected" if case["chosen"].get(field)==source["id"] else ""
                ui.label(field+" · "+str(evidence["value"])+chosen)
                if kind=="metadata_conflict" and evidence["status"]=="present":
                    ui.button("Use this "+field,on_click=lambda s=source,f=field:
                              send("field",**selected,source=s["id"],field=f,actor=actor.value,note=note.value))
        def classify(action,value):
            return send("classify",**selected,decision=value)
        with ui.expansion("Review or edit study labels"):
            render_study_panel(ui,{**state,"study_view":case["classification"],"study_proposal":None},None,classify,memory)
        ui.button("Confirm evidence reviewed",on_click=lambda:send("confirm",**selected,actor=actor.value,note=note.value))
