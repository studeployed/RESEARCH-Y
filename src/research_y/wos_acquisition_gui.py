"""Explicitly authorised, bounded Starter acquisition using the existing ledger.

This is a trust boundary, not a second paging algorithm: the durable WoS
checkpoint store and quota-aware runner own all provider requests and records.
No network call occurs while inspecting or preparing a checkpoint.
"""
from __future__ import annotations

from dataclasses import asdict
from uuid import UUID

from research_y.projects import Project
from research_y.wos_checkpoint_store import (
    WoSCheckpointError, _db, _job, create_wos_checkpoint,
    inspect_wos_checkpoint,
)
from research_y.wos_checkpoint_runner import run_wos_checkpoint
from research_y.wos_starter_client import WoSStarterClient

MAX_SESSION_REQUESTS = 3
# Maximum ONE explicitly confirmed uninterrupted verification session.
# Includes the resume count/identity probe and final count probe.
MAX_VERIFY_REQUESTS = 512
SAFE_ERRORS = frozenset((
    "pending_wos_query_required", "source_plan_unverified",
    "checkpoint_already_exists", "unknown_checkpoint",
    "checkpoint_identity_mismatch", "strategy_identity_mismatch",
    "invalid_checkpoint_plan", "checkpoint_write_failed",
    "worker_busy_or_interrupted", "another_wos_worker_active",
    "invalid_session_request_budget", "fresh_starter_client_required",
    "local_retention_not_authorized", "unsupported_query_parameters",
    "query_not_in_approved_compilation",
))


class WoSAcquisitionError(ValueError):
    def __init__(self, code="source_execution_unavailable"):
        self.code = code if code in SAFE_ERRORS | {
            "invalid_identifier", "retention_confirmation_required",
            "session_confirmation_required", "gui_admission_missing",
            "source_execution_unavailable", "verification_requires_long_worker",
            "verification_not_ready", "verification_budget_exceeded",
            "verification_plan_changed", "verification_worker_recovery_required",
            "verification_worker_not_running",
        } else "source_execution_unavailable"
        super().__init__(self.code)


def _uuid(value):
    try:
        if type(value) is not str or str(UUID(value)) != value:
            raise ValueError
    except (TypeError, ValueError, AttributeError):
        raise WoSAcquisitionError("invalid_identifier") from None
    return value


def _sha(value):
    if type(value) is not str or len(value) != 64 or any(
            char not in "0123456789abcdef" for char in value):
        raise WoSAcquisitionError("source_plan_unverified")
    return value


def inspect_wos_acquisition(project: Project, *, run_id, query_id) -> dict:
    """Reopen original durable checkpoint without credentials or network."""
    _uuid(run_id)
    _uuid(query_id)
    try:
        with _db(project) as db:
            job = _job(db, project, query_id)
            plan = job["plan"]
            if plan["run_id"] != run_id or plan["source_name"] != "wos":
                raise WoSAcquisitionError("checkpoint_identity_mismatch")
            origin = plan.get("preflight_sha256")
            if origin is not None:
                _sha(origin)
            # Plan is already hash/identity checked by _job. It can originate
            # from older CLI/manual workflows, which are READABLE but not
            # silently adopted as GUI-retention-authorised sessions.
            exact_query = plan["exact_query"]
        state = inspect_wos_checkpoint(project, query_id)
    except WoSAcquisitionError:
        raise
    except WoSCheckpointError as exc:
        raise WoSAcquisitionError(str(exc)) from None
    result = dict(
        run_id=run_id, query_id=query_id, exact_query=exact_query,
        approved_gui_retention=origin is not None,
        preflight_sha256=origin,
        checkpoint=asdict(state),
        source_retrieval_verified=False,
        whole_search_verified=False,
        provider_snapshot_guaranteed=False,
        bibliographic_metadata_complete=False,
        no_network_requests=True,
        max_next_session_requests=MAX_SESSION_REQUESTS,
    )
    # Never surface licensed record payload or credentials in a status read.
    return result


def preview_wos_acquisition(project: Project, *, run_id, query_id) -> dict:
    """Verify one still-pending source query against the frozen complete OR plan.

    Sibling query counts/statuses may have progressed, but the original
    approved group expressions and snapshot hash must still reconcile.
    This operation is read-only and cannot submit source requests.
    """
    _uuid(run_id)
    _uuid(query_id)
    from research_y.preflight_review import _inspect, PreflightError
    try:
        with _db(project) as db:
            summary = _inspect(db, run_id, allow_started=True)
            matches = [q for src in summary['sources']
                       if src['source_name'] == 'wos'
                       for q in src['queries']
                       if q['query_id'] == query_id]
            if len(matches) != 1:
                raise WoSAcquisitionError('source_plan_unverified')
            live = db.execute('SELECT status FROM source_queries WHERE query_id=? AND run_id=?',
                              (query_id,run_id)).fetchone()
            if live is None or live[0] != 'pending':
                raise WoSAcquisitionError('pending_wos_query_required')
            # Existing CLI/manual checkpoints may leave the source-query
            # status pending. A GUI must view them, never assume this
            # confirms new GUI retention. Admission also checks under its
            # own BEGIN IMMEDIATE transaction to close the race.
            existing = db.execute(
                'SELECT 1 FROM wos_checkpoint_jobs WHERE query_id=?',
                (query_id,)).fetchone() is not None
            return dict(run_id=run_id,query_id=query_id,
                        exact_query=matches[0]['exact_query'],
                        group_id=matches[0]['group_id'],
                        plan_sha256=summary['plan_sha256'],
                        checkpoint_exists=existing,
                        source_retrieval_verified=False,no_network_requests=True)
    except PreflightError:
        raise WoSAcquisitionError('source_plan_unverified') from None



def prepare_wos_acquisition(
    project: Project, *, run_id, query_id, expected_plan_sha256,
    retention_authorized, confirmed,
) -> dict:
    """Persist one immutable, source-verified authorised record-retention plan.

    Retention consent and exact pending whole-run preflight are checked before
    any data is retained. This preparation is offline and idempotent by
    checkpoint identity through the separate read operation after lost replies.
    """
    _uuid(run_id)
    _uuid(query_id)
    _sha(expected_plan_sha256)
    if confirmed is not True or retention_authorized is not True:
        raise WoSAcquisitionError("retention_confirmation_required")
    try:
        create_wos_checkpoint(
            project, query_id, retention_authorized=True,
            expected_run_id=run_id, expected_plan_sha256=expected_plan_sha256)
    except WoSCheckpointError as exc:
        raise WoSAcquisitionError(str(exc)) from None
    evidence = inspect_wos_acquisition(project, run_id=run_id, query_id=query_id)
    if evidence["preflight_sha256"] != expected_plan_sha256:
        raise WoSAcquisitionError("source_plan_unverified")
    return evidence


def run_wos_acquisition_session(
    project: Project, *, run_id, query_id, confirmed, client: WoSStarterClient,
    revalidate_quota=False,
) -> dict:
    """At most THREE provider requests per manually confirmed worker invocation.

    There are NO automatic retries. On interruption, only read the existing
    checkpoint: an unknown in-flight request must not be silently resent.
    """
    if confirmed is not True or type(revalidate_quota) is not bool:
        raise WoSAcquisitionError("session_confirmation_required")
    if type(client) is not WoSStarterClient or client.requests_made != 0:
        raise WoSAcquisitionError("session_confirmation_required")
    initial = inspect_wos_acquisition(project, run_id=run_id, query_id=query_id)
    job = initial["checkpoint"]
    # The existing identity-verification epoch restarts on every session.
    # Short sessions cannot certify multi-page verification/final count,
    # and MUST NOT spend quota repeating that same first verification page.
    if (job["pages_expected"] is not None and job["pages_expected"] > 1
            and job["stage"] in ("verify", "final")):
        raise WoSAcquisitionError("verification_requires_long_worker")
    if not initial["approved_gui_retention"]:
        raise WoSAcquisitionError("gui_admission_missing")
    try:
        run_wos_checkpoint(
            project, query_id, client,
            max_requests=MAX_SESSION_REQUESTS,
            revalidate_quota=revalidate_quota)
    except WoSCheckpointError as exc:
        raise WoSAcquisitionError(str(exc)) from None
    result = inspect_wos_acquisition(project, run_id=run_id, query_id=query_id)
    # A tick is network-capable, but a guarded/no-op session may make zero
    # actual requests. Preserve the observed transport count accurately.
    result['no_network_requests'] = client.requests_made == 0
    result['session_requests_made'] = client.requests_made
    result['session_confirmed'] = True
    return result



def preview_wos_verification(project: Project, *, run_id, query_id) -> dict:
    """Read a fully acquired checkpoint and determine the *exact* bounded sweep.

    A completed multi-page verification requires an uninterrupted session:
    count/first-identity recheck (1), all captured pages (N), final recheck (1).
    No provider calls, new checkpoint, unlocked quota or invented completion.
    """
    evidence = inspect_wos_acquisition(project, run_id=run_id, query_id=query_id)
    job = evidence["checkpoint"]
    if not evidence["approved_gui_retention"]:
        raise WoSAcquisitionError("gui_admission_missing")
    if job["worker_active"] is True or job["requests_unknown"] != 0:
        raise WoSAcquisitionError("verification_worker_recovery_required")
    if (job["status"] in ("completed_with_warnings", "cancelled") or
            job["stage"] not in ("verify", "final") or
            job["pages_expected"] is None or
            type(job["pages_expected"]) is not int or
            job["pages_expected"] < 1 or
            type(job["reported_matches"]) is not int or
            job["records_committed"] != job["reported_matches"] or
            job["pages_committed"] != job["pages_expected"]):
        raise WoSAcquisitionError("verification_not_ready")
    necessary = job["pages_expected"] + 2
    if necessary > MAX_VERIFY_REQUESTS:
        raise WoSAcquisitionError("verification_budget_exceeded")
    return dict(run_id=run_id, query_id=query_id,
                exact_query=evidence["exact_query"],
                preflight_sha256=evidence["preflight_sha256"],
                stage=job["stage"], pages_to_verify=job["pages_expected"],
                expected_requests=necessary,
                max_session_requests=MAX_VERIFY_REQUESTS,
                reported_matches=job["reported_matches"],
                source_retrieval_verified=False,
                provider_snapshot_guaranteed=False,
                whole_search_verified=False,
                no_network_requests=True)


def run_wos_verification_session(
    project: Project, *, run_id, query_id, expected_plan_sha256,
    expected_requests, confirmed, revalidate_quota,
    client: WoSStarterClient,
) -> dict:
    """One supervised explicit verification session, with fixed maximum budget.

    Every source request is still journalled/guarded by run_wos_checkpoint.
    An unavailable quota, network error or interruption cannot be translated
    into a success. The parent must read the original checkpoint separately.
    """
    _sha(expected_plan_sha256)
    if confirmed is not True or type(revalidate_quota) is not bool:
        raise WoSAcquisitionError("session_confirmation_required")
    if (type(expected_requests) is not int or
            not 3 <= expected_requests <= MAX_VERIFY_REQUESTS):
        raise WoSAcquisitionError("session_confirmation_required")
    if (type(client) is not WoSStarterClient or
            client.requests_made != 0 or
            client.requests_remaining < expected_requests):
        raise WoSAcquisitionError("session_confirmation_required")
    current = preview_wos_verification(
        project, run_id=run_id, query_id=query_id)
    if (current["preflight_sha256"] != expected_plan_sha256 or
            current["expected_requests"] != expected_requests):
        raise WoSAcquisitionError("verification_plan_changed")
    try:
        result = run_wos_checkpoint(
            project, query_id, client, max_requests=expected_requests,
            revalidate_quota=revalidate_quota)
    except WoSCheckpointError as exc:
        raise WoSAcquisitionError(str(exc)) from None
    read = inspect_wos_acquisition(project, run_id=run_id, query_id=query_id)
    return dict(run_id=run_id, query_id=query_id,
                preflight_sha256=current["preflight_sha256"],
                expected_requests=expected_requests,
                session_requests_made=client.requests_made,
                actual_checkpoint=read["checkpoint"],
                enumeration_reconciled=result.enumeration_reconciled,
                no_network_requests=client.requests_made == 0,
                source_retrieval_verified=False,
                whole_search_verified=False,
                provider_snapshot_guaranteed=False)



def pause_wos_verification_session(project: Project, *, run_id, query_id) -> dict:
    """Request graceful pause without sending any provider call.

    A currently in-flight page can still finish. The source worker checks the
    paused checkpoint between requests and releases its ownership only after
    it exits. The host must independently confirm worker termination; this
    receipt alone never establishes a stopped process.
    """
    evidence = inspect_wos_acquisition(project, run_id=run_id, query_id=query_id)
    if not evidence["approved_gui_retention"]:
        raise WoSAcquisitionError("gui_admission_missing")
    # A freshly submitted child can still be before _claim(). A pause there
    # would otherwise be overwritten by the subsequent acquisition claim.
    # Require an established durable owner before acknowledging the request.
    if evidence["checkpoint"]["worker_active"] is not True:
        raise WoSAcquisitionError("verification_worker_not_running")
    from research_y.wos_checkpoint_store import pause_wos_checkpoint
    try:
        pause_wos_checkpoint(project, query_id)
    except WoSCheckpointError as exc:
        raise WoSAcquisitionError(str(exc)) from None
    return inspect_wos_acquisition(project, run_id=run_id, query_id=query_id)
