"""P1-06a: explicit publication identities over preserved source retrievals.

No automatic matching, source completion, final deduplicated count or export is
provided here. Schema-v4 associations point to the existing append-only audit;
there is no second source/membership store and no migration. All writes use one
identity-checked connection and an immediate transaction. Empty publication
identities remain available for reversal, never as active result rows.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import sqlite3
from typing import Any
from uuid import UUID, uuid4

from research_y.projects import Project, _utc_now, _validated_project_connection

IDENTITY_EVENT = "publication_identity_v1"
FIELD_EVENT = "publication_field_v1"
METHOD = "explicit-publication-identity/1"


class PublicationIntegrityError(ValueError):
    """An existing identity, source reference or audit receipt is inconsistent."""


class StalePublicationError(ValueError):
    """The researcher must reopen the changed evidence before deciding."""


@dataclass(frozen=True, slots=True)
class PublicationSnapshot:
    publication_id: str
    created_at_utc: str
    revision: str
    retrievals: tuple[dict[str, Any], ...]
    chosen_fields: dict[str, Any]
    # These are identity hypotheses, not a verified deduplicated master list.
    deduplication_complete: bool = False
    export_permissions_verified: bool = False

    @property
    def active(self) -> bool:
        return bool(self.retrievals)


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":"))


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate object key")
        result[key] = value
    return result


def _object(raw: str) -> dict[str, Any]:
    try:
        result = json.loads(raw, object_pairs_hook=_pairs)
        if not isinstance(result, dict):
            raise ValueError("Object required")
        _json(result)  # Also reject non-finite numbers accepted by json.loads.
        return result
    except (ValueError, TypeError, RecursionError):
        raise PublicationIntegrityError("Invalid stored publication/source object") from None


def _hash(value: Any) -> str:
    return sha256(_json(value).encode("utf-8")).hexdigest()


def _identifier(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("A canonical identifier is required")
    try:
        valid = str(UUID(value)) == value
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("A canonical identifier is required")
    return value


def _text(value: str, maximum: int = 4000) -> str:
    if (not isinstance(value, str) or not value.strip() or len(value) > maximum
            or any(ord(c) < 32 for c in value)):
        raise ValueError("Nonempty printable decision text is required")
    return value


def _positive(value: int) -> int:
    if type(value) is not int or value < 1:
        raise PublicationIntegrityError("Invalid audit reference")
    return value


def _event(db: sqlite3.Connection, event_id: int, kind: str) -> dict[str, Any]:
    row = db.execute("SELECT event_type,occurred_at_utc,details_json FROM audit_events "
                     "WHERE event_id=?", (_positive(event_id),)).fetchone()
    if row is None or row[0] != kind:
        raise PublicationIntegrityError("Missing or mismatched publication audit")
    result = _object(row[2])
    if type(result.get("version")) is not int or result["version"] != 1 or result.get("at_utc") != row[1]:
        raise PublicationIntegrityError("Invalid publication audit version or timestamp")
    return result


def _audit(db: sqlite3.Connection, kind: str, details: dict[str, Any]) -> int:
    return int(db.execute(
        "INSERT INTO audit_events(occurred_at_utc,event_type,details_json) VALUES(?,?,?)",
        (details["at_utc"], kind, _json(details)),
    ).lastrowid)


def _source(db: sqlite3.Connection, retrieval_id: str) -> dict[str, Any]:
    row = db.execute(
        "SELECT retrieval_id,run_id,source_name,source_record_id,retrieved_at_utc,"
        "original_metadata_json FROM source_retrievals WHERE retrieval_id=?",
        (retrieval_id,),
    ).fetchone()
    if row is None:
        raise KeyError("Unknown source retrieval")
    run = db.execute("SELECT status FROM search_runs WHERE run_id=?", (row[1],)).fetchone()
    if run is None:
        raise PublicationIntegrityError("Source retrieval has no parent run")
    return dict(zip(("retrieval_id", "run_id", "source_name", "source_record_id",
                     "retrieved_at_utc"), row[:5]), original_metadata=_object(row[5]),
                source_sha256=_hash(row), run_status=run[0])


def _link(db: sqlite3.Connection, retrieval_id: str) -> tuple[str, int, dict[str, Any]] | None:
    row = db.execute("SELECT publication_id,decision_provenance_json "
                     "FROM publication_retrievals WHERE retrieval_id=?", (retrieval_id,)).fetchone()
    if row is None:
        return None
    pointer = _object(row[1])
    if (set(pointer) != {"version", "event_id"} or type(pointer["version"]) is not int
            or pointer["version"] != 1):
        raise PublicationIntegrityError("Unsupported association provenance; review required")
    event_id = _positive(pointer["event_id"])
    event = _event(db, event_id, IDENTITY_EVENT)
    if (event.get("retrieval_id") != retrieval_id or event.get("after") != row[0]
            or event.get("status") not in ("review_required", "confirmed_match")
            or event.get("source_sha256") != _source(db, retrieval_id)["source_sha256"]):
        raise PublicationIntegrityError("Association and source evidence do not agree")
    return row[0], event_id, event


def _field_state(db: sqlite3.Connection, publication_id: str, raw: str) -> dict[str, Any]:
    state = _object(raw)
    if not state:
        return {"version": 1, "head_event_id": None, "fields": {}}
    if (set(state) != {"version", "head_event_id", "fields"} or state["version"] != 1
            or type(state["version"]) is not int or not isinstance(state["fields"], dict)):
        raise PublicationIntegrityError("Unsupported chosen-field provenance; review required")
    head = _event(db, state["head_event_id"], FIELD_EVENT)
    expected_fields = head.get("after_fields")
    if isinstance(expected_fields, dict) and head.get("action") == "select":
        expected_fields = {**expected_fields, head.get("field"): state["head_event_id"]}
    if head.get("publication_id") != publication_id or expected_fields != state["fields"]:
        raise PublicationIntegrityError("Chosen fields do not match their audit")
    return state


def _path(value: Any, path: list[str | int] | tuple[str | int, ...]) -> Any:
    if not isinstance(path, (tuple, list)) or not 1 <= len(path) <= 16:
        raise ValueError("A bounded source-field path is required")
    for part in path:
        if isinstance(value, dict) and isinstance(part, str) and part in value:
            value = value[part]
        elif isinstance(value, list) and type(part) is int and 0 <= part < len(value):
            value = value[part]
        else:
            raise ValueError("Requested source field is not available")
    if value is None or value == "" or value == [] or value == {}:
        raise ValueError("Missing source values cannot become chosen metadata")
    return value


def _snapshot(db: sqlite3.Connection, publication_id: str) -> PublicationSnapshot:
    row = db.execute("SELECT created_at_utc,chosen_metadata_json FROM publications "
                     "WHERE publication_id=?", (publication_id,)).fetchone()
    if row is None:
        raise KeyError("Unknown publication")
    sources = []
    for (retrieval_id,) in db.execute("SELECT retrieval_id FROM publication_retrievals "
                                      "WHERE publication_id=? ORDER BY retrieval_id", (publication_id,)):
        source = _source(db, retrieval_id)
        link = _link(db, retrieval_id)
        if link is None or link[0] != publication_id:
            raise PublicationIntegrityError("Inconsistent publication association")
        memberships = db.execute(
            "SELECT q.query_id,q.run_id,q.strategy_version_id,q.group_id,q.source_name,"
            "q.exact_query,q.reported_matches,q.status,s.status FROM query_retrievals m "
            "JOIN source_queries q ON q.query_id=m.query_id AND q.run_id=m.run_id "
            "AND q.source_name=m.source_name "
            "JOIN search_runs s ON s.run_id=q.run_id AND s.strategy_version_id=q.strategy_version_id "
            "WHERE m.retrieval_id=? ORDER BY q.query_id",
            (retrieval_id,),
        ).fetchall()
        source.update(association_event_id=link[1], decision=link[2], memberships=[
            dict(zip(("query_id", "run_id", "strategy_version_id", "group_id", "source_name",
                      "exact_query", "reported_matches", "status", "run_status"), member)) for member in memberships])
        sources.append(source)
    field_state = _field_state(db, publication_id, row[1])
    by_id = {s["retrieval_id"]: s for s in sources}
    chosen = {}
    for field, event_id in field_state["fields"].items():
        event = _event(db, event_id, FIELD_EVENT)
        source = by_id.get(event.get("retrieval_id"))
        if (source is None or event.get("action") != "select"
                or event.get("publication_id") != publication_id or event.get("field") != field
                or event.get("source_sha256") != source["source_sha256"]):
            raise PublicationIntegrityError("Chosen field lost its source association")
        try:
            value = _path(source["original_metadata"], event.get("path"))
        except ValueError:
            raise PublicationIntegrityError("Chosen source field changed or is unavailable") from None
        chosen[field] = {"value": value, "provenance": event, "event_id": event_id}
    # Include source and membership evidence. A reversal uses a new audit event,
    # so returning to the same membership cannot revive an old review token.
    revision = _hash([publication_id, row, sources])
    return PublicationSnapshot(publication_id, row[0], revision, tuple(sources), chosen)


def read_publication(project: Project, publication_id: str) -> PublicationSnapshot:
    """Read one consistent local snapshot; values are not export permissions."""
    _identifier(publication_id)
    with _validated_project_connection(project) as db:
        db.execute("BEGIN")
        return _snapshot(db, publication_id)


def _expect(snapshot: PublicationSnapshot, revision: str) -> None:
    if not isinstance(revision, str) or snapshot.revision != revision:
        raise StalePublicationError("Publication evidence changed; reopen before deciding")


def _record_link(db: sqlite3.Connection, source: dict[str, Any], *, before: str | None,
                 after: str, previous_event_id: int | None, status: str, action: str,
                 actor: str, evidence: str, request_sha256: str | None = None,
                 reverses_event_id: int | None = None) -> int:
    event = dict(version=1, at_utc=_utc_now(), method=METHOD, action=action,
                 retrieval_id=source["retrieval_id"], source_sha256=source["source_sha256"],
                 before=before, after=after, previous_event_id=previous_event_id,
                 status=status, actor=actor, evidence=evidence, request_sha256=request_sha256,
                 reverses_event_id=reverses_event_id)
    event_id = _audit(db, IDENTITY_EVENT, event)
    pointer = _json({"version": 1, "event_id": event_id})
    if before is None:
        db.execute("INSERT INTO publication_retrievals VALUES(?,?,?)",
                   (source["retrieval_id"], after, pointer))
    else:
        db.execute("UPDATE publication_retrievals SET publication_id=?,decision_provenance_json=? "
                   "WHERE retrieval_id=?", (after, pointer, source["retrieval_id"]))
    return event_id


def materialise_retrieval(project: Project, retrieval_id: str, *, actor: str) -> PublicationSnapshot:
    """Create one provisional identity, or reuse its existing reviewed identity.

    Equal identifiers, titles or containers never cause an automatic association.
    Repeat calls cannot multiply publication rows, memberships or audit entries.
    """
    _identifier(retrieval_id)
    _text(actor, 200)
    with _validated_project_connection(project) as db:
        db.execute("BEGIN IMMEDIATE")
        source = _source(db, retrieval_id)
        link = _link(db, retrieval_id)
        if link is not None:
            return _snapshot(db, link[0])
        publication_id = str(uuid4())
        db.execute("INSERT INTO publications(publication_id,created_at_utc) VALUES(?,?)",
                   (publication_id, _utc_now()))
        _record_link(db, source, before=None, after=publication_id, previous_event_id=None,
                     status="review_required", action="materialise", actor=actor,
                     evidence="One source retrieval; publication equivalence not assessed")
        return _snapshot(db, publication_id)


def _movable(db: sqlite3.Connection, snapshot: PublicationSnapshot, retrieval_id: str) -> None:
    if any(v["provenance"]["retrieval_id"] == retrieval_id for v in snapshot.chosen_fields.values()):
        raise ValueError("Clear source-backed field choices before moving their retrieval")
    # Do not silently move or strand future specialist annotations. A later
    # publication-level merge/split workflow must explicitly disposition them.
    for table in ("classifications", "documents", "publication_containers", "publication_organisations"):
        if db.execute(f"SELECT 1 FROM {table} WHERE publication_id=? LIMIT 1",
                      (snapshot.publication_id,)).fetchone():
            raise ValueError("Publication annotations require dedicated merge/split review")


def associate_retrieval(project: Project, retrieval_id: str, target_publication_id: str, *,
                        expected_source_revision: str, expected_target_revision: str,
                        actor: str, evidence: str, same_publication_confirmed: bool) -> PublicationSnapshot:
    """Explicitly associate one retrieval, retaining the old identity for undo.

    This is not a publication-wide merge or an automatic candidate decision.
    An exact retry of the still-current decision is a no-op; stale earlier
    requests after another identity decision are rejected rather than replayed.
    """
    _identifier(retrieval_id)
    _identifier(target_publication_id)
    _text(actor, 200)
    _text(evidence)
    if same_publication_confirmed is not True:
        raise ValueError("Explicit same-publication confirmation is required")
    request = _hash(["associate", retrieval_id, target_publication_id, expected_source_revision,
                     expected_target_revision, actor, evidence])
    with _validated_project_connection(project) as db:
        db.execute("BEGIN IMMEDIATE")
        link = _link(db, retrieval_id)
        if link is None:
            raise ValueError("Materialise the retrieval before reviewing an association")
        if link[2].get("action") == "associate" and link[2].get("request_sha256") == request:
            return _snapshot(db, link[0])
        origin, target = _snapshot(db, link[0]), _snapshot(db, target_publication_id)
        _expect(origin, expected_source_revision)
        _expect(target, expected_target_revision)
        if origin.publication_id == target.publication_id:
            return target
        if not target.active:
            raise ValueError("Choose an active target publication, not a retained empty identity")
        _movable(db, origin, retrieval_id)
        _record_link(db, _source(db, retrieval_id), before=origin.publication_id,
                     after=target.publication_id, previous_event_id=link[1], status="confirmed_match",
                     action="associate", actor=actor, evidence=evidence, request_sha256=request)
        return _snapshot(db, target.publication_id)


def reverse_association(project: Project, retrieval_id: str, decision_event_id: int, *,
                        expected_current_revision: str, expected_restored_revision: str,
                        actor: str, evidence: str) -> PublicationSnapshot:
    """Append an inverse decision; never erase history or revive a stale review."""
    _identifier(retrieval_id)
    _positive(decision_event_id)
    _text(actor, 200)
    _text(evidence)
    request = _hash(["reverse", retrieval_id, decision_event_id, expected_current_revision,
                     expected_restored_revision, actor, evidence])
    with _validated_project_connection(project) as db:
        db.execute("BEGIN IMMEDIATE")
        link = _link(db, retrieval_id)
        if link is None:
            raise ValueError("Retrieval has no association")
        if link[2].get("action") == "reverse" and link[2].get("request_sha256") == request:
            return _snapshot(db, link[0])
        original = _event(db, decision_event_id, IDENTITY_EVENT)
        if (link[1] != decision_event_id or original.get("action") != "associate"
                or original.get("retrieval_id") != retrieval_id):
            raise StalePublicationError("Only the current association decision can be reversed")
        previous = _event(db, original["previous_event_id"], IDENTITY_EVENT)
        if previous.get("retrieval_id") != retrieval_id or previous.get("after") != original.get("before"):
            raise PublicationIntegrityError("Previous association audit is inconsistent")
        current, restored = _snapshot(db, link[0]), _snapshot(db, original["before"])
        _expect(current, expected_current_revision)
        _expect(restored, expected_restored_revision)
        _movable(db, current, retrieval_id)
        _record_link(db, _source(db, retrieval_id), before=current.publication_id,
                     after=restored.publication_id, previous_event_id=link[1], status=previous["status"],
                     action="reverse", actor=actor, evidence=evidence, request_sha256=request,
                     reverses_event_id=decision_event_id)
        return _snapshot(db, restored.publication_id)


def read_retrieval_history(project: Project, retrieval_id: str) -> tuple[dict[str, Any], ...]:
    """Return chronological immutable identity decisions, including reversals."""
    _identifier(retrieval_id)
    with _validated_project_connection(project) as db:
        db.execute("BEGIN")
        _source(db, retrieval_id)
        link = _link(db, retrieval_id)
        if link is None:
            return ()
        event_id: int | None = link[1]
        history = []
        expected_after = link[0]
        while event_id is not None:
            event = _event(db, event_id, IDENTITY_EVENT)
            if event.get("retrieval_id") != retrieval_id or event.get("after") != expected_after:
                raise PublicationIntegrityError("Broken publication decision chain")
            history.append({"event_id": event_id, **event})
            previous = event.get("previous_event_id")
            if previous is not None and _positive(previous) >= event_id:
                raise PublicationIntegrityError("Nonchronological publication decision chain")
            expected_after, event_id = event.get("before"), previous
        if expected_after is not None:
            raise PublicationIntegrityError("Publication decision chain lacks its origin")
        return tuple(reversed(history))
