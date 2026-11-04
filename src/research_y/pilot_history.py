"""Read-only, paginated project history of explicitly authorised source pilots.

A saved pilot request is NOT a verified source query. This inventory reads
the existing append-only PubMed/WoS journals; it never starts a network call,
resets a quota hold or manufactures a missing outcome after a process crash.
"""
from __future__ import annotations

import json
import sqlite3
from uuid import UUID

from research_y.export_files import project_guard
from research_y.projects import _validated_project_connection
from research_y import pubmed_pilot, wos_starter_pilot

PAGE_SIZE = 25
REQUEST_TYPES = (
    pubmed_pilot.REQUEST_EVENT,
    wos_starter_pilot.REQUEST_EVENT,
)
PROVIDERS = {
    pubmed_pilot.REQUEST_EVENT: ("pubmed", pubmed_pilot),
    wos_starter_pilot.REQUEST_EVENT: ("wos", wos_starter_pilot),
}


class PilotHistoryError(ValueError):
    """Safe error code only; original SQLite/JSON/source data never echoed."""

    def __init__(self, code="pilot_evidence_invalid"):
        self.code = code if code in {
            "pilot_evidence_invalid", "pilot_history_cursor_invalid"
        } else "pilot_evidence_invalid"
        super().__init__(self.code)


def _canonical_uuid(value):
    try:
        if type(value) is not str or str(UUID(value)) != value:
            raise ValueError
    except (TypeError, ValueError, AttributeError):
        raise PilotHistoryError() from None
    return value


def _strict_object(pairs):
    obj = {}
    for name, value in pairs:
        if name in obj:
            raise ValueError
        obj[name] = value
    return obj


def _request_id(value):
    try:
        parsed = json.loads(
            value, object_pairs_hook=_strict_object,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if type(parsed) is not dict:
            raise ValueError
        return _canonical_uuid(parsed.get("pilot_id"))
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise PilotHistoryError() from None


def read_pilot_history(project, *, before_event_id=None) -> dict:
    """At most 25 validated attempts, newest requests first, across BOTH sources.

    All statuses are current at the time of this read transaction. Pagination
    is request-event ID based, not response-event based. Older pages remain
    available; no result claims that truncated history is complete.
    """
    if before_event_id is not None and (
            type(before_event_id) is not int or
            not 1 <= before_event_id <= 2**63 - 1):
        raise PilotHistoryError("pilot_history_cursor_invalid")
    with project_guard(project), _validated_project_connection(project) as db:
        # Freeze one coherent read view: an outcome committed concurrently
        # cannot appear for some rows but be absent for other rows.
        db.execute("BEGIN")
        where = ("event_type IN (?,?)"
                 if before_event_id is None
                 else "event_type IN (?,?) AND event_id < ?")
        args = (*REQUEST_TYPES,)
        if before_event_id is not None:
            args += (before_event_id,)
        rows = db.execute(
            "SELECT event_id,event_type,details_json,occurred_at_utc "
            "FROM audit_events WHERE " + where +
            " ORDER BY event_id DESC LIMIT ?",
            (*args, PAGE_SIZE + 1),
        ).fetchall()
        selected = rows[:PAGE_SIZE]
        history = []
        for event_id, kind, raw, request_stamp in selected:
            source, module = PROVIDERS[kind]
            pilot_id = _request_id(raw)
            try:
                request, outcome = module._events(db, pilot_id)
                if request is None or request["recorded_at_utc"] != request_stamp:
                    raise PilotHistoryError()
                record = module._view(request, outcome)
                if (record.get("pilot_id") != pilot_id or
                        record.get("source", source) != source or
                        record.get("source_retrieval_verified") is not False or
                        record.get("search_completed") is not False or
                        record.get("execution_authorized") is not False or
                        record.get("automatically_retryable") is not False or
                        type(record.get("reported_matches")) not in (int, type(None))):
                    raise PilotHistoryError()
                # Deliberately exclude whole queries, provider translations,
                # keys, source payloads and other nonessential method evidence
                # from the project-wide list. Exact detail is fetched by
                # the original validated provider receipt on explicit selection.
                history.append({
                    "request_event_id": event_id,
                    "pilot_id": pilot_id,
                    "source": source,
                    "run_id": record["run_id"],
                    "query_id": record["query_id"],
                    "status": record["status"],
                    "reported_matches": record["reported_matches"],
                    "requested_at_utc": record["requested_at_utc"],
                    "completed_at_utc": record["completed_at_utc"],
                    "count_only": record["count_only"],
                    "sample_only": record.get("sample_only", False),
                    "quota_status": record.get("quota_status"),
                    "source_retrieval_verified": False,
                    "search_completed": False,
                    "execution_authorized": False,
                    "automatically_retryable": False,
                })
            except (pubmed_pilot.PubMedPilotError,
                    wos_starter_pilot.WoSPilotError, KeyError, TypeError,
                    ValueError):
                raise PilotHistoryError() from None
        total = db.execute(
            "SELECT COUNT(*) FROM audit_events WHERE event_type IN (?,?)",
            REQUEST_TYPES,
        ).fetchone()[0]
        next_cursor = selected[-1][0] if len(rows) > PAGE_SIZE else None
        return {
            "entries": history,
            "next_before_event_id": next_cursor,
            "request_events_total": total,
            "page_size": PAGE_SIZE,
            "source_retrieval_verified": False,
            "search_completed": False,
            "execution_authorized": False,
            "no_network_requests": True,
        }
