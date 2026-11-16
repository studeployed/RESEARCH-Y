"""Version and local-clock evidence recorded by the process that stores a source receipt."""
from datetime import datetime
import re

from research_y import __version__

USER_AGENT = "RESEARCHY/0.1"
ESEARCH = "NCBI E-utilities ESearch"
EFETCH = "NCBI E-utilities EFetch"
STARTER = "Web of Science Starter v1 documents"
OPERATIONS = {
    "pubmed_count_pilot_requested_v1": ESEARCH, "pubmed_count_pilot_outcome_v1": ESEARCH,
    "pubmed_checkpoint_created": ESEARCH, "pubmed_checkpoint_page_committed": ESEARCH,
    "pubmed_efetch_metadata_committed": EFETCH,
    "wos_starter_pilot_requested_v1": STARTER, "wos_starter_pilot_outcome_v1": STARTER,
    "wos_request_reserved": STARTER, "wos_page_committed": STARTER, "wos_identity_verified": STARTER,
    "wos_count_revalidated": STARTER,
}


def receipt_version(kind, stamp):
    instant = datetime.fromisoformat(stamp)
    if instant.utcoffset() is None:
        raise ValueError("An offset is required for source receipt provenance")
    return dict(api=OPERATIONS[kind],application=__version__,client=USER_AGENT,
                local_time=instant.astimezone().isoformat())


def recorded_methods(db,run):
    """Group receipt kinds and versions, retaining first and last observation in audit order."""
    markers=",".join("?" for _ in OPERATIONS)
    rows=db.execute(f"SELECT q.query_id,a.event_type,a.event_id,a.occurred_at_utc,"
        "json_extract(a.details_json,'$.source_version.api'),json_extract(a.details_json,'$.source_version.application'),"
        "json_extract(a.details_json,'$.source_version.client'),json_extract(a.details_json,'$.source_version.local_time') "
        "FROM audit_events a JOIN source_queries q ON q.query_id=json_extract(a.details_json,'$.query_id') "
        f"WHERE a.event_type IN ({markers}) AND q.run_id=? ORDER BY a.event_id",(*OPERATIONS,run))
    inventory={}
    for qid,kind,eid,utc,api,application,client,local in rows:
        if api is None and application is None and client is None and local is None:
            continue
        # Only export recognised source labels, version strings and timestamps. Do not export arbitrary JSON.
        if (api!=OPERATIONS[kind] or not isinstance(application,str) or not re.fullmatch(r"[0-9][0-9A-Za-z.+-]{0,39}",application)
                or not isinstance(client,str) or not re.fullmatch(r"RESEARCHY/[0-9][0-9A-Za-z.+-]{0,39}",client)):
            raise ValueError("Invalid recorded source version")
        instant=datetime.fromisoformat(local)
        if instant.utcoffset() is None or instant!=datetime.fromisoformat(utc):
            raise ValueError("Source receipt local and UTC timestamps disagree")
        by_method=inventory.setdefault(qid,{})
        item=by_method.setdefault((kind,api,application,client),dict(event=kind,api=api,application=application,
            client=client,first_event=eid,first_local=local,first_utc=utc,receipts=0))
        item.update(last_event=eid,last_local=local,last_utc=utc,receipts=item["receipts"]+1)
    return {qid:list(values.values()) for qid,values in inventory.items()}
