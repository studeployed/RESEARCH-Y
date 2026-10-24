"""Transactional persistence of approved search strategies and pending runs.

Phase 1 P1-02b. This does not compile, execute, count or verify a source
query. Only explicitly approved atomic terms are frozen into the strategy.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import sqlite3
from typing import Any
from uuid import uuid4

from research_y.projects import Project, _utc_now, _validated_project_connection


ORIGINS = frozenset({"researcher", "deterministic", "ai"})
PRIMARY_SOURCES = frozenset({"pubmed", "wos"})


@dataclass(frozen=True, slots=True)
class ApprovedTerm:
    """One atomic term. Approval must come from an explicit researcher action."""

    text: str
    origin: str
    approved: bool
    rationale: str = ""
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class StrategyGroup:
    group_id: str
    label: str
    terms: tuple[ApprovedTerm, ...]


@dataclass(frozen=True, slots=True)
class StrategyVersion:
    strategy_version_id: str
    version_number: int
    approved_at_utc: str


@dataclass(frozen=True, slots=True)
class SearchRun:
    run_id: str
    strategy_version_id: str
    created_at_utc: str
    status: str


@dataclass(frozen=True, slots=True)
class PendingSourceQuery:
    query_id: str
    run_id: str
    group_id: str
    source_name: str
    exact_query: str
    parameters: dict[str, Any]
    status: str
    reported_matches: int | None


def _nonblank(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be nonblank text")
    if any(ord(c) < 32 for c in value):
        raise ValueError(f"{field} may not contain control characters")
    return value.strip()


def _canonical_json(value: Any) -> str:
    # A strict JSON encoding preserves provenance and refuses NaN/Infinity.
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Value is not representable as strict JSON") from exc


def _audit(connection: sqlite3.Connection, *, kind: str, details: dict[str, Any],
           timestamp: str) -> None:
    connection.execute(
        "INSERT INTO audit_events (occurred_at_utc, event_type, details_json) "
        "VALUES (?, ?, ?)",
        (timestamp, kind, _canonical_json(details)),
    )


def _groups_snapshot(groups: Sequence[StrategyGroup]) -> list[dict[str, Any]]:
    if isinstance(groups, (str, bytes)) or not isinstance(groups, Sequence) or not groups:
        raise ValueError("An approved strategy must have at least one group")
    seen_groups: set[str] = set()
    stored: list[dict[str, Any]] = []
    for number, group in enumerate(groups):
        if not isinstance(group, StrategyGroup):
            raise TypeError("groups must contain StrategyGroup entries")
        group_id = _nonblank(group.group_id, field="group_id")
        label = _nonblank(group.label, field="group label")
        if group_id in seen_groups:
            raise ValueError("Duplicate group_id in approved strategy")
        seen_groups.add(group_id)
        if not isinstance(group.terms, (tuple, list)):
            raise TypeError("group terms must be an ordered collection")
        stored_terms: list[dict[str, Any]] = []
        seen_terms: set[str] = set()
        for term in group.terms:
            if not isinstance(term, ApprovedTerm):
                raise TypeError("terms must contain ApprovedTerm entries")
            value = _nonblank(term.text, field="atomic term")
            if term.approved is not True:
                raise ValueError("Unapproved term cannot enter a frozen strategy")
            if term.origin not in ORIGINS:
                raise ValueError(f"Unrecognised term origin: {term.origin}")
            if not isinstance(term.rationale, str):
                raise TypeError("Term rationale must be text")
            if term.origin == "ai" and not term.rationale.strip():
                raise ValueError("AI-generated terms require a visible rationale")
            if type(term.enabled) is not bool:
                raise TypeError("enabled must be a boolean")
            if value in seen_terms:
                raise ValueError("Duplicate atomic term in approved group")
            seen_terms.add(value)
            stored_terms.append({
                "text": value, "origin": term.origin, "rationale": term.rationale,
                "enabled": term.enabled, "approved": True,
            })
        stored.append({
            "group_id": group_id, "label": label,
            "group_order": number, "terms": stored_terms,
        })
    return stored


def approve_strategy(
    project: Project,
    *,
    theme: str,
    groups: Sequence[StrategyGroup],
    approved_by: str,
    approval_confirmed: bool,
) -> StrategyVersion:
    """Freeze a researcher-approved OR-only term snapshot and its audit event.

    The caller is responsible for presenting and obtaining actual human approval;
    this storage method refuses absent approval confirmation and unapproved terms.
    It does not generate or execute any search query.
    """
    if approval_confirmed is not True:
        raise ValueError("Researcher approval is required before freezing a strategy")
    theme = _nonblank(theme, field="research theme")
    approved_by = _nonblank(approved_by, field="approver")
    frozen_groups = _groups_snapshot(groups)
    snapshot = {
        "format_version": 1, "theme": theme, "logic": "OR",
        "approved_by": approved_by, "groups": frozen_groups,
    }
    payload = _canonical_json(snapshot)
    identifier = str(uuid4())
    timestamp = _utc_now()
    with _validated_project_connection(project) as connection:
        connection.execute("BEGIN IMMEDIATE")
        version_number = connection.execute(
            "SELECT COALESCE(MAX(version_number), 0) + 1 FROM strategy_versions"
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO strategy_versions "
            "(strategy_version_id, version_number, approved_at_utc, snapshot_json) "
            "VALUES (?, ?, ?, ?)",
            (identifier, version_number, timestamp, payload),
        )
        connection.executemany(
            "INSERT INTO strategy_groups "
            "(strategy_version_id, group_id, label, group_order) VALUES (?, ?, ?, ?)",
            [(identifier, entry["group_id"], entry["label"], entry["group_order"])
             for entry in frozen_groups],
        )
        _audit(
            connection, kind="strategy_approved", timestamp=timestamp,
            details={"strategy_version_id": identifier, "version_number": version_number,
                     "approved_by": approved_by, "group_count": len(frozen_groups)},
        )
    return StrategyVersion(identifier, version_number, timestamp)


def get_strategy_snapshot(project: Project, strategy_version_id: str) -> dict[str, Any]:
    _nonblank(strategy_version_id, field="strategy_version_id")
    with _validated_project_connection(project) as connection:
        row = connection.execute(
            "SELECT snapshot_json FROM strategy_versions WHERE strategy_version_id = ?",
            (strategy_version_id,),
        ).fetchone()
    if row is None:
        raise KeyError(f"Unknown strategy version: {strategy_version_id}")
    return json.loads(row[0])


def create_search_run(project: Project, strategy_version_id: str) -> SearchRun:
    """Create a pending, non-executed run tied to one frozen strategy."""
    _nonblank(strategy_version_id, field="strategy_version_id")
    run_id, timestamp = str(uuid4()), _utc_now()
    with _validated_project_connection(project) as connection:
        connection.execute("BEGIN IMMEDIATE")
        exists = connection.execute(
            "SELECT 1 FROM strategy_versions WHERE strategy_version_id = ?",
            (strategy_version_id,),
        ).fetchone()
        if exists is None:
            raise KeyError(f"Unknown strategy version: {strategy_version_id}")
        connection.execute(
            "INSERT INTO search_runs (run_id, strategy_version_id, created_at_utc) "
            "VALUES (?, ?, ?)",
            (run_id, strategy_version_id, timestamp),
        )
        _audit(
            connection, kind="search_run_created", timestamp=timestamp,
            details={"run_id": run_id, "strategy_version_id": strategy_version_id,
                     "status": "pending"},
        )
    return SearchRun(run_id, strategy_version_id, timestamp, "pending")


def plan_source_query(
    project: Project, *, run_id: str, group_id: str, source_name: str,
    exact_query: str, parameters: Mapping[str, Any] | None = None,
) -> PendingSourceQuery:
    """Record a proposed *unexecuted* primary-source query under a run.

    Provider syntax/logic is validated by the later query compiler; callers
    must not regard this record as a completed search or a reported hit count.
    """
    for field, value in (("run_id", run_id), ("group_id", group_id),
                         ("exact_query", exact_query)):
        _nonblank(value, field=field)
    if source_name not in PRIMARY_SOURCES:
        raise ValueError("Only primary database sources can be planned here")
    if parameters is None:
        parameters = {}
    if not isinstance(parameters, Mapping):
        raise TypeError("parameters must be a mapping")
    params = dict(parameters)
    if any(not isinstance(k, str) for k in params):
        raise ValueError("Query parameter keys must be text")
    encoded = _canonical_json(params)
    query_id, timestamp = str(uuid4()), _utc_now()
    with _validated_project_connection(project) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT strategy_version_id, status FROM search_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"Unknown run: {run_id}")
        version_id, status = row
        if status != "pending":
            raise ValueError("Source queries may only be planned for pending runs")
        valid_group = connection.execute(
            "SELECT 1 FROM strategy_groups WHERE strategy_version_id = ? AND group_id = ?",
            (version_id, group_id),
        ).fetchone()
        if valid_group is None:
            raise ValueError("Group does not belong to the run's frozen strategy")
        connection.execute(
            "INSERT INTO source_queries "
            "(query_id, run_id, strategy_version_id, group_id, "
            "source_name, exact_query, parameters_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (query_id, run_id, version_id, group_id, source_name,
             exact_query, encoded),
        )
        _audit(
            connection, kind="source_query_planned", timestamp=timestamp,
            details={"query_id": query_id, "run_id": run_id,
                     "group_id": group_id, "source_name": source_name},
        )
    return PendingSourceQuery(
        query_id, run_id, group_id, source_name, exact_query,
        params, "pending", None,
    )


def list_run_queries(project: Project, run_id: str) -> list[PendingSourceQuery]:
    """Read exact stored queries and explicitly unknown provider counts."""
    _nonblank(run_id, field="run_id")
    with _validated_project_connection(project) as connection:
        rows = connection.execute(
            "SELECT query_id, run_id, group_id, source_name, exact_query, "
            "parameters_json, status, reported_matches "
            "FROM source_queries WHERE run_id = ? ORDER BY rowid",
            (run_id,),
        ).fetchall()
    return [
        PendingSourceQuery(
            row[0], row[1], row[2], row[3], row[4], json.loads(row[5]),
            row[6], row[7],
        )
        for row in rows
    ]
