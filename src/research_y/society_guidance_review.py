"""Suggest official society libraries and explicitly relate reviewed guidance versions."""
from __future__ import annotations

import re

from research_y import publication_identity as identity
from research_y.projects import _utc_now, _validated_project_connection

RELATION = "society_guidance_relation_v1"
LIBRARIES = (
    ("Extracorporeal Life Support Organization", "https://www.elso.org/ecmo-resources/elso-ecmo-guidelines.aspx",
     ("ECMO", "extracorporeal", "ECLS")),
    ("Society of Critical Care Medicine", "https://www.sccm.org/clinical-resources/guidelines",
     ("critical care", "intensive care", "ICU", "sepsis")),
    ("American Thoracic Society", "https://site.thoracic.org/about-us/news/official-ats-documents",
     ("respiratory", "pulmonary", "thoracic", "ARDS")),
)


def suggest_societies(terms):
    if not isinstance(terms,list) or len(terms)>512:
        raise ValueError("Expected a bounded list of research terms")
    for term in terms:
        identity._text(term,2048)
    rows = []
    for name, url, cues in LIBRARIES:
        matched = [term for term in terms if any(re.search(r"(?<!\w)"+re.escape(c)+r"(?!\w)",term,re.I) for c in cues)]
        if matched:
            rows.append(dict(name=name,official_url=url,matched_terms=matched,origin="curated_official_libraries/1",
                             researcher_confirmation_required=True))
    return rows


def relate_guidance(project, *, request_id, publication_id, other_publication_id, relation,
                    expected_revision, other_revision, actor, rationale, confirmed):
    """Direction is from this publication to its predecessor or companion original."""
    identity._identifier(request_id)
    identity._identifier(publication_id)
    identity._identifier(other_publication_id)
    identity._text(actor,200)
    identity._text(rationale,2000)
    if confirmed is not True or publication_id == other_publication_id or relation not in ("supersedes","companion_to"):
        raise ValueError("Explicit, distinct guidance relationship required")
    request = identity._hash([publication_id,other_publication_id,relation,expected_revision,other_revision,actor,rationale])
    with _validated_project_connection(project) as db:
        db.execute("BEGIN IMMEDIATE")
        prior = db.execute("SELECT event_id FROM audit_events WHERE event_type=? AND json_extract(details_json,'$.request_id')=?",
                           (RELATION,request_id)).fetchone()
        if prior:
            existing = identity._event(db,prior[0],RELATION)
            if existing["request_sha256"] != request:
                raise ValueError("Request reused for a different relationship")
            return dict(existing,event_id=prior[0])
        left,right = [identity._snapshot(db,i) for i in (publication_id,other_publication_id)]
        if not left.active or not right.active or not any(r["source_name"]=="society" for r in left.retrievals):
            raise ValueError("Select an active society document and related active publication")
        if relation == "supersedes" and not any(r["source_name"]=="society" for r in right.retrievals):
            raise ValueError("Both versions require an original society source")
        if (left.revision,right.revision)!=(expected_revision,other_revision):
            raise identity.StalePublicationError("Reopen the two source records")
        previous = [identity._object(raw) for raw, in db.execute("SELECT details_json FROM audit_events WHERE event_type=?",
                                                                   (RELATION,))]
        if relation == "supersedes":
            edges = {}
            for row in previous:
                if row["relation"]=="supersedes":
                    edges.setdefault(row["publication_id"],set()).add(row["other_publication_id"])
            queue,seen = [other_publication_id],set()
            while queue:
                node=queue.pop()
                if node==publication_id:
                    raise ValueError("Supersession would create a cycle")
                if node not in seen:
                    seen.add(node)
                    queue.extend(edges.get(node,()))
        event = dict(version=1, at_utc=_utc_now(), request_id=request_id, request_sha256=request,
                     publication_id=publication_id, other_publication_id=other_publication_id, relation=relation,
                     source_revision=expected_revision, other_revision=other_revision, actor=actor, rationale=rationale)
        eid=identity._audit(db,RELATION,event)
        return dict(event,event_id=eid)


def attach_journal_manifestation(project, *, society_publication_id, journal_retrieval_id, society_revision,
                                 journal_revision, actor, rationale, confirmed):
    """Add only a reviewed journal retrieval to the society identity. Preserve original roles and source links."""
    with _validated_project_connection(project) as db:
        db.execute("BEGIN IMMEDIATE")
        target = identity._snapshot(db,identity._identifier(society_publication_id))
        original = identity._source(db,identity._identifier(journal_retrieval_id))
        if not any(s["source_name"]=="society" for s in target.retrievals) or original["source_name"] not in ("pubmed","wos"):
            raise ValueError("An original society identity and journal source are required")
        return identity._associate_in_transaction(db,journal_retrieval_id,society_publication_id,
                     expected_target_revision=society_revision,expected_source_revision=journal_revision,
                     actor=actor,evidence=rationale,same_publication_confirmed=confirmed)
