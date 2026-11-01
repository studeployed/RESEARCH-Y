"""Explicit source-backed field choices, separate from original/enriched data.

Choices retain paths and audit references, not another copy of source values.
No inferred missingness, conflict resolution, enrichment or redistribution
permission is created by a choice. Raw alternatives remain in the snapshot.
"""
from __future__ import annotations

import re

from research_y.projects import Project, _utc_now, _validated_project_connection
from research_y.publication_identity import (
    FIELD_EVENT, PublicationSnapshot, _audit, _event, _expect, _field_state, _hash,
    _identifier, _json, _path, _snapshot, _text,
)


def _field_name(field: str) -> None:
    if not isinstance(field, str) or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", field) is None:
        raise ValueError("A simple bibliographic field name is required")


def select_source_field(project: Project, publication_id: str, field: str, *,
                        retrieval_id: str, path: tuple[str | int, ...], expected_revision: str,
                        actor: str, reason: str) -> PublicationSnapshot:
    """Select an exact existing source value; retain actor, reason and all alternatives."""
    _identifier(publication_id)
    _identifier(retrieval_id)
    _field_name(field)
    _text(actor, 200)
    _text(reason)
    request = _hash(["select", publication_id, field, retrieval_id, path, expected_revision, actor, reason])
    with _validated_project_connection(project) as db:
        db.execute("BEGIN IMMEDIATE")
        snapshot = _snapshot(db, publication_id)
        old = snapshot.chosen_fields.get(field)
        if old is not None and old["provenance"].get("request_sha256") == request:
            return snapshot
        _expect(snapshot, expected_revision)
        source = next((s for s in snapshot.retrievals if s["retrieval_id"] == retrieval_id), None)
        if source is None:
            raise ValueError("Chosen field must refer to a current publication retrieval")
        _path(source["original_metadata"], path)
        raw = db.execute("SELECT chosen_metadata_json FROM publications WHERE publication_id=?",
                         (publication_id,)).fetchone()[0]
        state = _field_state(db, publication_id, raw)
        # Store other fields in the immutable receipt; its own allocated ID
        # supplies the selected field. Never predict AUTOINCREMENT values.
        fields = {k: v for k, v in state["fields"].items() if k != field}
        event = dict(version=1, at_utc=_utc_now(), action="select", method="exact-source-value/1",
                     publication_id=publication_id, field=field, retrieval_id=retrieval_id,
                     path=list(path), source_sha256=source["source_sha256"], actor=actor, reason=reason,
                     previous_head_event_id=state["head_event_id"], previous_field_event_id=state["fields"].get(field),
                     after_fields=fields, request_sha256=request)
        inserted = _audit(db, FIELD_EVENT, event)
        fields[field] = inserted
        db.execute("UPDATE publications SET chosen_metadata_json=? WHERE publication_id=?",
                   (_json(dict(version=1, head_event_id=inserted, fields=fields)), publication_id))
        return _snapshot(db, publication_id)


def clear_source_field(project: Project, publication_id: str, field: str, *,
                       expected_revision: str, actor: str, reason: str) -> PublicationSnapshot:
    """Remove a current choice, not its source or audit; no replacement is invented."""
    _identifier(publication_id)
    _field_name(field)
    _text(actor, 200)
    _text(reason)
    request = _hash(["clear", publication_id, field, expected_revision, actor, reason])
    with _validated_project_connection(project) as db:
        db.execute("BEGIN IMMEDIATE")
        snapshot = _snapshot(db, publication_id)
        raw = db.execute("SELECT chosen_metadata_json FROM publications WHERE publication_id=?",
                         (publication_id,)).fetchone()[0]
        state = _field_state(db, publication_id, raw)
        if state["head_event_id"] is not None:
            head = _event(db, state["head_event_id"], FIELD_EVENT)
            if head.get("action") == "clear" and head.get("request_sha256") == request:
                return snapshot
        _expect(snapshot, expected_revision)
        if field not in snapshot.chosen_fields:
            return snapshot
        fields = dict(state["fields"])
        previous_field = fields.pop(field)
        event = dict(version=1, at_utc=_utc_now(), action="clear", method="explicit-field-clear/1",
                     publication_id=publication_id, field=field, actor=actor, reason=reason,
                     previous_head_event_id=state["head_event_id"], previous_field_event_id=previous_field,
                     after_fields=fields, request_sha256=request)
        event_id = _audit(db, FIELD_EVENT, event)
        db.execute("UPDATE publications SET chosen_metadata_json=? WHERE publication_id=?",
                   (_json(dict(version=1, head_event_id=event_id, fields=fields)), publication_id))
        return _snapshot(db, publication_id)
