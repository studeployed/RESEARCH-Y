"""Audited, explicitly authorised *count-only* PubMed pilot for one frozen query.

This service is deliberately not a search executor. It reuses the strict PubMed
ESearch retmax=0 client and immutable preflight plan. In-flight ambiguity must
never cause an automatic second provider request.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import sqlite3
from uuid import UUID

from research_y.export_files import project_guard
from research_y.preflight_review import _inspect, PreflightError
from research_y.projects import _validated_project_connection
from research_y.pubmed_cooldown import project_requests, retry_not_before
from research_y.pubmed_probe import (
    PubMedESearchProbeClient, PubMedCountProbe, PubMedProbeError,
)
from research_y.storage import _audit

REQUEST_EVENT = "pubmed_count_pilot_requested_v1"
OUTCOME_EVENT = "pubmed_count_pilot_outcome_v1"
METHOD = "pubmed-esearch-count-only-pilot/1"
STATUSES = frozenset(("requested_indeterminate", "count_reported_not_retrieved",
                      "translation_review_required", "probe_failed", "stale_plan"))
FAILURE_CODES = frozenset(("provider_unavailable", "provider_rate_limited",
                           "provider_response_invalid", "provider_auth_error"))
REVIEW_REASONS = frozenset((
    "PubMed reported warnings/errors requiring query review",
    "PubMed query translation differs from the submitted query",
    "PubMed may have introduced unwanted Medical Subject Headings mapping",
    "PubMed translation includes AND/NOT outside quoted literals",
))


class PubMedPilotError(ValueError):
    """Fixed, credential-free codes; never expose provider exception bodies."""

    def __init__(self, code):
        allowed = {"invalid_identifier", "pilot_confirmation_required",
                   "pilot_conflict", "pilot_evidence_invalid", "pilot_plan_invalid",
                   "pilot_storage_failed", "pilot_client_invalid", "provider_cooldown"}
        self.code = code if code in allowed else "pilot_evidence_invalid"
        super().__init__(self.code)


def _uuid(value):
    try:
        if type(value) is not str or str(UUID(value)) != value:
            raise ValueError
    except (TypeError, ValueError, AttributeError):
        raise PubMedPilotError("invalid_identifier") from None
    return value


def _sha(value):
    if type(value) is not str or len(value) != 64 or any(
            c not in "0123456789abcdef" for c in value):
        raise PubMedPilotError("pilot_plan_invalid")
    return value


def _utc(value):
    try:
        stamp = datetime.fromisoformat(value)
        if stamp.utcoffset() is None or stamp.utcoffset().total_seconds() != 0:
            raise ValueError
    except (ValueError, TypeError, AttributeError, OverflowError):
        raise PubMedPilotError("pilot_evidence_invalid") from None
    return value


def _base(pilot_id, run_id, query_id, plan_sha):
    return dict(method=METHOD, pilot_id=pilot_id, run_id=run_id,
                query_id=query_id, plan_sha256=plan_sha,
                source="pubmed", count_only=True,
                source_retrieval_verified=False, execution_authorized=False)


def _events(db, pilot_id):
    request = outcome = None
    for kind, raw, stamp in db.execute(
            "SELECT event_type,details_json,occurred_at_utc FROM audit_events "
            "WHERE event_type IN (?,?) ORDER BY event_id",
            (REQUEST_EVENT, OUTCOME_EVENT)):
        try:
            record = json.loads(raw)
            if type(record) is not dict:
                raise ValueError
        except (TypeError, ValueError):
            raise PubMedPilotError("pilot_evidence_invalid") from None
        if record.get("pilot_id") != pilot_id:
            continue
        _utc(stamp)
        if (record.get("method") != METHOD or
                record.get("source") != "pubmed" or
                record.get("count_only") is not True or
                record.get("source_retrieval_verified") is not False or
                record.get("execution_authorized") is not False):
            raise PubMedPilotError("pilot_evidence_invalid")
        if kind == REQUEST_EVENT:
            if request is not None or record.get("status") != "requested_indeterminate":
                raise PubMedPilotError("pilot_evidence_invalid")
            request = dict(record, recorded_at_utc=stamp)
        elif kind == OUTCOME_EVENT:
            if outcome is not None or record.get("status") not in STATUSES - {"requested_indeterminate"}:
                raise PubMedPilotError("pilot_evidence_invalid")
            outcome = dict(record, recorded_at_utc=stamp)
        else:
            raise PubMedPilotError("pilot_evidence_invalid")
    if outcome is not None and request is None:
        raise PubMedPilotError("pilot_evidence_invalid")
    if request is not None and outcome is not None:
        for key in ("method", "pilot_id", "run_id", "query_id", "plan_sha256",
                    "source", "count_only", "source_retrieval_verified",
                    "execution_authorized", "exact_query"):
            if request.get(key) != outcome.get(key):
                raise PubMedPilotError("pilot_evidence_invalid")
    return request, outcome


def _view(request, outcome):
    record = outcome or request
    if record is None:
        raise PubMedPilotError("pilot_evidence_invalid")
    status = record["status"]
    if status not in STATUSES:
        raise PubMedPilotError("pilot_evidence_invalid")
    matches = record.get("reported_matches")
    if matches is not None and (type(matches) is not int or matches < 0
                                or status not in ("count_reported_not_retrieved",
                                                  "translation_review_required")):
        raise PubMedPilotError("pilot_evidence_invalid")
    if (status in ("count_reported_not_retrieved", "translation_review_required")
            and matches is None):
        raise PubMedPilotError("pilot_evidence_invalid")
    return dict(
        pilot_id=record["pilot_id"], run_id=record["run_id"],
        query_id=record["query_id"], plan_sha256=record["plan_sha256"],
        status=status, reported_matches=matches,
        exact_query=record["exact_query"],
        accepted_translation=record.get("accepted_translation"),
        translation_matches_submitted=record.get("translation_matches_submitted"),
        warnings=record.get("warnings", []),
        review_reasons=record.get("review_reasons", []),
        error_code=record.get("error_code"),
        checked_at_utc=record.get("checked_at_utc"),
        requested_at_utc=request["recorded_at_utc"],
        completed_at_utc=None if outcome is None else outcome["recorded_at_utc"],
        count_only=True, provider="PubMed ESearch",
        retrieval_verified=False, source_retrieval_verified=False,
        search_completed=False, execution_authorized=False,
        automatically_retryable=False,
    )


def read_pubmed_pilot(project, pilot_id: str) -> dict | None:
    """Read original immutable audit evidence even after subsequent run changes."""
    pilot_id = _uuid(pilot_id)
    with project_guard(project), _validated_project_connection(project) as db:
        request, outcome = _events(db, pilot_id)
        return None if request is None else _view(request, outcome)


def _query(db, run_id, query_id, plan_sha):
    try:
        summary = _inspect(db, run_id)
    except PreflightError:
        raise PubMedPilotError("pilot_plan_invalid") from None
    if summary["plan_sha256"] != plan_sha:
        raise PubMedPilotError("pilot_plan_invalid")
    found = [q for source in summary["sources"]
             if source["source_name"] == "pubmed"
             for q in source["queries"] if q["query_id"] == query_id]
    if len(found) != 1:
        raise PubMedPilotError("pilot_plan_invalid")
    return found[0]["exact_query"]


def _probe_outcome(report, exact_query, client):
    if (type(report) is not PubMedCountProbe or report.exact_query != exact_query
            or type(report.reported_matches) is not int
            or not 0 <= report.reported_matches < 10**20
            or report.retrieved_records != 0 or
            report.retrieval_verified is not False
            or type(report.translation_matches_submitted) is not bool
            or type(report.accepted_translation) is not str
            or not report.accepted_translation or
            len(report.accepted_translation) > 16384
            or type(report.warnings) is not tuple or len(report.warnings) > 25
            or type(report.review_reasons) is not tuple
            or set(report.review_reasons) - REVIEW_REASONS):
        raise PubMedPilotError("pilot_evidence_invalid")
    _utc(report.checked_at_utc)
    if any(type(w) is not str or len(w) > 1024 or
           any(ord(c) < 32 or ord(c) == 127 for c in w)
           for w in report.warnings + report.review_reasons):
        raise PubMedPilotError("pilot_evidence_invalid")
    # The provider text is untrusted. Fail closed if it unexpectedly repeats
    # the host-supplied API key/contact, rather than journalling that secret.
    for secret in (getattr(client, "_api_key", None), getattr(client, "_email", None)):
        if (type(secret) is str and secret and
                (secret in report.accepted_translation or
                 any(secret in w for w in report.warnings))):
            raise PubMedPilotError("pilot_evidence_invalid")
    return dict(
        status=("translation_review_required" if report.review_required else
                "count_reported_not_retrieved"),
        reported_matches=report.reported_matches,
        accepted_translation=report.accepted_translation,
        translation_matches_submitted=report.translation_matches_submitted,
        warnings=list(report.warnings),
        review_reasons=list(report.review_reasons),
        checked_at_utc=report.checked_at_utc,
        error_code=None,
    )


@project_requests
def probe_pubmed_count_once(
    project, *, pilot_id: str, run_id: str, query_id: str,
    expected_plan_sha256: str, confirmed: bool,
    client: PubMedESearchProbeClient,
) -> dict:
    """One authorised count-only provider request, never implicit replay.

    A durable request receipt is written BEFORE the network call. If the
    process dies or the outcome cannot be stored, the original attempt is
    indeterminate; repeating this UUID does NOT call PubMed again. A new UUID
    requires a fresh explicit confirmation and is a separate audited attempt.
    """
    pilot_id, run_id, query_id = _uuid(pilot_id), _uuid(run_id), _uuid(query_id)
    expected_plan_sha256 = _sha(expected_plan_sha256)
    if confirmed is not True:
        raise PubMedPilotError("pilot_confirmation_required")
    if not isinstance(client, PubMedESearchProbeClient):
        raise PubMedPilotError("pilot_client_invalid")
    base = _base(pilot_id, run_id, query_id, expected_plan_sha256)
    with project_guard(project):
        try:
            with _validated_project_connection(project) as db:
                db.execute("BEGIN IMMEDIATE")
                request, outcome = _events(db, pilot_id)
                if request is not None:
                    if any(request.get(k) != v for k, v in base.items()):
                        raise PubMedPilotError("pilot_conflict")
                    # A past completed result or unresolved attempt is read-only
                    # here, including after project/run state changes.
                    return _view(request, outcome)
                exact_query = _query(db, run_id, query_id, expected_plan_sha256)
                deadline = retry_not_before(db)
                if deadline is not None and datetime.fromisoformat(deadline) > client._cooldown.utcnow():
                    raise PubMedPilotError("provider_cooldown")
                start = dict(base, exact_query=exact_query,
                             status="requested_indeterminate")
                _audit(db, kind=REQUEST_EVENT,
                       timestamp=datetime.now(timezone.utc).isoformat(timespec="microseconds"),
                       details=start)
        except PubMedPilotError:
            raise
        except (sqlite3.Error, OSError, ValueError, TypeError):
            raise PubMedPilotError("pilot_storage_failed") from None

        try:
            report = client.probe(exact_query)
            data = _probe_outcome(report, exact_query, client)
        except PubMedProbeError as exc:
            code = ("provider_rate_limited" if exc.http_status == 429 else
                    "provider_auth_error" if exc.http_status in (401, 403) else
                    "provider_unavailable")
            data = dict(status="probe_failed", error_code=code,
                        reported_matches=None)
        except Exception:
            # No raw exception/provider/source data reaches an audit receipt.
            data = dict(status="probe_failed",
                        error_code="provider_response_invalid",
                        reported_matches=None)
        try:
            with _validated_project_connection(project) as db:
                db.execute("BEGIN IMMEDIATE")
                request, outcome = _events(db, pilot_id)
                if (request is None or
                        any(request.get(k) != v for k, v in base.items()) or
                        request.get("exact_query") != exact_query):
                    raise PubMedPilotError("pilot_evidence_invalid")
                if outcome is not None:
                    return _view(request, outcome)
                try:
                    fresh = _query(db, run_id, query_id, expected_plan_sha256)
                    if fresh != exact_query:
                        raise PubMedPilotError("pilot_plan_invalid")
                except PubMedPilotError:
                    data = dict(status="stale_plan", error_code=None,
                                reported_matches=None)
                complete = dict(base, exact_query=exact_query, **data)
                recorded_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
                _audit(db, kind=OUTCOME_EVENT, timestamp=recorded_at, details=complete)
                return _view(request, dict(complete, recorded_at_utc=recorded_at))
        except PubMedPilotError:
            raise
        except (sqlite3.Error, OSError, ValueError, TypeError):
            raise PubMedPilotError("pilot_storage_failed") from None
