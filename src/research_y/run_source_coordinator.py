"""Explicit, supervised whole-run progress through ALREADY AUTHORISED source jobs.

One confirmation covers at most TWO pre-existing query checkpoints. It does not
prepare WoS retention, invent PubMed partition coverage, restart unknown
requests, silently revalidate quotas or schedule unattended work. Existing
source engines remain responsible for transport, paging, durable commits,
backoff, and incompleteness. No new provider or publication-count algorithm.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import time

from research_y.projects import Project
from research_y.run_execution_board import read_run_execution_board, ExecutionBoardError
from research_y import pubmed_source_gui as pubmed_ids
from research_y import pubmed_metadata_gui as pubmed_metadata
from research_y import wos_acquisition_gui as wos
from research_y.pubmed_probe import PubMedESearchProbeClient
from research_y.pubmed_metadata import PubMedEFetchClient
from research_y.wos_starter_client import WoSStarterClient
from research_y.wos_checkpoint_store import (
    _db as _wos_db, _provider_hold as _wos_provider_hold,
    _stamp as _wos_stamp, WoSCheckpointError,
)

METHOD = "supervised-run-source-coordination/1"
MAX_COORDINATED_STEPS = 2
MAX_COORDINATED_WOS_VERIFY_REQUESTS = 24
# The ceilings are pre-existing service budgets, NOT limits on search results.
PER_STEP_REQUESTS = {
    "pubmed_identifiers_resume": pubmed_ids.MAX_PUBMED_REQUESTS,
    "pubmed_metadata": pubmed_metadata.MAX_METADATA_BATCHES,
    "wos_acquire": wos.MAX_SESSION_REQUESTS,
}
ELIGIBLE_ACTIONS = frozenset((*PER_STEP_REQUESTS, "wos_verify"))


class RunCoordinationError(ValueError):
    """Static errors only: never return provider errors, secrets or record text."""

    def __init__(self, code="run_coordination_unavailable"):
        self.code = code if code in (
            "run_coordination_unavailable", "run_coordination_stale",
            "run_coordination_invalid", "run_coordination_confirmation_required",
            "run_coordination_credentials_required", "run_coordination_no_work",
        ) else "run_coordination_unavailable"
        super().__init__(self.code)


def _digest(value) -> str:
    return sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False).encode("utf-8")).hexdigest()


def _task(project: Project, run_id: str, row: dict) -> tuple[dict | None, str | None]:
    """Classify ONE source from existing evidence; no network or writes."""
    from research_y.wos_checkpoint_store import WoSCheckpointError
    query_id = row["query_id"]
    source = row["source_name"]
    stage = row["source_stage"]
    common = dict(query_id=query_id, source_name=source,
                  group_id=row["group_id"], exact_query=row["exact_query"])
    try:
        if source == "pubmed" and stage in (
                "pubmed_identifier_paused", "pubmed_identifiers_incomplete"):
            p = pubmed_ids.preview_pubmed_source(
                project, run_id=run_id, query_id=query_id)
            checkpoint = p["checkpoint"]
            if (checkpoint is None or checkpoint.get("coverage") is None or
                    checkpoint.get("resume_budget_sufficient") is not True or
                    checkpoint["status"] == "identifiers_reconciled_metadata_pending"):
                return None, "manual_pubmed_checkpoint_recovery_required"
            dates = checkpoint["coverage"]
            if (type(dates.get("start")) is not str or
                    type(dates.get("end")) is not str):
                return None, "manual_pubmed_checkpoint_recovery_required"
            return dict(common, action="pubmed_identifiers_resume",
                        preflight_sha256=p["plan_sha256"],
                        coverage_start=dates["start"],
                        coverage_end=dates["end"],
                        max_requests=PER_STEP_REQUESTS["pubmed_identifiers_resume"]), None
        if source == "pubmed" and stage == "pubmed_metadata_needed":
            p = pubmed_metadata.preview_pubmed_metadata(
                project, run_id=run_id, query_id=query_id)
            if (p.get("identifier_checkpoint_reconciled") is not True or
                    p.get("metadata_records_reconciled") is not False or
                    type(p.get("metadata_records_pending")) is not int or
                    p["metadata_records_pending"] <= 0):
                return None, "manual_pubmed_metadata_review_required"
            return dict(common, action="pubmed_metadata",
                        preflight_sha256=p["plan_sha256"],
                        records_to_fetch=p["metadata_records_pending"],
                        max_requests=PER_STEP_REQUESTS["pubmed_metadata"]), None
        if source == "wos" and stage in (
                "wos_acquisition_incomplete", "wos_verification_needed"):
            evidence = wos.inspect_wos_acquisition(
                project, run_id=run_id, query_id=query_id)
            checkpoint = evidence["checkpoint"]
            if (not evidence["approved_gui_retention"] or
                    evidence["preflight_sha256"] is None):
                return None, "manual_wos_retention_consent_required"
            if (checkpoint["worker_active"] or checkpoint["requests_unknown"] or
                    checkpoint["status"] in ("cancelled", "incomplete", "failed") or
                    checkpoint["reason_code"] in (
                        "quota_revalidation_required",
                        "entitlement_unverified", "server_retry_after",
                        "provider_quota_revalidation_required")):
                return None, "manual_wos_recovery_or_quota_review_required"
            if checkpoint["reason_code"] == "provider_cooldown":
                deadline = checkpoint["not_before_utc"]
                try:
                    if (deadline is None or
                            datetime.fromisoformat(deadline) >
                            datetime.now(timezone.utc)):
                        return None, "manual_wos_recovery_or_quota_review_required"
                except (ValueError, TypeError):
                    return None, "manual_wos_recovery_or_quota_review_required"
            if stage == "wos_acquisition_incomplete":
                return dict(common, action="wos_acquire",
                            preflight_sha256=evidence["preflight_sha256"],
                            max_requests=PER_STEP_REQUESTS["wos_acquire"]), None
            p = wos.preview_wos_verification(
                project, run_id=run_id, query_id=query_id)
            requests = p["expected_requests"]
            if requests > MAX_COORDINATED_WOS_VERIFY_REQUESTS:
                return None, "manual_long_wos_verification_required"
            return dict(common, action="wos_verify",
                        preflight_sha256=evidence["preflight_sha256"],
                        max_requests=requests), None
        if source == "wos" and stage in (
                "wos_worker_or_recovery_active", "wos_request_outcome_unknown"):
            return None, "manual_wos_worker_recovery_required"
        if source == "pubmed" and stage == "pubmed_identifiers_not_started":
            return None, "manual_pubmed_date_coverage_approval_required"
        if source == "wos" and stage == "wos_not_started":
            return None, "manual_wos_retention_consent_required"
        return None, "no_automatic_next_step_available"
    except (wos.WoSAcquisitionError, pubmed_ids.PubMedSourceError,
            pubmed_metadata.PubMedMetadataGUIError, WoSCheckpointError,
            ValueError, KeyError, TypeError):
        # A stored source error is NOT permission to make a fresh request.
        return None, "manual_source_evidence_review_required"


def preview_run_coordination(project: Project, *, run_id: str) -> dict:
    """Truthful queue: all tasks are ALREADY admitted to their source service.

    A preview is a proposal, not network authorisation. Every source query is
    shown, including blockers requiring manual date/retention/quota recovery.
    """
    try:
        board = read_run_execution_board(project, run_id)
        ordered = sorted(board["queries"], key=lambda q: (
            q["group_id"], q["source_name"], q["query_id"]))
        eligible, blocked = [], []
        for row in ordered:
            task, reason = _task(project, run_id, row)
            if task is not None:
                eligible.append(task)
            else:
                blocked.append(dict(
                    query_id=row["query_id"], group_id=row["group_id"],
                    source_name=row["source_name"], exact_query=row["exact_query"],
                    source_stage=row["source_stage"], blocker=reason))
        board_revision = board["revision"]
        digest = _digest([METHOD, str(project.identifier), run_id,
                          board_revision, eligible, blocked])
        return dict(method=METHOD, project_id=str(project.identifier), run_id=run_id,
                    board_revision=board_revision, plan_sha256=digest,
                    eligible_tasks=eligible, blocked_tasks=blocked,
                    max_session_steps=MAX_COORDINATED_STEPS,
                    source_retrieval_verified=False,
                    whole_search_verified=False, no_network_requests=True)
    except RunCoordinationError:
        raise
    except (ExecutionBoardError, ValueError, KeyError, TypeError,
            OverflowError, RecursionError):
        raise RunCoordinationError("run_coordination_unavailable") from None


def _validate_approved_steps(preview: dict, tasks: tuple) -> None:
    if (type(tasks) is not tuple or
            not 1 <= len(tasks) <= MAX_COORDINATED_STEPS or
            any(type(t) is not dict for t in tasks)):
        raise RunCoordinationError("run_coordination_invalid")
    allowed = preview["eligible_tasks"]
    index = -1
    for task in tasks:
        if (task.get("action") not in ELIGIBLE_ACTIONS or
                task not in allowed):
            raise RunCoordinationError("run_coordination_invalid")
        next_index = allowed.index(task)
        if next_index <= index:
            raise RunCoordinationError("run_coordination_invalid")
        index = next_index


def _source_step(project, run_id, task, *, wos_key, pubmed_client):
    """Execute the ORIGINAL bounded service; do not catch provider content."""
    qid, action = task["query_id"], task["action"]
    if action.startswith("wos_"):
        if wos_key is None:
            raise RunCoordinationError("run_coordination_credentials_required")
        if action == "wos_acquire":
            client = WoSStarterClient(
                api_key=wos_key, request_budget=3, timeout=10)
            receipt = wos.run_wos_acquisition_session(
                project, run_id=run_id, query_id=qid, confirmed=True,
                client=client, revalidate_quota=False)
            state = receipt["checkpoint"]
            spent = receipt["session_requests_made"]
            uncertain = bool(state["worker_active"] or state["requests_unknown"])
            halted = (uncertain or spent == 0 or
                      state["status"] in ("incomplete", "failed") or
                      state["reason_code"] not in (
                          "session_budget_reached", "in_progress",
                          "enumeration_reconciled_snapshot_unavailable"))
            return dict(query_id=qid,source_name="wos",action=action,
                        source_status=state["status"], requests_made=spent,
                        records_committed=state["records_committed"],
                        identifiers_reconciled=state["enumeration_reconciled"],
                        stop_required=halted, outcome_uncertain=uncertain)
        client = WoSStarterClient(
            api_key=wos_key, request_budget=task["max_requests"], timeout=10)
        receipt = wos.run_wos_verification_session(
            project, run_id=run_id, query_id=qid,
            expected_plan_sha256=task["preflight_sha256"],
            expected_requests=task["max_requests"], confirmed=True,
            revalidate_quota=False, client=client)
        state = receipt["actual_checkpoint"]
        spent = receipt["session_requests_made"]
        uncertain = bool(state["worker_active"] or state["requests_unknown"])
        return dict(query_id=qid,source_name="wos",action=action,
                    source_status=state["status"], requests_made=spent,
                    records_committed=state["records_committed"],
                    identifiers_reconciled=state["enumeration_reconciled"],
                    stop_required=uncertain or spent == 0 or
                        not state["enumeration_reconciled"],
                    outcome_uncertain=uncertain)
    if pubmed_client is None:
        raise RunCoordinationError("run_coordination_credentials_required")
    esearch = pubmed_client
    if action == "pubmed_identifiers_resume":
        receipt = pubmed_ids.run_pubmed_source_session(
            project, run_id=run_id, query_id=qid,
            expected_plan_sha256=task["preflight_sha256"],
            coverage_start=task["coverage_start"],
            coverage_end=task["coverage_end"],
            confirmed=True, client=esearch)
        state = receipt["checkpoint"]
        # This legacy transport has no per-request outcome journal.
        # An incomplete identifier session needs explicit user review.
        complete = receipt["status"] == "identifiers_reconciled_metadata_pending"
        return dict(query_id=qid,source_name="pubmed",action=action,
                    source_status=receipt["status"],
                    requests_made=receipt["session_requests_reserved"],
                    identifiers_committed=(
                        None if state is None else state["identifiers_committed"]),
                    stop_required=not complete, outcome_uncertain=not complete)
    if action == "pubmed_metadata":
        receipt = pubmed_metadata.run_pubmed_metadata_session(
            project, run_id=run_id, query_id=qid,
            expected_plan_sha256=task["preflight_sha256"],
            confirmed=True, client=PubMedEFetchClient(esearch))
        uncertain = receipt["unknown_inflight_request_possible"]
        done = receipt["status"] == "metadata_acquired_reconciliation_pending"
        # A deliberate 100-batch stop can be continued only by a NEW
        # confirmed session. It is not a failure requiring provider retry.
        deliberate_budget_stop = (receipt["status"] == "incomplete" and
                                  not uncertain and
                                  receipt["successful_batches"] ==
                                  pubmed_metadata.MAX_METADATA_BATCHES)
        return dict(query_id=qid,source_name="pubmed",action=action,
                    source_status=receipt["status"],
                    # The collector counts *successful* commits, not failed
                    # POST attempts. Never label a possibly delivered HTTP
                    # request as a known number of transport calls.
                    requests_made=(None if uncertain else
                                   receipt["successful_batches"]),
                    successful_batches=receipt["successful_batches"],
                    metadata_records_committed=receipt["metadata_records_committed"],
                    metadata_records_pending=receipt["metadata_records_pending"],
                    stop_required=uncertain or not (done or deliberate_budget_stop),
                    outcome_uncertain=uncertain)
    raise RunCoordinationError("run_coordination_invalid")


def _await_ordinary_wos_pacing(project: Project) -> bool:
    """Bounded 1.05s Starter spacing, NOT automatic quota revalidation.

    The original project-wide source guard owns deadlines from all Starter
    queries and pilots. Only a short ordinary inter-request delay (<=2s)
    may be waited automatically inside an already confirmed session. A
    longer server Retry-After, daily quota hold or unknown attempt MUST stop
    the coordinator without sending another request.
    """
    try:
        with _wos_db(project) as db:
            hold, deadline = _wos_provider_hold(
                db, _wos_stamp(datetime.now(timezone.utc)),
                revalidate_quota=False)
        if hold is None:
            return True
        if hold != "provider_cooldown" or deadline is None:
            return False
        delta = (datetime.fromisoformat(deadline) -
                 datetime.now(timezone.utc)).total_seconds()
        if not 0 < delta <= 2.0:
            return False
        time.sleep(delta + 0.08)
        with _wos_db(project) as db:
            hold, _ = _wos_provider_hold(
                db, _wos_stamp(datetime.now(timezone.utc)),
                revalidate_quota=False)
        return hold is None
    except (WoSCheckpointError, ValueError, TypeError, OverflowError):
        # A damaged provider clock or unknown quota is not clearance.
        return False


def run_coordinated_source_session(
    project: Project, *, run_id: str, expected_plan_sha256: str,
    tasks: tuple[dict, ...], confirmed: bool, wos_key: str | None,
    pubmed_email: str | None, pubmed_key: str | None,
) -> dict:
    """One bounded, confirmed two-job sequence, foreground app lifetime only.

    The whole-run board is rechecked BEFORE the first source call; every
    subsequent target's admission/plan is independently reverified. Stop
    after the first uncertain/error/quota outcome; never retry automatically.
    """
    if (confirmed is not True or type(expected_plan_sha256) is not str or
            len(expected_plan_sha256) != 64 or
            any(c not in "0123456789abcdef" for c in expected_plan_sha256)):
        raise RunCoordinationError("run_coordination_confirmation_required")
    preview = preview_run_coordination(project, run_id=run_id)
    if preview["plan_sha256"] != expected_plan_sha256:
        raise RunCoordinationError("run_coordination_stale")
    _validate_approved_steps(preview, tasks)
    if any(t["source_name"] == "wos" for t in tasks):
        if type(wos_key) is not str:
            raise RunCoordinationError("run_coordination_credentials_required")
        # Validate the original client without making requests.
        WoSStarterClient(api_key=wos_key, request_budget=3, timeout=10)
    # One ESearch client for the whole confirmed session: ESearch and EFetch
    # share the same per-account pacing deadline ACROSS coordinated stages.
    # Constructing a fresh client for each query would reset its limiter.
    pubmed_client = None
    if any(t["source_name"] == "pubmed" for t in tasks):
        if type(pubmed_email) is not str or (
                pubmed_key is not None and type(pubmed_key) is not str):
            raise RunCoordinationError("run_coordination_credentials_required")
        pubmed_client = PubMedESearchProbeClient(
            email=pubmed_email, api_key=pubmed_key, timeout=15)
    receipts = []
    stopped_reason = None
    previous_task = None
    for task in tasks:
        if (previous_task is not None and
                previous_task["source_name"] == "wos" and
                task["source_name"] == "wos" and
                not _await_ordinary_wos_pacing(project)):
            stopped_reason = "provider_cooldown_requires_later_session"
            break
        # The previous source changed the board revision, by design. Check
        # THIS untouched target instead of rejecting a legitimate next step.
        try:
            current_board = read_run_execution_board(project, run_id)
            matches = [q for q in current_board["queries"]
                       if q["query_id"] == task["query_id"]]
            if len(matches) != 1:
                stopped_reason = "target_source_changed"
                break
            current, blocked = _task(project, run_id, matches[0])
            if current != task or blocked is not None:
                stopped_reason = "target_source_changed"
                break
            result = _source_step(
                project, run_id, task, wos_key=wos_key,
                pubmed_client=pubmed_client)
        except RunCoordinationError:
            stopped_reason = "source_step_refused"
            break
        except Exception:
            # No untrusted source or transport error details in results.
            # The original source journal may retain a still-unknown attempt.
            stopped_reason = "source_step_failed_or_uncertain"
            break
        receipts.append(result)
        previous_task = task
        if result["stop_required"]:
            stopped_reason = ("source_outcome_uncertain" if
                              result["outcome_uncertain"] else
                              "source_step_requires_review")
            break
    final_board = read_run_execution_board(project, run_id)
    return dict(method=METHOD, project_id=str(project.identifier),
                run_id=run_id, plan_sha256=expected_plan_sha256,
                planned_step_count=len(tasks), dispatched_step_count=len(receipts),
                steps=receipts,
                stopped_reason=stopped_reason,
                new_board_revision=final_board["revision"],
                no_automatic_retry=True, source_retrieval_verified=False,
                whole_search_verified=False, verified_complete=False,
                global_unique_publications=None,
                # No idle user action or passive refresh calls this worker.
                session_confirmed=True)
