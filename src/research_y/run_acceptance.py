"""Explicit researcher acceptance of a reconciled run with documented source limitations."""
from research_y import publication_identity as identity
from research_y import result_counts
from research_y.application_inspection import _read
from research_y.projects import _utc_now,_validated_project_connection
from research_y.reviewed_master import retained_union
from research_y.run_execution_board import _read_board

EVENT="run_scope_acceptance_v1"


def _state(db,project,run):
    board=_read_board(project,run,connection=db)
    reasons=[]
    if not board["approved_query_inventory_matches"]:
        reasons.append("Approved query inventory is unverified")
    if not board["primary_source_enumerations_reconciled"] or not board["available_primary_metadata_acquired"]:
        reasons.append("Mandatory source queries or metadata are incomplete")
    if any(q["stored_query_status"] in {"failed","cancelled"} or q["count_reconciliation"]!="equal"
           or q["metadata_records_missing"] for q in board["queries"]):
        reasons.append("At least one query has unresolved counts or missing metadata")
    if board["stored_run_status"] in {"failed","cancelled"}:
        reasons.append("The stored run failed or was cancelled")
    counts=result_counts._snapshot(db,project,run)
    if counts.totals["identifiers_without_metadata"] or counts.totals["unmaterialised_retrievals"]:
        reasons.append("Some source records lack metadata or publication identity")
    proof=retained_union(db,counts,supplementary_reconciliation=True)
    total=0 if counts.totals["source_record_sum"]==0 else None
    if proof is not None:
        total=proof["retained_unique_publications"]
    elif (counts.totals["metadata_source_records"]==counts.totals["source_record_sum"]==1
          and counts.totals["global_publication_identities"]==1 and not counts.totals["unmaterialised_retrievals"]
          and not counts.reviews["stale_decisions"] and not counts.reviews["decisions_conflicting_with_current_links"]
          and (not counts.totals["queryless_source_records"] or sum(board["supplementary_source_records"].values())==1)):
        total=1
    if total is None:
        reasons.append("The complete retained publication union has outstanding identity review")
    revision=identity._hash([board["revision"],counts.revision,total,reasons])
    receipt=None
    row=db.execute("SELECT event_id,details_json FROM audit_events WHERE event_type=? AND "
                   "json_extract(details_json,'$.run_id')=? ORDER BY event_id DESC LIMIT 1",(EVENT,run)).fetchone()
    if row:
        recorded=identity._event(db,row[0],EVENT)
        if recorded["revision"]==revision and not reasons:
            receipt=dict(recorded,event_id=row[0])
    return dict(run_id=run,revision=revision,eligible=not reasons,reasons=reasons,receipt=receipt,
                status="Verified Complete" if receipt else "Incomplete",global_unique_publications=total,
                supplementary=board["supplementary_source_records"],source_warnings={q["query_id"]:q["warnings"] for q in board["queries"]})


def read_acceptance(project,run):
    with _read(project) as db:
        return _state(db,project,run)


def accept_run(project,run,*,expected_revision,actor,limitations,confirmed):
    identity._text(actor,200)
    identity._text(limitations,4000)
    if confirmed is not True:
        raise ValueError("Confirm the reviewed scope and its limitations")
    with _validated_project_connection(project) as db:
        db.execute("BEGIN IMMEDIATE")
        state=_state(db,project,run)
        if not state["eligible"] or state["revision"]!=expected_revision:
            raise ValueError("Run evidence is incomplete or changed. Refresh the verification.")
        existing=state["receipt"]
        if existing and (existing["actor"],existing["limitations"])==(actor,limitations):
            return state
        event=dict(version=1,at_utc=_utc_now(),run_id=run,actor=actor,limitations=limitations,revision=expected_revision,
                   global_unique_publications=state["global_unique_publications"],source_warnings=state["source_warnings"])
        eid=identity._audit(db,EVENT,event)
        state.update(status="Verified Complete",receipt=dict(event,event_id=eid))
        return state
