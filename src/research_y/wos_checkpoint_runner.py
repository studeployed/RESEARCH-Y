"""Bounded, synchronous Starter worker ticks over durable local checkpoints.

No guessed daily resets, background scheduling, implicit retries or secret
persistence. A fresh client rechecks source count and actual quota on resume.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import math
import sqlite3
from typing import Callable

from research_y.projects import Project
from research_y.wos_starter import WoSStarterError
from research_y.wos_starter_client import WoSStarterClient
from research_y.wos_checkpoint_store import (
    WoSCheckpoint, WoSCheckpointError, _accept, _audit_job, _claim, _db,
    _job, _json, _owned, _release, _reserve, _stamp, _state,
    inspect_wos_checkpoint, validate_wos_checkpoint,
)

# Never persist arbitrary exception strings, even from a custom transport.
_SAFE_ERRORS = frozenset((
    "invalid_approved_topic_query", "invalid_database", "invalid_page", "invalid_page_size",
    "invalid_or_oversized_response", "invalid_source_response", "source_error_or_warning",
    "missing_page_metadata", "invalid_source_counts", "page_identity_mismatch",
    "truncated_or_unexpected_page", "invalid_source_record", "missing_or_invalid_accession",
    "duplicate_accession", "page_sequence_mismatch", "source_count_changed", "cross_page_duplicate",
    "credential_in_query", "request_budget_exhausted", "retry_not_due", "explicit_revalidation_required",
    "quota_or_entitlement_unverified", "network_error", "transport_error", "invalid_transport_response",
    "authentication_or_entitlement_denied", "quota_or_rate_limited", "redirect_refused", "http_error",
    "credential_echo_in_source",
))


def _after(stamp: str, seconds: float) -> str:
    # An absurd Retry-After must not be shortened into an early retry.
    try:
        if not math.isfinite(seconds) or seconds < 0:
            raise OverflowError
        return _stamp(datetime.fromisoformat(stamp) + timedelta(seconds=seconds))
    except (OverflowError, ValueError):
        return _stamp(datetime.max.replace(tzinfo=timezone.utc))


def _pause(project: Project, query_id: str, token: str, stamp: str,
           reason: str, *, minimum_delay: float = 0) -> None:
    with _db(project, write=True) as db:
        job = _owned(db, project, query_id, token)
        if job["status"] != "running":
            return
        due = _after(stamp, minimum_delay) if minimum_delay else job["not_before_utc"]
        if due and job["not_before_utc"]:
            due = max(due, job["not_before_utc"])
        db.execute("UPDATE wos_checkpoint_jobs SET not_before_utc=? WHERE query_id=?", (due, query_id))
        _state(db, job, "paused", reason, stamp)


def _failure(project: Project, query_id: str, token: str, attempt_id: str,
             client: WoSStarterClient, exc: WoSStarterError, stamp: str, sent: bool) -> None:
    code = exc.code if exc.code in _SAFE_ERRORS else "unexpected_source_error"
    with _db(project, write=True) as db:
        job = _owned(db, project, query_id, token)
        failures = job["failures"] + 1
        # A parsed HTTP 200 can still fail body or credential-echo validation.
        # The client retains its server delay even if that exception omits it.
        wait = max(30 * 2 ** min(failures - 1, 4), exc.retry_after_seconds or 0,
                   client.retry_after_remaining)
        quota = asdict(client.quota)
        if client.quota.daily_remaining == 0:
            wait = max(wait, 3600)  # Probe cooldown, explicitly NOT a presumed reset.
        db.execute("UPDATE wos_checkpoint_attempts SET outcome='error',finished_at_utc=?,"
                   "reason_code=?,http_status=?,sent=?,quota_json=? WHERE attempt_id=? AND outcome='started'",
                   (stamp, code, exc.http_status, int(sent), _json(quota), attempt_id))
        db.execute("UPDATE wos_checkpoint_jobs SET failures=?,quota_json=?,not_before_utc=? WHERE query_id=?",
                   (failures, _json(quota), _after(stamp, wait), query_id))
        if job["status"] not in ("paused", "cancelled"):
            status = "paused" if exc.retryable and failures < 3 else "incomplete"
            reason = "retry_budget_exhausted" if failures >= 3 else code
            _state(db, job, status, reason, stamp)
        _audit_job(db, job, "request_failed", stamp, attempt_id=attempt_id,
                   reason_code=code, failures=failures, transport_attempted=sent)


def run_wos_checkpoint(
    project: Project, query_id: str, client: WoSStarterClient, *,
    max_requests: int = 1000, revalidate_quota: bool = False,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    on_progress: Callable[[WoSCheckpoint], None] | None = None,
) -> WoSCheckpoint:
    """Run a bounded worker session; return a durable status, never sleep for days.

    Each resume needs a NEW client. It performs a one-record count/first-ID
    probe before acquiring only missing pages. A separate identity verification
    pass compares every captured page; a restarted verification pass starts at
    page 1 (old receipts are preserved). Final source count is checked again.
    A verified enumeration is not an atomic provider snapshot or a full run.
    Each session honours the smaller worker/client request allowance, including
    its resume probe. A local budget stop is a pause, not a source failure.

    After a quota stop the caller must explicitly request revalidation, and the
    saved cooldown/Retry-After still applies. Three failures without forward
    page progress stop further retries; a fresh client cannot reset that budget.
    """
    if type(max_requests) is not int or not 1 <= max_requests <= 10000:
        raise WoSCheckpointError("invalid_session_request_budget")
    if type(revalidate_quota) is not bool:
        raise WoSCheckpointError("invalid_revalidation_flag")
    if not isinstance(client, WoSStarterClient) or client.requests_made != 0:
        raise WoSCheckpointError("fresh_starter_client_required")
    # Both positive limits remain in force. This worker exclusively uses the
    # fresh client; never raise its allowance to match the worker's default.
    session_request_budget = min(max_requests, client.requests_remaining)
    validate_wos_checkpoint(project, query_id)
    before = inspect_wos_checkpoint(project, query_id)
    token = _claim(project, query_id, _stamp(now()), revalidate_quota=revalidate_quota)
    if token is None:
        return inspect_wos_checkpoint(project, query_id)
    used = 0

    def request(purpose: str, number: int, size: int) -> None:
        nonlocal used
        with _db(project) as db:
            plan = _job(db, project, query_id)["plan"]
        attempt = _reserve(project, query_id, token, purpose, number, size, _stamp(now()))
        previous_attempts = client.requests_made
        used += 1  # Reserve budget BEFORE any network access or callback.
        try:
            page = client.fetch_page(plan["exact_query"], database=plan["database"], page=number, limit=size)
        except WoSStarterError as exc:
            _failure(project, query_id, token, attempt, client, exc, _stamp(now()),
                     client.requests_made > previous_attempts)
            return
        delay = client.retry_after_remaining
        stamp = _stamp(now())
        # Persist the strongest restriction with the response, before a pause,
        # cancellation or final completion can skip the loop's quota check.
        quota_delay = 3600 if page.quota.daily_remaining == 0 else 0
        next_allowed = _after(stamp, max(1.05, delay, quota_delay))
        _accept(project, query_id, token, attempt, page, stamp, next_allowed)
        if quota_delay:
            _pause(project, query_id, token, stamp, "quota_revalidation_required",
                   minimum_delay=max(delay, quota_delay))
        elif delay > 0:
            _pause(project, query_id, token, stamp, "server_retry_after", minimum_delay=delay)

    try:
        if before.reported_matches is not None:
            request("probe", 1, 1)
        while True:
            state = inspect_wos_checkpoint(project, query_id)
            if on_progress is not None:
                on_progress(state)
                state = inspect_wos_checkpoint(project, query_id)
            if state.status != "running":
                break
            if used and not client.quota.can_continue:
                _pause(project, query_id, token, _stamp(now()), "quota_revalidation_required", minimum_delay=3600)
                break
            if used >= session_request_budget:
                _pause(project, query_id, token, _stamp(now()), "session_budget_reached")
                break
            with _db(project) as db:
                job = _job(db, project, query_id)
            if job["stage"] == "acquire":
                request("acquire", job["next_page"], job["plan"]["page_size"])
            elif job["stage"] == "verify":
                request("verify", job["verify_page"], job["plan"]["page_size"])
            elif job["stage"] == "final":
                # Recheck local durable integrity before the final provider probe.
                validate_wos_checkpoint(project, query_id)
                request("final", 1, 1)
            else:
                raise WoSCheckpointError("unexpected_worker_stage")
    except sqlite3.DatabaseError:
        # The failed response transaction rolls back. Its earlier reservation
        # remains outcome-unknown, so explicit crash recovery is required.
        raise WoSCheckpointError("checkpoint_write_failed") from None
    except WoSCheckpointError as exc:
        if str(exc) != "worker_paused":
            raise
    finally:
        _release(project, query_id, token)
    result = inspect_wos_checkpoint(project, query_id)
    if result.enumeration_reconciled:
        validate_wos_checkpoint(project, query_id)
    return result
