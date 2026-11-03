"""Offline, immutable-run-bound pre-execution verification and PRESS review receipts.

The exact stored query plan is checked against the immutable OR compiler.
No provider, search worker, pilot-count request, or new project schema is used.
Manual PRESS checklist entries are *self-reported*, never independent proof.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from uuid import UUID
import json
import sqlite3

from research_y.application_inspection import _read
from research_y.export_files import project_guard
from research_y.projects import _validated_project_connection
from research_y.query_compiler import compile_both, QueryCompilationError
from research_y.storage import _audit
from research_y.strategy_report import canonical, decode, _strategy, ReportIntegrityError


EVENT = "pre_run_review_v1"
METHOD = "pre-run-verification/1"
PRESS_ITEMS = (
    "research_objective", "terminology_coverage", "boolean_logic",
    "source_syntax", "spelling", "search_fields", "limits",
)
STATES = frozenset(("reviewed", "needs_revision", "not_reviewed"))
REVIEW_ROLES = frozenset(("researcher_self_check", "independent_peer_reported"))


class PreflightError(ValueError):
    """Fixed, path/term-free error identifiers exposed across the worker."""
    def __init__(self, code):
        allowed = {"invalid_identifier", "unknown_run", "run_not_pending",
                   "plan_unverified", "review_invalid", "review_conflict",
                   "stale_preflight", "review_evidence_invalid"}
        self.code = code if code in allowed else "plan_unverified"
        super().__init__(self.code)


def _uuid(value):
    try:
        if type(value) is not str or str(UUID(value)) != value:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise PreflightError("invalid_identifier") from None
    return value


def _short_text(value, *, max_length=200, required=True, multiline=False):
    if type(value) is not str or len(value) > max_length:
        raise PreflightError("review_invalid")
    value = value.strip()
    if (required and not value) or any(
        ord(c) == 127 or ord(c) < 32 and
        (not multiline or c not in ("\n", "\t")) for c in value
    ):
        raise PreflightError("review_invalid")
    return value


def _review_payload(review_id, run_id, plan_sha256, *,
                    reviewer_name, reviewer_role, press_items,
                    review_note, known_relevant):
    _uuid(review_id)
    _uuid(run_id)
    if (type(plan_sha256) is not str or len(plan_sha256) != 64 or
            any(char not in "0123456789abcdef" for char in plan_sha256)):
        raise PreflightError("review_invalid")
    if type(reviewer_role) is not str or reviewer_role not in REVIEW_ROLES:
        raise PreflightError("review_invalid")
    reviewer_name = _short_text(reviewer_name)
    note = _short_text(review_note, max_length=2048, required=False, multiline=True)
    if (type(press_items) is not dict or
            set(press_items) != set(PRESS_ITEMS) or
            any(type(v) is not str or v not in STATES
                for v in press_items.values())):
        raise PreflightError("review_invalid")
    if (type(known_relevant) is not tuple or len(known_relevant) > 30):
        raise PreflightError("review_invalid")
    known = [_short_text(value, max_length=150) for value in known_relevant]
    if len(set(known)) != len(known):
        raise PreflightError("review_invalid")
    return dict(method=METHOD, review_id=review_id, run_id=run_id,
                plan_sha256=plan_sha256, reviewer_name=reviewer_name,
                reviewer_role=reviewer_role,
                press_items={key: press_items[key] for key in PRESS_ITEMS},
                review_note=note, known_relevant=known,
                known_relevant_status="not_tested_against_provider",
                peer_review_verified=False,
                execution_authorized=False)


def _previous(db, run_id, plan_sha):
    latest = None
    for event_id, raw, stamp in db.execute(
        "SELECT event_id,details_json,occurred_at_utc FROM audit_events "
        "WHERE event_type=? ORDER BY event_id", (EVENT,)
    ):
        try:
            data = decode(raw)
        except (ValueError, TypeError):
            raise PreflightError("review_evidence_invalid") from None
        if data.get("run_id") != run_id:
            continue
        if (data.get("method") != METHOD or
                data.get("plan_sha256") != plan_sha or
                data.get("peer_review_verified") is not False or
                data.get("execution_authorized") is not False or
                type(data.get("press_items")) is not dict or
                set(data["press_items"]) != set(PRESS_ITEMS)):
            raise PreflightError("review_evidence_invalid")
        try:
            time = datetime.fromisoformat(stamp)
            if time.utcoffset() is None or time.utcoffset().total_seconds() != 0:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise PreflightError("review_evidence_invalid") from None
        latest = dict(data, event_id=event_id, occurred_at_utc=stamp)
    return latest


def _inspect(db, run_id):
    row = db.execute(
        "SELECT r.strategy_version_id,r.status,v.version_number,v.snapshot_json "
        "FROM search_runs r JOIN strategy_versions v ON "
        "r.strategy_version_id=v.strategy_version_id WHERE r.run_id=?",
        (run_id,)
    ).fetchone()
    if row is None:
        raise PreflightError("unknown_run")
    version_id, status, version_number, raw = row
    if status != "pending":
        raise PreflightError("run_not_pending")
    try:
        strategy = decode(raw)
        indexed_groups = db.execute(
            "SELECT group_id,label,group_order FROM strategy_groups "
            "WHERE strategy_version_id=? ORDER BY group_order,group_id",
            (version_id,)
        ).fetchall()
        _strategy(strategy, indexed_groups)
        sources = compile_both(strategy)
    except (ReportIntegrityError, QueryCompilationError, ValueError, TypeError):
        raise PreflightError("plan_unverified") from None
    expected = {}
    for source in sources:
        for group in source.groups:
            if group.exact_group_query is not None:
                expected[(source.source_name, group.group_id)] = group.exact_group_query
    actual = {}
    for ident, version, group_id, source, exact, params, stored_status, matches, executed in db.execute(
        "SELECT query_id,strategy_version_id,group_id,source_name,exact_query,"
        "parameters_json,status,reported_matches,executed_at_utc "
        "FROM source_queries WHERE run_id=?", (run_id,)
    ):
        try:
            _uuid(ident)
            if decode(params) != {}:
                raise ValueError
        except (PreflightError, ValueError, TypeError):
            raise PreflightError("plan_unverified") from None
        key = (source, group_id)
        if (version != version_id or key in actual or key not in expected
                or exact != expected[key] or stored_status != "pending"
                or matches is not None or executed is not None):
            raise PreflightError("plan_unverified")
        actual[key] = dict(query_id=ident, group_id=group_id, source=source,
                           exact_query=exact, parameters={},
                           status="pending", reported_matches=None,
                           provider_translation="not_checked")
    if actual.keys() != expected.keys():
        raise PreflightError("plan_unverified")
    ordered = [
        actual[(source.source_name, group.group_id)]
        for source in sources for group in source.groups
        if group.exact_group_query is not None
    ]
    plan_sha = sha256(canonical(dict(run_id=run_id, version_id=version_id,
        strategy_snapshot=strategy, queries=ordered)).encode("utf-8")).hexdigest()
    summary = dict(
        method=METHOD, run_id=run_id, strategy_version_id=version_id,
        version_number=version_number, plan_sha256=plan_sha,
        theme=strategy["theme"], approved_by=strategy["approved_by"],
        logic="OR", group_count=len(strategy["groups"]),
        active_group_count=len({q["group_id"] for q in ordered}),
        active_term_count=sum(g.active_term_count for g in sources[0].groups),
        groups=strategy["groups"],
        sources=[dict(source_name=source.source_name, source_coverage=source.source_coverage,
            overall_union_preview=source.logical_union_query,
            warnings=list(source.warnings),
            queries=[q for q in ordered if q["source"] == source.source_name])
            for source in sources],
        limitations="none recorded in planned queries; no automatic exclusions",
        programmatic_checks=dict(
            immutable_snapshot="verified", exact_compiler_match="verified",
            broad_or_only="verified", stored_query_coverage="verified",
            provider_translation="not_checked", phrase_behavior="not_checked",
            known_relevant_test="not_performed", press_peer_review="not_verified"),
        known_relevant_status="not_tested_against_provider",
        provider_counts=None, estimated_workload=None,
        workload_status="unknown_until_pilot_counts",
        source_retrieval_verified=False, execution_authorized=False,
        press_items=list(PRESS_ITEMS),
        warnings=["Wide search can return large results; no counts or workload "
                  "are estimated before provider checks.",
                  "PubMed phrase behavior and exact accepted query translation "
                  "have not been tested.",
                  "PRESS self-check is not an independent peer review."],
    )
    summary["last_review"] = _previous(db, run_id, plan_sha)
    return summary


def read_preflight(project, run_id: str) -> dict:
    """Inspect exact frozen plan and recorded reviewer attestations; never write."""
    _uuid(run_id)
    try:
        code = None
        with _read(project) as db:
            # The existing read context maps arbitrary ValueError to its own
            # diagnostic. Catch the *static* preflight error inside the context
            # before its generic conversion can obscure the precise status.
            try:
                result = _inspect(db, run_id)
            except PreflightError as exc:
                code = exc.code
        if code is not None:
            raise PreflightError(code)
        return result
    except PreflightError:
        raise
    except (sqlite3.Error, ValueError, TypeError, KeyError):
        raise PreflightError("plan_unverified") from None


def record_preflight_review(project, *, run_id: str, review_id: str,
                            expected_plan_sha256: str,
                            reviewer_name: str, reviewer_role: str,
                            press_items: dict[str, str],
                            review_note: str = "",
                            known_relevant: tuple[str, ...] = ()) -> dict:
    """Append an idempotent *self-reported* PRESS review; never start retrieval."""
    _uuid(run_id)
    candidate = _review_payload(
        review_id, run_id, expected_plan_sha256,
        reviewer_name=reviewer_name, reviewer_role=reviewer_role,
        press_items=press_items, review_note=review_note,
        known_relevant=known_relevant,
    )
    try:
        with project_guard(project), _validated_project_connection(project) as db:
            db.execute("BEGIN IMMEDIATE")
            current = _inspect(db, run_id)
            if current["plan_sha256"] != expected_plan_sha256:
                raise PreflightError("stale_preflight")
            for (raw,) in db.execute(
                "SELECT details_json FROM audit_events WHERE event_type=?", (EVENT,)
            ):
                try:
                    previous = decode(raw)
                except (ValueError, TypeError):
                    raise PreflightError("review_evidence_invalid") from None
                if previous.get("review_id") == review_id:
                    if previous != candidate:
                        raise PreflightError("review_conflict")
                    return dict(review_id=review_id, run_id=run_id,
                                plan_sha256=expected_plan_sha256,
                                newly_recorded=False,
                                execution_authorized=False,
                                peer_review_verified=False,
                                source_retrieval_verified=False)
            now = datetime.now(timezone.utc).isoformat(timespec="microseconds")
            _audit(db, kind=EVENT, timestamp=now, details=candidate)
            return dict(review_id=review_id, run_id=run_id,
                        plan_sha256=expected_plan_sha256, newly_recorded=True,
                        execution_authorized=False, peer_review_verified=False,
                        source_retrieval_verified=False)
    except PreflightError:
        raise
    except (sqlite3.Error, ValueError, TypeError, KeyError):
        raise PreflightError("review_evidence_invalid") from None
