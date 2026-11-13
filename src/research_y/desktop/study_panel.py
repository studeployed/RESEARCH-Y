"""Review the selected publication's independent study labels."""
from research_y.study_classification import LABELS


def review_edits(memory, view, proposal):
    key = (view["publication_id"], view["evidence_revision"], proposal["event_id"] if proposal else None)
    if memory.get("key") != key:
        memory.clear()
        memory.update(key=key, choices={}, receipts={})
    for dimension, decision in view["decisions"].items():
        if memory["receipts"].get(dimension) != decision["event_id"]:
            memory["choices"][dimension] = decision["labels"]
            memory["receipts"][dimension] = decision["event_id"]
    return memory["choices"]


def render_study_panel(ui, state, detail, act, memory=None):
    if detail is not None:
        ui.button("Review study classifications", on_click=lambda: act("study_inspect")).props("data-testid=study-inspect")
    view = state.get("study_view")
    if not view:
        return
    proposal = state.get("study_proposal")
    memory = {} if memory is None else memory
    edits = review_edits(memory, view, proposal)
    if detail and state.get("local_assistant_enabled"):
        for source in detail["source_retrievals"]:
            ui.button("Ask local AI about " + source["source_name"] + " " + source["source_record_id"],
                      on_click=lambda rid=source["retrieval_id"]: act("study_suggest", rid))
    if view["warnings"]:
        ui.label("Review needed: " + ", ".join(v.replace("_", " ") for v in view["warnings"]))
    actor = ui.input("Reviewer", value=memory.get("actor",state["strategy_draft"]["approved_by"]),
                     on_change=lambda e: memory.update(actor=e.value))
    reason = ui.input("Evidence for this decision", value=memory.get("reason",""),
                      on_change=lambda e: memory.update(reason=e.value))
    for dimension, allowed in LABELS.items():
        current = view["current"][dimension]
        ui.label(dimension.replace("_", " ").capitalize() + ": " + ", ".join(current)
                 + " (" + view["review_status"][dimension] + ")")
        for evidence in view["evidence"].get(dimension, []):
            ui.label(f'{evidence["value"]} · source {evidence["retrieval_id"]} · ' +
                     ".".join(map(str, evidence["path"])))
        suggested = proposal["proposals"].get(dimension) if proposal else None
        if suggested:
            ui.label(proposal["model"] + " suggests " + ", ".join(suggested))
        initial = edits.get(dimension, suggested or current)
        many = dimension == "design"
        choice = ui.select(sorted(allowed), multiple=many, value=initial if many else initial[0],
                           on_change=lambda e, key=dimension, multi=many:
                               edits.update({key:list(e.value or []) if multi else [e.value]}),
                           label="Reviewed " + dimension.replace("_", " "))
        ui.button("Confirm " + dimension.replace("_", " "), on_click=lambda key=dimension, box=choice,
                  multi=many, eid=proposal["event_id"] if suggested else None:
                  act("study_confirm", dict(dimension=key, labels=box.value if multi else [box.value],
                      revision=view["revision"], actor=actor.value, rationale=reason.value, event_id=eid)))


def render_study_queue(ui,state,act,memory):
    page=state.get("study_queue") or {}
    with ui.expansion("Study review queue and filters"):
        review=ui.checkbox("Only records requiring review",value=page.get("only_review",True))
        language=ui.checkbox("Hide explicitly non-English records",value=page.get("hide_non_english",False))
        species=ui.checkbox("Hide explicitly non-human-only records",value=page.get("hide_non_human_only",False))
        ui.button("Apply review filters",on_click=lambda:act("study_queue",dict(only_review=review.value,
            hide_non_english=language.value,hide_non_human_only=species.value,after=None)))
        if page:
            ui.label(f'Examined {page["examined"]} publications on this page; {page["hidden_by_filter"]} hidden by filters; {page["displayed"]} displayed.')
            for row in page["rows"]:
                ui.label(", ".join(row["dimensions"]["design"]) + " · " + ", ".join(row["warnings"]))
                ui.button("Review "+row["publication_id"],on_click=lambda r=row:act("study_queue_open",
                          {"publication_id":r["publication_id"],"revision":r["revision"]}))
            if page["next_after"]:
                ui.button("Next review page",on_click=lambda:act("study_queue",dict(only_review=page["only_review"],
                    hide_non_english=page["hide_non_english"],hide_non_human_only=page["hide_non_human_only"],after=page["next_after"])))
        if state.get("queued_study"):
            render_study_panel(ui,{**state,"study_view":state["queued_study"],"study_proposal":None},None,act,memory)
