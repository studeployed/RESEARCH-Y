"""One-shot, quota-aware Web of Science Starter minimal-page count pilot.

Starter's documented minimum page size is 1, NOT 0. One licensed record
may be returned transiently; only count/quota/method evidence is retained.
This is not an abstract or publication retrieval workflow.

A durable request receipt precedes the single fixed-origin HTTP request.
An uncertain outcome never causes an automatic replay of that request ID.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from math import isfinite
import json
import sqlite3
from uuid import UUID

from research_y.export_files import project_guard
from research_y.preflight_review import _inspect, PreflightError
from research_y.projects import _validated_project_connection
from research_y.storage import _audit
from research_y.wos_checkpoint_store import _provider_hold, _stamp, WoSCheckpointError
from research_y.wos_starter import WoSPage, WoSQuota, WoSStarterError, validate_request
from research_y.wos_starter_client import WoSStarterClient, MIN_REQUEST_INTERVAL

REQUEST_EVENT = "wos_starter_pilot_requested_v1"
OUTCOME_EVENT = "wos_starter_pilot_outcome_v1"
METHOD = "wos-starter-minimal-page-pilot/1"
DATABASE = "WOS"
STATUSES = frozenset((
    "requested_indeterminate", "count_reported_sample_not_retained",
    "entitlement_unverified", "quota_exhausted_after_probe",
    "probe_failed", "stale_plan",
))
PROVIDER_CODES = frozenset((
    "authentication_or_entitlement_denied", "quota_or_rate_limited",
    "redirect_refused", "http_error", "network_error", "transport_error",
    "invalid_transport_response", "invalid_or_oversized_response",
    "invalid_source_response", "source_error_or_warning",
    "missing_page_metadata", "invalid_source_counts",
    "page_identity_mismatch", "truncated_or_unexpected_page",
    "missing_or_invalid_accession", "duplicate_accession",
    "credential_echo_in_source", "request_budget_exhausted",
    "quota_or_entitlement_unverified", "explicit_revalidation_required",
    "retry_not_due", "credential_in_query",
))


class WoSPilotError(ValueError):
    """Redacted fixed service codes; never echo a key, source text or path."""

    def __init__(self, code):
        allowed = {
            "invalid_identifier", "pilot_confirmation_required",
            "pilot_conflict", "pilot_evidence_invalid", "pilot_plan_invalid",
            "pilot_storage_failed", "pilot_client_invalid",
            "provider_cooldown", "provider_quota_revalidation_required",
            "provider_worker_active", "provider_pilot_cooldown",
        }
        self.code = code if code in allowed else "pilot_evidence_invalid"
        super().__init__(self.code)


def _uuid(value):
    try:
        if type(value) is not str or str(UUID(value)) != value:
            raise ValueError
    except (TypeError, ValueError, AttributeError):
        raise WoSPilotError("invalid_identifier") from None
    return value


def _sha(value):
    if type(value) is not str or len(value) != 64 or any(
            c not in "0123456789abcdef" for c in value):
        raise WoSPilotError("pilot_plan_invalid")
    return value


def _utc(value):
    try:
        stamp = datetime.fromisoformat(value)
        if stamp.utcoffset() is None or stamp.utcoffset().total_seconds() != 0:
            raise ValueError
    except (TypeError, ValueError, AttributeError, OverflowError):
        raise WoSPilotError("pilot_evidence_invalid") from None
    return stamp


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _base(pilot_id, run_id, query_id, plan_sha, *, revalidate_quota):
    return dict(
        method=METHOD, pilot_id=pilot_id, run_id=run_id, query_id=query_id,
        plan_sha256=plan_sha, source="wos", database=DATABASE,
        page_number=1, page_size=1, sort_field="LD+A",
        revalidate_quota=revalidate_quota,
        source_retrieval_verified=False,
        bibliographic_records_persisted=0,
        execution_authorized=False,
    )


def _events(db, pilot_id):
    request = outcome = None
    for kind, raw, timestamp in db.execute(
        "SELECT event_type,details_json,occurred_at_utc FROM audit_events "
        "WHERE event_type IN (?,?) ORDER BY event_id",
        (REQUEST_EVENT, OUTCOME_EVENT),
    ):
        try:
            record = json.loads(raw, object_pairs_hook=_unique,
                                parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if type(record) is not dict:
                raise ValueError
        except (TypeError, ValueError, RecursionError):
            raise WoSPilotError("pilot_evidence_invalid") from None
        if record.get("pilot_id") != pilot_id:
            continue
        _utc(timestamp)
        if (record.get("method") != METHOD or
                record.get("source") != "wos" or
                record.get("database") != DATABASE or
                record.get("page_number") != 1 or
                record.get("page_size") != 1 or
                record.get("sort_field") != "LD+A" or
                type(record.get("revalidate_quota")) is not bool or
                record.get("source_retrieval_verified") is not False or
                record.get("bibliographic_records_persisted") != 0 or
                record.get("execution_authorized") is not False or
                type(record.get("exact_query")) is not str):
            raise WoSPilotError("pilot_evidence_invalid")
        if kind == REQUEST_EVENT:
            if request is not None or record.get("status") != "requested_indeterminate":
                raise WoSPilotError("pilot_evidence_invalid")
            request = dict(record, recorded_at_utc=timestamp)
        elif kind == OUTCOME_EVENT:
            if (outcome is not None or record.get("status") not in
                    STATUSES - {"requested_indeterminate"}):
                raise WoSPilotError("pilot_evidence_invalid")
            outcome = dict(record, recorded_at_utc=timestamp)
        else:
            raise WoSPilotError("pilot_evidence_invalid")
    if outcome is not None and request is None:
        raise WoSPilotError("pilot_evidence_invalid")
    if request is not None and outcome is not None:
        for field in (
            "method", "pilot_id", "run_id", "query_id", "plan_sha256",
            "source", "database", "page_number", "page_size", "sort_field",
            "revalidate_quota", "source_retrieval_verified",
            "bibliographic_records_persisted", "execution_authorized",
            "exact_query",
        ):
            if request.get(field) != outcome.get(field):
                raise WoSPilotError("pilot_evidence_invalid")
    return request, outcome


def _view(request, outcome):
    record = outcome or request
    if request is None:
        raise WoSPilotError("pilot_evidence_invalid")
    status = record["status"]
    if status not in STATUSES:
        raise WoSPilotError("pilot_evidence_invalid")
    count = record.get("reported_matches")
    if (count is not None and (type(count) is not int or
                              not 0 <= count <= 2**63-1 or
                              status not in {
                                  "count_reported_sample_not_retained",
                                  "entitlement_unverified", "quota_exhausted_after_probe"})):
        raise WoSPilotError("pilot_evidence_invalid")
    if (status in {"count_reported_sample_not_retained", "entitlement_unverified",
                   "quota_exhausted_after_probe"} and count is None):
        raise WoSPilotError("pilot_evidence_invalid")
    quota = record.get("quota")
    if quota is not None:
        try:
            if type(quota) is not dict or set(quota) != {
                    "daily_limit", "daily_remaining", "per_second_limit", "valid"}:
                raise ValueError
            parsed = WoSQuota(**quota)
            if (type(parsed.valid) is not bool or
                    any(value is not None and
                        (type(value) is not int or value < 0)
                        for value in (parsed.daily_limit, parsed.daily_remaining,
                                      parsed.per_second_limit))):
                raise ValueError
        except (TypeError, ValueError):
            raise WoSPilotError("pilot_evidence_invalid") from None
    return dict(
        pilot_id=record["pilot_id"], run_id=record["run_id"],
        query_id=record["query_id"], plan_sha256=record["plan_sha256"],
        exact_query=record["exact_query"], source="wos",
        database=DATABASE, status=status, reported_matches=count,
        checked_at_utc=record.get("checked_at_utc"),
        quota=quota, quota_status=record.get("quota_status", "not_observed"),
        error_code=record.get("error_code"),
        retry_after_seconds=record.get("retry_after_seconds"),
        retry_after_unverifiable=record.get("retry_after_unverifiable", False),
        response_sha256=record.get("response_sha256"),
        access_probe_records_received=record.get("access_probe_records_received"),
        requested_at_utc=request["recorded_at_utc"],
        completed_at_utc=None if outcome is None else outcome["recorded_at_utc"],
        accepted_translation=None,
        translation_status="not_exposed_by_starter_contract",
        sample_page_limit=1, sample_only=True,
        count_only=False,  # Starter returns up to one actual licensed record.
        bibliographic_records_persisted=0,
        source_retrieval_verified=False, retrieval_verified=False,
        search_completed=False, execution_authorized=False,
        automatically_retryable=False,
    )


def read_wos_pilot(project, pilot_id: str) -> dict | None:
    """Historical read is independent of current run state; no provider call."""
    pilot_id = _uuid(pilot_id)
    with project_guard(project), _validated_project_connection(project) as db:
        request, outcome = _events(db, pilot_id)
        return None if request is None else _view(request, outcome)


def _query(db, run_id, query_id, expected_plan_sha):
    try:
        summary = _inspect(db, run_id)
    except PreflightError:
        raise WoSPilotError("pilot_plan_invalid") from None
    if summary["plan_sha256"] != expected_plan_sha:
        raise WoSPilotError("pilot_plan_invalid")
    matches = [q for source in summary["sources"]
               if source["source_name"] == "wos"
               for q in source["queries"] if q["query_id"] == query_id]
    if len(matches) != 1:
        raise WoSPilotError("pilot_plan_invalid")
    exact = matches[0]["exact_query"]
    try:
        validate_request(exact, DATABASE, 1, 1)
    except WoSStarterError:
        raise WoSPilotError("pilot_plan_invalid") from None
    return exact


def _guard_provider(db, *, revalidate_quota, now):
    """Existing checkpoint restrictions must not be bypassed by a new pilot.

    This is project-scoped, NOT cross-project or account-wide quota protection.
    One-record probes do not mutate checkpoint retrieval counts or jobs.
    """
    if db.execute(
            "SELECT 1 FROM wos_checkpoint_jobs WHERE owner_token IS NOT NULL LIMIT 1"
    ).fetchone():
        raise WoSPilotError("provider_worker_active")
    try:
        hold, _ = _provider_hold(
            db, _stamp(now), revalidate_quota=revalidate_quota)
    except (WoSCheckpointError, TypeError, ValueError):
        raise WoSPilotError("pilot_evidence_invalid") from None
    if hold is not None:
        raise WoSPilotError(hold)
    # The shared checkpoint guard now handles *both* checkpoint and pilot
    # quota observations (including failed-HTTP quota and Retry-After). Only
    # the pilot's separate request-start pacing remains local here.
    last_stamp = None
    for (stamp,) in db.execute(
        "SELECT occurred_at_utc FROM audit_events WHERE event_type=? "
        "ORDER BY event_id DESC LIMIT 1", (REQUEST_EVENT,)
    ):
        last_stamp = _utc(stamp)
    if last_stamp is not None:
        elapsed = (now - last_stamp).total_seconds()
        if not elapsed >= MIN_REQUEST_INTERVAL:
            raise WoSPilotError("provider_pilot_cooldown")


def _outcome(page, expected_query, client):
    if (type(page) is not WoSPage or page.exact_query != expected_query or
            page.database != DATABASE or page.page != 1 or page.limit != 1 or
            page.sort_field != "LD+A" or
            type(page.reported_matches) is not int or
            not 0 <= page.reported_matches <= 2**63-1 or
            len(page.records) != min(1, page.reported_matches) or
            page.accepted_translation is not None or
            page.translation_status != "not_exposed_by_starter_contract" or
            page.source_retrieval_verified is not False or
            type(page.response_sha256) is not str or
            len(page.response_sha256) != 64 or
            any(c not in "0123456789abcdef" for c in page.response_sha256) or
            type(page.quota) is not WoSQuota):
        raise WoSPilotError("pilot_evidence_invalid")
    _utc(page.retrieved_at_utc)
    quota = page.quota
    details = asdict(quota)
    for key in ("daily_limit", "daily_remaining", "per_second_limit"):
        value = details[key]
        if value is not None and (type(value) is not int or value < 0):
            raise WoSPilotError("pilot_evidence_invalid")
    if type(details["valid"]) is not bool:
        raise WoSPilotError("pilot_evidence_invalid")
    # The existing strict source client rejects echoed API keys throughout
    # returned JSON (including unknown fields), prior to our audit boundary.
    if (type(page.response_json) is not str or
            getattr(client, "_key", "") in page.response_json):
        raise WoSPilotError("pilot_evidence_invalid")
    if quota.entitlement_status != "institutional_allowance_observed":
        status = "entitlement_unverified"
    elif quota.daily_remaining is None:
        status = "entitlement_unverified"
    elif quota.daily_remaining == 0:
        status = "quota_exhausted_after_probe"
    else:
        status = "count_reported_sample_not_retained"
    return dict(
        status=status, reported_matches=page.reported_matches,
        checked_at_utc=page.retrieved_at_utc,
        quota=details, quota_status=quota.entitlement_status,
        access_probe_records_received=len(page.records),
        response_sha256=page.response_sha256,
        error_code=None, retry_after_seconds=None,
    )


def probe_wos_starter_once(
    project, *, pilot_id, run_id, query_id, expected_plan_sha256,
    confirmed: bool, client: WoSStarterClient, revalidate_quota=False,
) -> dict:
    """Exactly one confirmed minimal-page request, never a full retrieval.

    A request journal row is committed first. A lost outcome remains
    indeterminate, never silently retried with the original pilot ID.
    """
    pilot_id, run_id, query_id = _uuid(pilot_id), _uuid(run_id), _uuid(query_id)
    plan_sha = _sha(expected_plan_sha256)
    if confirmed is not True:
        raise WoSPilotError("pilot_confirmation_required")
    if type(revalidate_quota) is not bool:
        raise WoSPilotError("pilot_confirmation_required")
    if type(client) is not WoSStarterClient:
        raise WoSPilotError("pilot_client_invalid")
    base = _base(pilot_id, run_id, query_id, plan_sha,
                 revalidate_quota=revalidate_quota)
    with project_guard(project):
        try:
            with _validated_project_connection(project) as db:
                db.row_factory = sqlite3.Row
                db.execute("BEGIN IMMEDIATE")
                request, outcome = _events(db, pilot_id)
                if request is not None:
                    if any(request.get(k) != v for k, v in base.items()):
                        raise WoSPilotError("pilot_conflict")
                    return _view(request, outcome)
                # A prior client may be used to *read* a completed attempt,
                # but no new UUID can reuse a client's old request budget.
                if client.requests_made != 0:
                    raise WoSPilotError("pilot_client_invalid")
                exact_query = _query(db, run_id, query_id, plan_sha)
                _guard_provider(db, revalidate_quota=revalidate_quota,
                                now=datetime.now(timezone.utc))
                start = dict(base, exact_query=exact_query,
                             status="requested_indeterminate")
                _audit(db, kind=REQUEST_EVENT,
                       timestamp=datetime.now(timezone.utc).isoformat(
                           timespec="microseconds"), details=start)
        except WoSPilotError:
            raise
        except (sqlite3.Error, OSError, ValueError, TypeError):
            raise WoSPilotError("pilot_storage_failed") from None
        try:
            page = client.fetch_page(
                exact_query, database=DATABASE, page=1, limit=1)
            data = _outcome(page, exact_query, client)
        except WoSStarterError as exc:
            code = exc.code if exc.code in PROVIDER_CODES else "source_invalid"
            delay = exc.retry_after_seconds
            # Preserve the observed safe quota independently of whether an
            # HTTP 429/403 or malformed page produced a usable count.
            quota = client.quota
            quota_data = (asdict(quota) if type(quota) is WoSQuota else None)
            delay_valid = (type(delay) in (int, float) and isfinite(delay)
                           and 0 <= delay <= 365*86400)
            data = dict(
                status="probe_failed", reported_matches=None,
                error_code=code, quota=quota_data,
                quota_status=(quota.entitlement_status
                              if type(quota) is WoSQuota else "unverified"),
                retry_after_seconds=(delay if delay_valid else None),
                # An unrepresentable server-directed delay may not simply
                # be dropped or shortened; future attempts fail closed.
                retry_after_unverifiable=(delay is not None and not delay_valid),
            )
        except Exception:
            data = dict(status="probe_failed", reported_matches=None,
                        error_code="source_invalid", retry_after_seconds=None)
        try:
            with _validated_project_connection(project) as db:
                db.execute("BEGIN IMMEDIATE")
                request, outcome = _events(db, pilot_id)
                if (request is None or any(request.get(k) != v for k, v in base.items())
                        or request.get("exact_query") != exact_query):
                    raise WoSPilotError("pilot_evidence_invalid")
                if outcome is not None:
                    return _view(request, outcome)
                try:
                    if _query(db, run_id, query_id, plan_sha) != exact_query:
                        raise WoSPilotError("pilot_plan_invalid")
                except WoSPilotError:
                    data = dict(status="stale_plan", reported_matches=None,
                                error_code=None, retry_after_seconds=None)
                complete = dict(base, exact_query=exact_query, **data)
                stamp = datetime.now(timezone.utc).isoformat(
                    timespec="microseconds")
                _audit(db, kind=OUTCOME_EVENT, timestamp=stamp,
                       details=complete)
                return _view(request, dict(complete, recorded_at_utc=stamp))
        except WoSPilotError:
            raise
        except (sqlite3.Error, OSError, ValueError, TypeError):
            raise WoSPilotError("pilot_storage_failed") from None
