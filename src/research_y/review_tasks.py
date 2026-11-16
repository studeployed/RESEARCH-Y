"""Local, cursor-paged follow-up for retained records and specialist sources."""
from research_y import conference_review, publication_identity as identity, society_sources, study_classification
from research_y.master_results import _abstract
from research_y.crossref_metadata import inspect_stored_enrichment
from research_y.projects import _utc_now, _validated_project_connection
from research_y.publication_match_evidence import project_source


REVIEWED = "source_evidence_reviewed_v1"
CITATION_FIELDS = ("title", "doi", "year", "journal", "authors", "pages")
PUBLICATION_CATEGORIES = ("missing_abstract", "metadata_conflict", "source_tags")
PAGE = 20


def _case(db, run, pid, category):
    snapshot = identity._snapshot(db, pid)
    if not any(s["run_id"] == run for s in snapshot.retrievals):
        return None
    sources = []
    for s in snapshot.retrievals:
        record = s["original_metadata"].get("record")
        if not isinstance(record,dict):
            record = {}
        fields = project_source(s)["fields"]
        sources.append(dict(id=s["retrieval_id"], source=s["source_name"], record_id=s["source_record_id"],
                            fields=fields, abstract_present=bool(_abstract(record).strip())))
    fields = CITATION_FIELDS if category == "metadata_conflict" else ("document_types", "source_document_types")
    conflicts = [f for f in fields if len({s["fields"][f]["normalised"] for s in sources
                                           if s["fields"][f]["status"] == "present"}) > 1]
    enrichment = None
    if category == "missing_abstract":
        if any(s["abstract_present"] for s in sources):
            return None
        enrichment = inspect_stored_enrichment(db, pid)["current"]
        if enrichment and enrichment["fields"].get("abstract"):
            return None
    elif not conflicts:
        if category != "source_tags" or not any(w.startswith("conflicting_") for w in
                                                 study_classification._proposals(snapshot)[2]):
            return None
    revision = identity._hash([run, pid, category, snapshot.revision, enrichment and enrichment["event_id"]])
    done = db.execute("SELECT event_id FROM audit_events WHERE event_type=? AND "
                      "json_extract(details_json,'$.revision')=? LIMIT 1", (REVIEWED, revision)).fetchone()
    title = next((s["fields"]["title"]["value"] for s in sources if s["fields"]["title"]["status"]=="present"),pid)
    return dict(id=pid, title=title, revision=revision, publication_revision=snapshot.revision,
                reviewed_event=done[0] if done else None, conflicts=conflicts, sources=sources,
                chosen={k:v["provenance"]["retrieval_id"] for k,v in snapshot.chosen_fields.items() if k in conflicts})


def read_page(project, run, category, after=None):
    identity._identifier(run)
    with _validated_project_connection(project) as db:
        db.execute("BEGIN")
        if not db.execute("SELECT 1 FROM search_runs WHERE run_id=?", (run,)).fetchone():
            raise ValueError("Select an existing run")
        rows = []
        if category in PUBLICATION_CATEGORIES:
            if after is not None:
                identity._identifier(after)
            ids = [r[0] for r in db.execute("SELECT DISTINCT l.publication_id FROM publication_retrievals l "
                   "JOIN source_retrievals r USING(retrieval_id) WHERE r.run_id=? AND l.publication_id>? "
                   "ORDER BY l.publication_id LIMIT ?", (run, after or "", PAGE+1))]
            for pid in ids[:PAGE]:
                case = _case(db, run, pid, category)
                if case and not case["reviewed_event"]:
                    rows.append({k:case[k] for k in ("id","title","revision","conflicts")})
        elif category == "conference":
            if after is not None:
                identity._positive(after)
            tasks = db.execute("SELECT a.event_id,a.details_json,r.source_record_id FROM audit_events a "
                "JOIN source_retrievals r ON r.retrieval_id=json_extract(a.details_json,'$.retrieval_id') "
                "WHERE r.run_id=? AND a.event_type=? AND a.event_id>? AND NOT EXISTS "
                "(SELECT 1 FROM audit_events d WHERE d.event_type=? AND json_extract(d.details_json,'$.task_id')=a.event_id) "
                "ORDER BY a.event_id LIMIT ?", (run,conference_review.OPEN,after or 0,conference_review.FINISH,PAGE+1)).fetchall()
            ids = [r[0] for r in tasks]
            for eid,raw,source_id in tasks[:PAGE]:
                task = identity._object(raw)
                rows.append(dict(id=eid, title=source_id, retrieval_id=task["retrieval_id"], locator=task["locator"],
                                 reason=task["reason"], document_sha256=task["document_sha256"]))
        elif category == "society":
            if after is not None:
                identity._identifier(after)
            ids = [r[0] for r in db.execute("SELECT organisation_id FROM organisations WHERE organisation_id>? "
                  "AND json_type(metadata_json,'$.directory_event_id')='integer' ORDER BY organisation_id LIMIT ?",
                  (after or "",PAGE+1))]
            for oid in ids[:PAGE]:
                org = society_sources._org(db, oid)
                visits = db.execute("SELECT event_id,details_json FROM audit_events WHERE event_type=? AND "
                    "json_extract(details_json,'$.details.society_id')=? ORDER BY event_id", (society_sources.VISIT_EVENT,oid))
                pages, outstanding = {}, []
                for eid, raw in visits:
                    v = identity._object(raw)["details"]
                    for page in v["pages"]:
                        pages[(page["url"],tuple(v["terms"]),v["method"])] = v["outcome"]
                    if v["outcome"] == "guidance_found" and not db.execute("SELECT 1 FROM audit_events WHERE event_type=? "
                            "AND json_extract(details_json,'$.visit_event_id')=?", (society_sources.GUIDANCE_EVENT,eid)).fetchone():
                        outstanding.append(eid)
                reasons = sorted({s for s in pages.values() if s in ("unavailable","review_needed")})
                if not pages:
                    reasons.append("unvisited")
                if outstanding:
                    reasons.append("guidance awaiting import")
                if reasons:
                    rows.append(dict(id=oid,title=org["name"],reasons=reasons,visits=outstanding))
        else:
            raise ValueError("Unknown review category")
        return dict(run=run,category=category,after=after,rows=rows,examined=min(PAGE,len(ids)),
                    next_after=ids[PAGE-1] if len(ids)>PAGE else None)


def open_case(project, run, pid, category, revision):
    with _validated_project_connection(project) as db:
        db.execute("BEGIN")
        return _current(db,run,pid,category,revision)


def _current(db, run, pid, category, revision):
    if category not in PUBLICATION_CATEGORIES:
        raise ValueError("Choose a publication evidence category")
    case = _case(db,run,pid,category)
    if not case or case["revision"] != revision:
        raise ValueError("Refresh the changed review evidence")
    return case


def confirm(project,run,pid,category,revision,actor,note):
    identity._text(actor,200)
    identity._text(note,2000)
    with _validated_project_connection(project) as db:
        db.execute("BEGIN IMMEDIATE")
        case = _current(db,run,pid,category,revision)
        return case["reviewed_event"] or identity._audit(db,REVIEWED,dict(at_utc=_utc_now(),run_id=run,
               publication_id=pid,category=category,revision=revision,actor=actor,note=note,
               publication_revision=case["publication_revision"],conflicts=case["conflicts"]))
