"""Local, allowlisted project diagnostics and researcher-readable audit receipts."""
import json
import os
from pathlib import Path
import tempfile

from research_y import __version__,publication_identity as identity
from research_y.application_inspection import _read
from research_y.export_files import Directory,filename

# Only these documented identifiers and small state fields enter diagnostic output.
SAFE_ID = {"run_id","query_id","publication_id","retrieval_id","review_id","export_id","strategy_version_id"}
STATES = {"pending","running","paused","incomplete","failed","cancelled","completed_verified",
          "confirmed_match","rejected_match","review_required","accepted","rejected","corrected","approved"}
KNOWN = {"project_created","schema_migrated","strategy_approved","strategy_admitted","source_query_planned",
         "research_setup_updated","publication_identity_v1","publication_field_v1","publication_candidate_decision_v1",
         "pre_run_review_v1","publication_pdf_attachment_v1","manual_bibliographic_import_v1","researcher_publication_note_v1",
         "study_classification_review_v1","conference_abstract_admission_v1","society_guidance_import_v1",
         "society_manual_search_v1","master_results_view_saved_v1","local_study_proposal_v1"}


def _receipt(row):
    eid,stamp,kind,raw=row
    info=identity._object(raw)
    safe={}
    for key in SAFE_ID:
        if key in info:
            try:
                safe[key]=identity._identifier(info[key])
            except ValueError:
                pass
    for key in ("status","decision","action"):
        value=info.get(key)
        if isinstance(value,str) and value in STATES:
            safe[key]=value
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
