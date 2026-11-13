"""Inspect an existing publication's DOI and attach an attributed Crossref work response."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from urllib.parse import quote

from research_y import publication_identity as identity
from research_y.projects import _utc_now, _validated_project_connection
from research_y.publication_match_evidence import _doi, project_source

EVENT = "crossref_work_enrichment_v1"
MAX_RESPONSE = 2 * 1024 * 1024
FIELDS = ("title", "author", "container-title", "published", "volume", "issue", "page",
          "article-number", "publisher", "type", "language", "abstract", "license", "link")


def _target(db, pub_id):
    snapshot = identity._snapshot(db, identity._identifier(pub_id))
    if not snapshot.active:
        raise ValueError("Publication has no retained source records")
    dois = set()
    evidence = []
    ambiguous = False
    for source in snapshot.retrievals:
        candidate = project_source(source)["fields"]["doi"]
        if candidate["status"] == "present":
            dois.add(candidate["normalised"])
            evidence.append(dict(retrieval_id=source["retrieval_id"], path=candidate["path"],
                                 source_sha256=source["source_sha256"]))
        elif candidate["status"] in ("malformed", "multiple_values"):
            ambiguous = True
    doi = next(iter(dois)) if len(dois) == 1 and not ambiguous else None
    return dict(publication_id=pub_id, revision=snapshot.revision, doi=doi, evidence=evidence,
                status="ready" if doi else "ambiguous_doi" if dois or ambiguous else "missing_doi",
                request_url="https://api.crossref.org/works/" + quote(doi, safe="") if doi else None)


def _history(db, pub_id):
    ids = db.execute("SELECT event_id FROM audit_events WHERE event_type=? "
                     "AND json_extract(details_json,'$.publication_id')=? ORDER BY event_id", (EVENT, pub_id))
    return [dict(identity._event(db, i, EVENT), event_id=i) for (i,) in ids]


def inspect_enrichment(project, publication_id):
    with _validated_project_connection(project) as db:
        db.execute("BEGIN")
        target = _target(db, publication_id)
        history = _history(db, publication_id)
        current = next((event for event in reversed(history) if event["revision"] == target["revision"]
                        and event["doi"] == target["doi"]), None)
        return dict(target=target, current=current, prior_receipts=[e["event_id"] for e in history])


def record_work_response(project, publication_id, *, expected_revision, requested_doi, status_code, body,
                         retrieved_at_utc, actor, confirmed):
    """Apply a permitted work response to a selected original. No new source, publication or query is created."""
    identity._text(actor, 200)
    if confirmed is not True or type(status_code) is not int or not 100 <= status_code <= 599:
        raise ValueError("Explicit confirmation and an HTTP response status required")
    if type(body) is not bytes or len(body) > MAX_RESPONSE:
        raise ValueError("Work response exceeds supported size")
    observed = datetime.fromisoformat(retrieved_at_utc)
    if observed.tzinfo is None:
        raise ValueError("Work response needs a timezone-aware retrieval timestamp")
    observed = observed.astimezone(timezone.utc).isoformat()
    digest = sha256(body).hexdigest()
    fields = {}
    if status_code == 200:
        response = identity._object(body.decode("utf-8"))
        msg = response.get("message")
        if (response.get("status") != "ok" or response.get("message-type") != "work" or not isinstance(msg, dict)
                or not requested_doi or _doi(msg.get("DOI")) != requested_doi):
            raise ValueError("Work response DOI does not match the selected publication")
        fields = {field: msg[field] for field in FIELDS if field in msg and msg[field] not in ("", None, [], {})}
        outcome = "metadata_available" if fields else "metadata_gap"
    else:
        outcome = "not_found" if status_code == 404 else "unavailable"
    with _validated_project_connection(project) as db:
        db.execute("BEGIN IMMEDIATE")
        target = _target(db, publication_id)
        if expected_revision != target["revision"] or not target["doi"] or requested_doi != target["doi"]:
            raise identity.StalePublicationError("Review the current DOI and linked source evidence")
        request = identity._hash([target["revision"], requested_doi, status_code, digest, observed, actor])
        history = _history(db, publication_id)
        prior = next((e for e in history if e.get("request_sha256") == request), None)
        if prior:
            return prior
        event = dict(version=1, at_utc=_utc_now(), publication_id=publication_id, revision=expected_revision,
                     doi=requested_doi, source_url=target["request_url"], source_evidence=target["evidence"],
                     retrieved_at_utc=observed, actor=actor, http_status=status_code, outcome=outcome,
                     response_sha256=digest, fields=fields, gaps=[f for f in FIELDS if f not in fields],
                     rights_review_required=True, request_sha256=request)
        event_id = identity._audit(db, EVENT, event)
        return dict(event, event_id=event_id)
