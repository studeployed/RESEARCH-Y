"""Bind a provisional local study suggestion to retained source and classification revisions."""
from research_y import publication_identity as identity
from research_y import study_classification as classification
from research_y.projects import _utc_now, _validated_project_connection

EVENT = "local_study_proposal_v1"


def propose(project, publication_id, retrieval_id, *, assistant, expected_revision):
    with _validated_project_connection(project) as db:
        db.execute("BEGIN")
        view = classification._view(db, publication_id)
        if view["revision"] != expected_revision:
            raise identity.StalePublicationError("Classification changed")
        source = identity._source(db, identity._identifier(retrieval_id))
        link = identity._link(db, retrieval_id)
        if not link or link[0] != publication_id:
            raise ValueError("Source does not belong to the publication")
        original = source["original_metadata"]
        record = original.get("record", {})
        permitted_source = (
            (source["source_name"] == "pubmed" and original.get("source") == "NCBI PubMed EFetch XML") or
            (source["source_name"] == "wos" and original.get("provider") == "wos_starter") or
            (source["source_name"] in {"conference_jats","conference_pdf"} and original.get("provider") == source["source_name"])
        )
        if not permitted_source or not isinstance(record, dict):
            raise ValueError("Missing source text")
        parts = []
        paths = []
        def add(value, path):
            if isinstance(value, str) and value.strip():
                parts.append(" ".join(value.split()))
                paths.append(path)
        add(record.get("title"), ["record","title"])
        if source["source_name"] == "pubmed":
            sections = record.get("abstract_sections") or []
            if not isinstance(sections, list):
                raise ValueError("Invalid retained abstract sections")
            for i, section in enumerate(sections):
                if isinstance(section, dict):
                    add(section.get("text"), ["record","abstract_sections",i,"text"])
        if original.get("provider") in {"conference_jats","conference_pdf"}:
            add(record.get("text"), ["record","text"])
        text = " ".join(parts)
        if not text or len(text) > 5000:
            raise ValueError("Available evidence is empty or exceeds local model input window")
    generated = assistant.propose_study(text)
    with _validated_project_connection(project) as db:
        db.execute("BEGIN IMMEDIATE")
        fresh = classification._view(db, publication_id)
        if fresh["revision"] != expected_revision:
            raise identity.StalePublicationError("Publication changed during inference")
        event = dict(version=1, at_utc=_utc_now(), publication_id=publication_id, retrieval_id=retrieval_id,
                     source_sha256=source["source_sha256"], paths=paths, classification_revision=expected_revision,
                     evidence_revision=view["evidence_revision"], generated=generated)
        eid = identity._audit(db, EVENT, event)
        return dict(event_id=eid, proposals=generated["proposals"], model=generated["model"],
                    publication_id=publication_id, revision=expected_revision)


def review(project, publication_id, *, event_id, dimension, labels, expected_revision, actor, rationale, confirmed):
    with _validated_project_connection(project) as db:
        db.execute("BEGIN")
        source = identity._event(db, event_id, EVENT)
        current = classification._view(db, publication_id)
        if source["publication_id"] != publication_id or source["evidence_revision"] != current["evidence_revision"]:
            raise identity.StalePublicationError("Original model evidence has changed")
        if dimension not in source["generated"]["proposals"]:
            raise ValueError("Unknown proposed dimension")
    return classification.review_classification(project, publication_id, dimension=dimension, labels=labels,
            expected_revision=expected_revision, actor=actor, rationale=rationale,
            confirmed=confirmed, proposal_event_id=event_id)
