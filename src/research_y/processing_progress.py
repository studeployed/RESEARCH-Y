"""Run-scoped progress for the execution monitor and bounded PubMed sessions."""
from contextlib import contextmanager
from uuid import uuid4

from research_y import publication_identity as identity
from research_y.projects import _utc_now, _validated_project_connection
from research_y.study_classification import LABELS

SESSION = "pubmed_processing_session_v1"


@contextmanager
def pubmed_session(project,query_id,stage):
    token=str(uuid4())
    def record(status,reason):
        with _validated_project_connection(project) as db:
            db.execute("BEGIN IMMEDIATE")
            identity._audit(db,SESSION,dict(version=1,at_utc=_utc_now(),session_id=token,query_id=query_id,
                                           stage=stage,status=status,reason=reason))
    record("started",None)
    try:
        result={}
        yield result
    except Exception:
        record("failed","Source session could not finish. Inspect the saved checkpoint.")
        raise
    else:
        record(result["status"],result["reason"])


def _pubmed_progress(db,qid):
    prior={}
    open_sessions=set()
    retries=0
    latest=None
    for stage,session,status,reason in db.execute(
            "SELECT json_extract(details_json,'$.stage'),json_extract(details_json,'$.session_id'),"
            "json_extract(details_json,'$.status'),json_extract(details_json,'$.reason') FROM audit_events "
            "WHERE event_type=? AND json_extract(details_json,'$.query_id')=? ORDER BY event_id",(SESSION,qid)):
        if status=="started":
            retries+=prior.get(stage)=="failed"
            open_sessions.add(session)
        else:
            open_sessions.discard(session)
        prior[stage]=status
        latest=reason
    batches,=db.execute("SELECT COUNT(*) FROM audit_events WHERE event_type='pubmed_efetch_metadata_committed' "
                        "AND json_extract(details_json,'$.query_id')=?",(qid,)).fetchone()
    return dict(retries=retries if prior else None,retry_unit="sessions restarted after a recorded failure",
                unknown_outcomes=len(open_sessions) if prior else None,latest_reason=latest,metadata_batches=batches,
                daily_remaining=None)


def source_progress(db,query):
    qid=query["query_id"]
    if query["source_name"]=="pubmed":
        return _pubmed_progress(db,qid)
    job=db.execute("SELECT reason_code,json_extract(quota_json,'$.daily_remaining') FROM wos_checkpoint_jobs "
                   "WHERE query_id=?",(qid,)).fetchone()
    pending={}
    retries=0
    for purpose,page,outcome in db.execute("SELECT purpose,page_number,outcome FROM wos_checkpoint_attempts "
                "WHERE query_id=? ORDER BY rowid",(qid,)):
        key=(purpose,page)
        retries+=pending.get(key) in ("error","abandoned")
        pending[key]=outcome
    unknown,=db.execute("SELECT COUNT(*) FROM wos_checkpoint_attempts WHERE query_id=? AND "
                        "(outcome='started' OR outcome='abandoned' AND sent IS NOT 0)",(qid,)).fetchone()
    return dict(retries=retries if job else None,retry_unit="repeat attempts after a failed or abandoned page request",
                unknown_outcomes=unknown if job else None,latest_reason=job[0] if job else None,metadata_batches=None,
                daily_remaining=job[1] if job else None)


def processing_stages(db,run,board):
    pubs="SELECT DISTINCT l.publication_id FROM publication_retrievals l JOIN source_retrievals r USING(retrieval_id) WHERE r.run_id=?"
    count,=db.execute("SELECT COUNT(*) FROM ("+pubs+")",(run,)).fetchone()
    decisions,=db.execute("SELECT COUNT(*) FROM (SELECT DISTINCT publication_id,dimension FROM classifications "
                          "WHERE publication_id IN ("+pubs+"))",(run,)).fetchone()
    enrich,=db.execute("SELECT COUNT(DISTINCT json_extract(details_json,'$.publication_id')) FROM audit_events "
                       "WHERE event_type='crossref_work_enrichment_v1' AND json_extract(details_json,'$.publication_id') "
                       "IN ("+pubs+")",(run,)).fetchone()
    exports,=db.execute("SELECT COUNT(*) FROM audit_events WHERE event_type GLOB 'workbook_export_v1:*' AND "
                        "json_extract(details_json,'$.action')='prepared' AND json_extract(details_json,'$.data.run_id')=?",
                        (run,)).fetchone()
    queries=board["queries"]
    def row(stage,unit,observed,total=None):
        return dict(stage=stage,unit=unit,observed=observed,total=total)
    return [
        row("Query validation","approved query inventory matched",int(board["approved_query_inventory_matches"]),1),
        row("Count retrieval","queries with reported counts",sum(q["reported_matches"] is not None for q in queries),len(queries)),
        row("Record pagination","saved identifier or record pages",sum(q["pages_committed"] or 0 for q in queries)),
        row("Metadata fetching","unique primary source records with metadata",sum(s["metadata_source_records"] for s in board["source_totals"])),
        row("Enrichment","publications with a stored Crossref outcome",enrich,count),
        row("Source reconciliation","queries with equal reported and retrieved counts",
            sum(q["count_reconciliation"]=="equal" for q in queries),len(queries)),
        row("Deduplication","reconciled primary publications",board["reconciled_primary_run_unique_publications"]),
        row("Classification","distinct researcher-reviewed publication dimensions",decisions,count*len(LABELS)),
        row("Export preparation","prepared run workbooks",exports),
    ]
