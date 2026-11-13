"""Project society directory and researcher-recorded official-site review tasks."""
from __future__ import annotations

from datetime import date
from urllib.parse import urlsplit
from uuid import uuid4

from research_y import publication_identity as identity
from research_y.projects import _utc_now, _validated_project_connection

DIRECTORY_EVENT = "society_directory_v1"
VISIT_EVENT = "society_manual_search_v1"
GUIDANCE_EVENT = "society_guidance_import_v1"
GUIDANCE_TYPES = {"clinical practice guideline", "consensus statement", "position statement",
                  "practice recommendation", "guideline"}


def web_url(value):
    identity._text(value, 4096)
    if any(c.isspace() or ord(c) == 127 or c == "\\" for c in value):
        raise ValueError("Expected a web URL")
    parts = urlsplit(value)
    if parts.scheme not in {"https", "http"} or not parts.hostname or parts.username is not None:
        raise ValueError("Expected an HTTP or HTTPS URL without credentials")
    _ = parts.port
    return value


def _org(db, org_id):
    row = db.execute("SELECT name,metadata_json FROM organisations WHERE organisation_id=?",
                     (identity._identifier(org_id),)).fetchone()
    if row is None:
        raise KeyError("Unknown society")
    metadata = identity._object(row[1])
    event_id = metadata.get("directory_event_id")
    event = identity._event(db, event_id, DIRECTORY_EVENT)
    if (event.get("society_id"), event.get("name"), event.get("official_url")) != (
        org_id, row[0], metadata.get("official_url")
    ):
        raise identity.PublicationIntegrityError("Directory entry disagrees with its audit")
    return dict(society_id=org_id, name=row[0], official_url=event["official_url"], revision=event_id)


def list_societies(project):
    with _validated_project_connection(project) as db:
        db.execute("BEGIN")
        ids = db.execute("SELECT organisation_id FROM organisations "
                         "WHERE json_type(metadata_json,'$.directory_event_id')='integer' ORDER BY name,organisation_id")
        return [_org(db, org_id) for (org_id,) in ids]


def save_society(project, *, society_id, name, official_url, actor, expected_revision=None, confirmed):
    """Caller-generated stable ID allows creation retries without merging similarly named societies."""
    identity._identifier(society_id)
    identity._text(name, 500)
    identity._text(actor, 200)
    web_url(official_url)
    if confirmed is not True or expected_revision is not None and type(expected_revision) is not int:
        raise ValueError("Explicit confirmation and a valid revision are required")
    request = identity._hash([society_id, name, official_url, actor, expected_revision])
    with _validated_project_connection(project) as db:
        db.execute("BEGIN IMMEDIATE")
        exists = db.execute("SELECT 1 FROM organisations WHERE organisation_id=?", (society_id,)).fetchone()
        current = _org(db, society_id) if exists else None
        if current:
            event = identity._event(db, current["revision"], DIRECTORY_EVENT)
            if event["request_sha256"] == request:
                return current
        if expected_revision != (current["revision"] if current else None):
            raise identity.StalePublicationError("Reopen the society directory entry")
        stamp = _utc_now()
        event_id = identity._audit(db, DIRECTORY_EVENT, dict(version=1, at_utc=stamp, society_id=society_id,
                   name=name, official_url=official_url, actor=actor, previous_revision=expected_revision,
                   request_sha256=request))
        metadata = identity._json(dict(official_url=official_url, directory_event_id=event_id))
        if current:
            db.execute("UPDATE organisations SET name=?,metadata_json=? WHERE organisation_id=?",
                       (name, metadata, society_id))
        else:
            db.execute("INSERT INTO organisations VALUES(?,?,?)", (society_id, name, metadata))
        return _org(db, society_id)


def _same_host(url, official):
    return urlsplit(web_url(url)).hostname == urlsplit(official).hostname


def record_society_visit(project, *, request_id, society_id, revision, actor, method, terms, pages,
                         outcome, limitations, confirmed):
    """Record the operator's observations; manual review never certifies an exhaustive site search."""
    identity._identifier(request_id)
    identity._identifier(society_id)
    identity._text(actor, 200)
    identity._text(limitations, 4000)
    if (confirmed is not True or type(revision) is not int or revision <= 0
            or method not in ("manual_browse", "site_search")
            or outcome not in ("guidance_found", "none_seen", "unavailable", "review_needed")
            or not isinstance(terms, list) or len(terms) > 512
            or not isinstance(pages, list) or len(pages) > 512):
        raise ValueError("Invalid manual search task")
    for term in terms:
        identity._text(term, 256)
    if (method == "site_search" and not terms) or (not pages and outcome not in ("unavailable", "review_needed")):
        raise ValueError("Missing source observations")
    for page in pages:
        if not isinstance(page, dict) or set(page) != {"url", "examined_on"}:
            raise ValueError("Each page requires a URL and examination date")
        web_url(page["url"])
        if date.fromisoformat(page["examined_on"]).isoformat() != page["examined_on"]:
            raise ValueError("Use an ISO calendar date")
    details = dict(society_id=society_id, directory_revision=revision, actor=actor, method=method,
                   terms=terms, pages=pages, outcome=outcome, limitations=limitations, exhaustive=False)
    with _validated_project_connection(project) as db:
        db.execute("BEGIN IMMEDIATE")
        prior = db.execute("SELECT event_id FROM audit_events WHERE event_type=? "
                           "AND json_extract(details_json,'$.request_id')=?", (VISIT_EVENT, request_id)).fetchall()
        if prior:
            if len(prior) != 1:
                raise identity.PublicationIntegrityError("Ambiguous manual visit receipt")
            event_id = prior[0][0]
            event = identity._event(db, event_id, VISIT_EVENT)
            if event.get("details") != details:
                raise ValueError("Manual visit request reused with different details")
            return dict(event, event_id=event_id)
        org = _org(db, society_id)
        if org["revision"] != revision:
            raise identity.StalePublicationError("Society directory entry changed")
        if any(not _same_host(p["url"], org["official_url"]) for p in pages):
            raise ValueError("Reviewed page must be on the confirmed official hostname")
        event = dict(version=1, at_utc=_utc_now(), request_id=request_id, details=details)
        event_id = identity._audit(db, VISIT_EVENT, event)
        return dict(event, event_id=event_id)


def list_society_visits(project, society_id):
    with _validated_project_connection(project) as db:
        db.execute("BEGIN")
        _org(db, society_id)
        ids = db.execute("SELECT event_id FROM audit_events WHERE event_type=? "
                         "AND json_extract(details_json,'$.details.society_id')=? ORDER BY event_id",
                         (VISIT_EVENT, society_id))
        return [dict(identity._event(db, i, VISIT_EVENT), event_id=i) for (i,) in ids]


def import_guidance(project, *, request_id, run_id, visit_event_id, record, roles, actor, confirmed):
    """Capture one version witnessed on an official site, including a society-only item without DOI."""
    identity._identifier(request_id)
    identity._identifier(run_id)
    identity._text(actor, 200)
    if confirmed is not True or not isinstance(record, dict) or not isinstance(roles, dict):
        raise ValueError("Researcher confirmation and guidance metadata required")
    optional = {"authors", "edition", "issue_date", "update_statement", "document_url", "journal_citation",
                "supplement", "doi"}
    required = {"title", "document_types", "landing_url"}
    if not required <= record.keys() or record.keys() - required - optional:
        raise ValueError("Unexpected or missing guidance fields")
    identity._text(record["title"], 2048)
    web_url(record["landing_url"])
    types = record["document_types"]
    if (not isinstance(types, list) or not types or any(type(t) is not str or t not in GUIDANCE_TYPES for t in types)
            or len(types) != len(set(types))):
        raise ValueError("Explicit document types required")
    for field in optional & record.keys():
        if field == "document_url":
            web_url(record[field])
        elif field == "authors":
            if not isinstance(record[field], list) or len(record[field]) > 512:
                raise ValueError("Expected a list of authors")
            for author in record[field]:
                identity._text(author, 500)
        else:
            identity._text(record[field], 2048)
    if set(roles) - {"issuing", "collaborating", "endorsing"} or not roles.get("issuing"):
        raise ValueError("At least one verified issuing society required")
    for ids in roles.values():
        if not isinstance(ids, list) or len(ids) > 128:
            raise ValueError("Invalid society role assignments")
        for org_id in ids:
            identity._identifier(org_id)
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate society role assignment")
    request = identity._hash([request_id, run_id, visit_event_id, record, roles, actor])
    with _validated_project_connection(project) as db:
        db.execute("BEGIN IMMEDIATE")
        prior = db.execute("SELECT event_id FROM audit_events WHERE event_type=? "
                           "AND json_extract(details_json,'$.request_id')=?", (GUIDANCE_EVENT, request_id)).fetchall()
        if prior:
            receipt = identity._event(db, prior[0][0], GUIDANCE_EVENT)
            if len(prior) != 1 or receipt.get("request_sha256") != request:
                raise ValueError("Guidance request conflicts with existing evidence")
            source = identity._source(db, receipt["retrieval_id"])
            if source["source_sha256"] != receipt["source_sha256"]:
                raise identity.PublicationIntegrityError("Guidance original changed")
            return dict(receipt, event_id=prior[0][0])
        visit = identity._event(db, visit_event_id, VISIT_EVENT)["details"]
        if (visit["outcome"] != "guidance_found" or
                record["landing_url"] not in {page["url"] for page in visit["pages"]}):
            raise ValueError("Guidance must link to an observed official page")
        named = {role: [_org(db, oid) for oid in ids] for role, ids in roles.items()}
        stamp = _utc_now()
        retrieval, publication = str(uuid4()), str(uuid4())
        original = dict(provider="manual_society_guidance", record=record, society_roles=named,
                        visit_event_id=visit_event_id, actor=actor, retrieved_at_utc=stamp,
                        rights_status="licence_review_required")
        db.execute("INSERT INTO source_retrievals VALUES(?,?,?,?,?,?)",
                   (retrieval, run_id, "society", request_id, stamp, identity._json(original)))
        db.execute("INSERT INTO publications(publication_id,created_at_utc) VALUES(?,?)", (publication, stamp))
        source = identity._source(db, retrieval)
        identity._record_link(db, source, before=None, after=publication, previous_event_id=None,
                              status="review_required", action="materialise", actor=actor,
                              evidence="Researcher-confirmed society guidance source")
        db.executemany("INSERT INTO publication_organisations VALUES(?,?,?)",
                       [(publication, org_id, role) for role, ids in roles.items() for org_id in ids])
        event = dict(version=1, at_utc=stamp, request_id=request_id, request_sha256=request,
                     actor=actor, source_sha256=source["source_sha256"], publication_id=publication,
                     retrieval_id=retrieval, visit_event_id=visit_event_id)
        event_id = identity._audit(db, GUIDANCE_EVENT, event)
        return dict(event, event_id=event_id)
