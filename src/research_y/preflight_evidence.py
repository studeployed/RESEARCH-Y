"""Read pilot observations and researcher checks against an exact frozen search plan."""
from datetime import date, datetime, timezone

from research_y import publication_identity as identity, pubmed_pilot, wos_starter_pilot
from research_y.projects import _utc_now, _validated_project_connection


KNOWN_ITEM = "known_item_search_check_v1"


def pilot_observations(db, plan):
    from research_y.pubmed_metadata import MAX_BATCH_IDS
    from research_y.pubmed_source_gui import PUBMED_PAGE_SIZE
    from research_y.wos_starter import MAX_PAGE_SIZE
    latest = {}
    for source in plan["sources"]:
        name=source["source_name"]
        module=pubmed_pilot if name=="pubmed" else wos_starter_pilot
        for query in source["queries"]:
            qid=query["query_id"]
            row=db.execute("SELECT json_extract(details_json,'$.pilot_id') FROM audit_events WHERE event_type=? "
                    "AND json_extract(details_json,'$.run_id')=? AND json_extract(details_json,'$.query_id')=? "
                    "ORDER BY event_id DESC LIMIT 1",(module.REQUEST_EVENT,plan["run_id"],qid)).fetchone()
            if not row:
                continue
            record=module._view(*module._events(db,row[0]))
            if (record["plan_sha256"]!=plan["plan_sha256"] or record["exact_query"]!=query["exact_query"]
                    or record["query_id"]!=qid or record["run_id"]!=plan["run_id"]):
                raise ValueError("Pilot belongs to a different frozen plan")
            count=record["reported_matches"]
            pages=batches=None
            if count is not None and record["status"] in ("count_reported_not_retrieved","count_reported_sample_not_retained",
                                                          "quota_exhausted_after_probe","entitlement_unverified"):
                size=PUBMED_PAGE_SIZE if name=="pubmed" else MAX_PAGE_SIZE
                pages=(count+size-1)//size
                if name=="pubmed":
                    batches=(count+MAX_BATCH_IDS-1)//MAX_BATCH_IDS
            latest[qid]=dict(source=name,status=record["status"],reported_matches=count,pilot_id=row[0],
                             observed_utc=record["completed_at_utc"] or record["requested_at_utc"],
                             estimated_result_pages=pages,estimated_metadata_batches=batches)
    return latest


def known_checks(db,run,plan_sha):
    return [dict(identity._object(raw),event_id=eid) for eid,raw in db.execute("SELECT event_id,details_json "
        "FROM audit_events WHERE event_type=? AND json_extract(details_json,'$.run_id')=? AND "
        "json_extract(details_json,'$.plan_sha256')=? ORDER BY event_id",(KNOWN_ITEM,run,plan_sha))]


def record_known_check(project,run,plan_sha,*,query_id,identifier,outcome,checked_on,actor,basis):
    from research_y.preflight_review import _inspect
    identity._identifier(query_id)
    for text,limit in ((identifier,150),(actor,200),(basis,2000)):
        identity._text(text,limit)
    when=date.fromisoformat(checked_on)
    if when.isoformat()!=checked_on or when>datetime.now(timezone.utc).date() or outcome not in ("found","not_found","inconclusive"):
        raise ValueError("Choose an observed outcome and the date the check was performed")
    with _validated_project_connection(project) as db:
        db.execute("BEGIN IMMEDIATE")
        plan=_inspect(db,run)
        query=next((q for s in plan["sources"] for q in s["queries"] if q["query_id"]==query_id),None)
        if plan["plan_sha256"]!=plan_sha or not query:
            raise ValueError("Reopen the frozen strategy before recording the check")
        item=dict(run_id=run,plan_sha256=plan_sha,query_id=query_id,source=query["source"],identifier=identifier,
                  outcome=outcome,checked_on=checked_on,actor=actor,basis=basis,method="researcher_reported_source_check")
        prior=db.execute("SELECT event_id,details_json FROM audit_events WHERE event_type=? AND "
            "json_extract(details_json,'$.query_id')=? AND json_extract(details_json,'$.identifier')=? ORDER BY event_id DESC LIMIT 1",
            (KNOWN_ITEM,query_id,identifier)).fetchone()
        if prior and all(identity._object(prior[1]).get(k)==v for k,v in item.items()):
            return prior[0]
        return identity._audit(db,KNOWN_ITEM,dict(item,at_utc=_utc_now(),previous_event_id=prior[0] if prior else None))
