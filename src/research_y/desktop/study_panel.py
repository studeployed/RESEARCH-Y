"""Review the selected publication's independent study labels."""
from research_y.study_classification import LABELS


def render_study_panel(ui, state, detail, act):
    ui.button("Review study classifications", on_click=lambda: act("study_inspect")).props("data-testid=study-inspect")
    view = state.get("study_view")
    if not view:
        return
    proposal = state.get("study_proposal")
    if state.get("local_assistant_enabled"):
        for source in detail["source_retrievals"]:
            ui.button("Ask local AI about " + source["source_name"] + " " + source["source_record_id"],
                      on_click=lambda rid=source["retrieval_id"]: act("study_suggest", rid))
    if view["warnings"]:
        ui.label("Review needed: " + ", ".join(v.replace("_", " ") for v in view["warnings"]))
    actor = ui.input("Reviewer", value=state["strategy_draft"]["approved_by"])
    reason = ui.input("Evidence for this decision")
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
        initial = suggested or current
        many = dimension == "design"
        choice = ui.select(sorted(allowed), multiple=many, value=initial if many else initial[0],
                           label="Reviewed " + dimension.replace("_", " "))
        ui.button("Confirm " + dimension.replace("_", " "), on_click=lambda key=dimension, box=choice,
                  multi=many, eid=proposal["event_id"] if suggested else None:
                  act("study_confirm", dict(dimension=key, labels=box.value if multi else [box.value],
                      revision=view["revision"], actor=actor.value, rationale=reason.value, event_id=eid)))
