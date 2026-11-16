"""Local, allowlisted project diagnostics and researcher-readable audit receipts."""
import json
import os
from pathlib import Path
import tempfile

from research_y import __version__,publication_identity as identity
from research_y.application_inspection import _read
from research_y.export_files import Directory,filename
from research_y.study_classification import EVENT as CLASSIFICATION_EVENT, LABELS
from research_y.publication_results import DETAIL_FIELDS
from research_y.society_sources import VISIT_EVENT
from research_y.project_documents import EVENT as ATTACHMENT_EVENT

# Only these documented identifiers and small state fields enter diagnostic output.
SAFE_ID = {"run_id","query_id","publication_id","retrieval_id","review_id","export_id","strategy_version_id"}
STATES = {"pending","running","paused","incomplete","failed","cancelled","completed_verified",
          "confirmed_match","rejected_match","review_required","accepted","rejected","corrected","approved"}
KNOWN = {"project_created","schema_migrated","strategy_approved","strategy_admitted","source_query_planned",
         "research_setup_updated","publication_identity_v1","publication_field_v1","publication_candidate_decision_v1",
         "pre_run_review_v1","publication_pdf_attachment_v1","manual_bibliographic_import_v1","researcher_publication_note_v1",
         "study_classification_review_v1",CLASSIFICATION_EVENT,"conference_abstract_admission_v1","society_guidance_import_v1",
         "society_manual_search_v1","master_results_view_saved_v1","local_study_proposal_v1"}


def _copy_ids(safe, info, keys):
    for key in keys:
        if key in info:
            try:
                safe[key] = identity._identifier(info[key])
            except ValueError:
                pass


def _receipt(row):
    eid,stamp,kind,raw=row
    info=identity._object(raw)
    safe={}
    _copy_ids(safe, info, SAFE_ID)
    for key in ("status","decision","action"):
        value=info.get(key)
        if isinstance(value,str) and value in STATES:
            safe[key]=value
    if kind == identity.IDENTITY_EVENT:
        _copy_ids(safe, info, ("before", "after"))
        if info.get("action") in ("materialise", "associate", "reverse"):
            safe["action"] = info["action"]
        parent = info.get("reverses_event_id")
        if type(parent) is int and 0 < parent < eid:
            safe["reverses_event_id"] = parent
    if kind == CLASSIFICATION_EVENT:
        dimension, labels = info.get("dimension"), info.get("labels")
        if isinstance(dimension, str) and dimension in LABELS:
            safe["dimension"] = dimension
            if isinstance(labels, list) and all(isinstance(s,str) and s in LABELS[dimension] for s in labels):
                safe["labels"] = labels
        if info.get("status") in ("user-confirmed", "user-corrected"):
            safe["status"] = info["status"]
    if kind == identity.FIELD_EVENT and info.get("action") in ("select","clear"):
        safe["action"] = info["action"]
        field = info.get("field")
        if isinstance(field, str):
            if field in DETAIL_FIELDS:
                safe["field"] = field
            else:
                safe["custom_field_sha256"] = identity._hash(field)
        prior = info.get("previous_field_event_id")
        if type(prior) is int and 0 < prior < eid:
            safe["previous_field_event_id"] = prior
    if kind == ATTACHMENT_EVENT:
        _copy_ids(safe, info, ("document_id",))
    if kind == VISIT_EVENT and isinstance(info.get("details"), dict):
        details = info["details"]
        _copy_ids(safe, details, ("society_id",))
        for key, choices in (("method", ("manual_browse", "site_search")),
                             ("outcome", ("guidance_found", "none_seen", "unavailable", "review_needed"))):
            if details.get(key) in choices:
                safe[key] = details[key]
        if isinstance(details.get("pages"), list):
            safe["pages_examined"] = len(details["pages"])
    from datetime import datetime
    parsed=datetime.fromisoformat(stamp)
    return dict(event_id=eid,utc=parsed.isoformat(),event_type=kind if kind in KNOWN else "other_project_event",fields=safe)


def audit_page(project,after=0):
    if type(after) is not int or after<0:
        raise ValueError("Invalid audit page")
    with _read(project) as db:
        rows=db.execute("SELECT event_id,occurred_at_utc,event_type,details_json FROM audit_events WHERE event_id>? "
                        "ORDER BY event_id LIMIT 26",(after,)).fetchall()
        return dict(rows=[_receipt(row) for row in rows[:25]],next_after=rows[24][0] if len(rows)>25 else None)


def export_diagnostic(project,destination):
    dest=Path(destination)
    filename(dest.name)
    if dest.suffix.lower()!=".json":
        raise ValueError("Choose a JSON filename")
    with Directory(dest.parent) as folder, _read(project) as db:
        if dest.exists():
            raise FileExistsError(dest)
        totals={name:db.execute("SELECT count(*) FROM "+name).fetchone()[0] for name in
                ("search_runs","source_queries","source_retrievals","publications","query_retrievals","audit_events")}
        metadata=dict(format="researchy-diagnostic/1",project_id=str(project.identifier),software=__version__,
                      schema=db.execute("PRAGMA user_version").fetchone()[0],totals=totals)
        with tempfile.TemporaryDirectory(dir=dest.parent,prefix=".researchy-diagnostic-") as temp:
            stage=Path(temp)/"evidence.json"
            with stage.open("x",encoding="utf-8") as out:
                out.write(json.dumps(metadata,sort_keys=True)[:-1]+',"audit":[')
                first=True
                for row in db.execute("SELECT event_id,occurred_at_utc,event_type,details_json FROM audit_events ORDER BY event_id"):
                    if not first:
                        out.write(",")
                    json.dump(_receipt(row),out,sort_keys=True)
                    first=False
                out.write("]}\n")
                out.flush()
                os.fsync(out.fileno())
            os.link(stage,dest)
            folder.sync()
    return totals
