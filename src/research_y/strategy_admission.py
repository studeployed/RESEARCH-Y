"""Atomic researcher-approved OR strategy admission and unexecuted query plans.

This is a trusted Python service, not a browser endpoint or a search executor.
The caller must obtain explicit researcher approval; a stable request UUID
allows lost replies to be reconciled without duplicate strategy versions/runs.
All related writes use one SQLite transaction and one validated project handle.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from uuid import UUID, NAMESPACE_URL, uuid5

from research_y.export_files import project_guard
from research_y.projects import Project, _utc_now, _validated_project_connection
from research_y.query_compiler import compile_both
from research_y.storage import (
    StrategyGroup, _audit, _canonical_json, _groups_snapshot, _nonblank,
)


# Distinct UUIDv5 domains keep an admission request, immutable version, run and
# query rows separate. The stable request UUID is host-owned, not a term value.
_NAMESPACE = uuid5(NAMESPACE_URL, "research-y/approved-strategy-admission/v1")


class StrategyAdmissionError(ValueError):
    """A static code, with no project paths or user-supplied terms."""

    def __init__(self, code: str):
        super().__init__(code if code in {
            "approval_required", "invalid_request_id", "admission_conflict",
            "admission_evidence_invalid", "no_active_terms",
        } else "admission_evidence_invalid")


@dataclass(frozen=True, slots=True)
class StrategyAdmission:
    request_id: str
    strategy_version_id: str
    version_number: int
    run_id: str
    query_count: int
    newly_created: bool
    run_status: str
    # Query text is not returned by this service; inspect the authoritative
    # run snapshot for exact text, statuses, provenance and unknown counts.


def _canonical_uuid(value: str) -> str:
    if type(value) is not str:
        raise StrategyAdmissionError("invalid_request_id")
    try:
        if str(UUID(value)) != value:
            raise ValueError
    except (ValueError, AttributeError, TypeError):
        raise StrategyAdmissionError("invalid_request_id") from None
    return value


def _identity(kind: str, request_id: str) -> str:
    return str(uuid5(_NAMESPACE, kind + ":" + request_id))


def _plans(snapshot: dict, request_id: str):
    """Compiler-derived exact per-group queries, never an inferred provider cap."""
    sources = compile_both(snapshot)
    plans = []
    for compiled in sources:
        for group in compiled.groups:
            if group.exact_group_query is None:
                continue  # An empty/disabled group has no executable query.
            query_id = str(uuid5(
                _NAMESPACE,
                "query:" + request_id + ":" +
                json.dumps([compiled.source_name, group.group_id],
                           ensure_ascii=False, separators=(",", ":")),
            ))
            plans.append((query_id, group.group_id, compiled.source_name,
                          group.exact_group_query, "{}"))
    return tuple(plans)


def commit_approved_strategy(
    project: Project, *,
    request_id: str,
    theme: str,
    groups: tuple[StrategyGroup, ...] | list[StrategyGroup],
    approved_by: str,
    approval_confirmed: bool,
) -> StrategyAdmission:
    """Atomically freeze terms, create one pending run and plan both sources.

    Never executes a source call, changes provider counts or marks retrieval as
    verified. Retrying the *same* UUID with an identical approved snapshot
    returns the original version/run. Reusing a UUID for different content,
    or inconsistent stored evidence, fails closed with no new writes.
    """
    if approval_confirmed is not True:
        raise StrategyAdmissionError("approval_required")
    request_id = _canonical_uuid(request_id)
    theme = _nonblank(theme, field="research theme")
    approved_by = _nonblank(approved_by, field="approver")
    frozen_groups = _groups_snapshot(groups)
    snapshot = {
        "format_version": 1, "theme": theme, "logic": "OR",
        "approved_by": approved_by, "groups": frozen_groups,
    }
    # Compile and validate the *entire* draft before starting an audit write.
    # The compiler enforces OR, escaped literals and mandatory PubMed/WoS
    # source fields. No provider-specific byte ceiling is guessed.
    try:
        plans = _plans(snapshot, request_id)
    except ValueError as exc:
        from research_y.query_compiler import QueryCompilationError
        if isinstance(exc, QueryCompilationError) and "No active" in str(exc):
            raise StrategyAdmissionError("no_active_terms") from None
        raise
    if not plans:
        raise StrategyAdmissionError("no_active_terms")
    payload = _canonical_json(snapshot)
    version_id = _identity("strategy", request_id)
    run_id = _identity("run", request_id)
    expected_rows = sorted(
        (query_id, run_id, version_id, group_id, source, query, parameters)
        for query_id, group_id, source, query, parameters in plans
    )
    with project_guard(project), _validated_project_connection(project) as db:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute(
            "SELECT version_number,snapshot_json FROM strategy_versions "
            "WHERE strategy_version_id=?", (version_id,)
        ).fetchone()
        if existing is not None:
            version_number, stored_payload = existing
            if stored_payload != payload:
                raise StrategyAdmissionError("admission_conflict")
            state = db.execute(
                "SELECT strategy_version_id,status FROM search_runs WHERE run_id=?",
                (run_id,)
            ).fetchone()
            actual_groups = db.execute(
                "SELECT group_id,label,group_order FROM strategy_groups "
                "WHERE strategy_version_id=? ORDER BY group_order",
                (version_id,)
            ).fetchall()
            expected_groups = [
                (item["group_id"], item["label"], item["group_order"])
                for item in frozen_groups
            ]
            actual_rows = sorted(db.execute(
                "SELECT query_id,run_id,strategy_version_id,group_id,source_name,"
                "exact_query,parameters_json FROM source_queries WHERE run_id=?",
                (run_id,)
            ).fetchall())
            if (state is None or state[0] != version_id or
                    actual_groups != expected_groups or
                    actual_rows != expected_rows):
                raise StrategyAdmissionError("admission_evidence_invalid")
            return StrategyAdmission(request_id, version_id, version_number,
                                     run_id, len(plans), False, state[1])
        # If a partially corrupted database already owns a deterministic
        # run/query ID, do not overwrite it or reinterpret it as a new request.
        if db.execute("SELECT 1 FROM search_runs WHERE run_id=?", (run_id,)).fetchone():
            raise StrategyAdmissionError("admission_evidence_invalid")
        for query_id, *_ in plans:
            if db.execute("SELECT 1 FROM source_queries WHERE query_id=?",
                          (query_id,)).fetchone():
                raise StrategyAdmissionError("admission_evidence_invalid")

        version_number = db.execute(
            "SELECT COALESCE(MAX(version_number),0)+1 FROM strategy_versions"
        ).fetchone()[0]
        now = _utc_now()
        db.execute(
            "INSERT INTO strategy_versions "
            "(strategy_version_id,version_number,approved_at_utc,snapshot_json) "
            "VALUES (?,?,?,?)", (version_id, version_number, now, payload)
        )
        db.executemany(
            "INSERT INTO strategy_groups "
            "(strategy_version_id,group_id,label,group_order) VALUES (?,?,?,?)",
            [(version_id, entry["group_id"], entry["label"], entry["group_order"])
             for entry in frozen_groups]
        )
        _audit(db, kind="strategy_approved", timestamp=now,
               details={"strategy_version_id": version_id, "version_number": version_number,
                        "approved_by": approved_by, "group_count": len(frozen_groups),
                        "admission_request_id": request_id})
        db.execute(
            "INSERT INTO search_runs "
            "(run_id,strategy_version_id,created_at_utc,status) "
            "VALUES (?,?,?,'pending')", (run_id, version_id, now)
        )
        _audit(db, kind="search_run_created", timestamp=now,
               details={"run_id": run_id, "strategy_version_id": version_id,
                        "status": "pending", "admission_request_id": request_id})
        for query_id, group_id, source, exact_query, parameters in plans:
            db.execute(
                "INSERT INTO source_queries "
                "(query_id,run_id,strategy_version_id,group_id,source_name,"
                "exact_query,parameters_json) VALUES (?,?,?,?,?,?,?)",
                (query_id, run_id, version_id, group_id, source, exact_query,
                 parameters)
            )
            _audit(db, kind="source_query_planned", timestamp=now,
                   details={"query_id": query_id, "run_id": run_id,
                            "group_id": group_id, "source_name": source,
                            "admission_request_id": request_id})
    return StrategyAdmission(request_id, version_id, version_number,
                             run_id, len(plans), True, "pending")
