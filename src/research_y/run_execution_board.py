"""Read-only whole-run execution board over existing PubMed and WoS evidence.

This is a navigation and source-stage view, NOT a new retrieval engine, worker
scheduler, deduplication verdict or provider completeness certificate. All
source and group evidence comes from one validated SQLite read transaction.
"""
from __future__ import annotations

from dataclasses import asdict
import sqlite3

from research_y.application_inspection import _read, ApplicationInspectionError
from research_y import result_counts
from research_y.reviewed_master import retained_union
from research_y.preflight_review import _matched_query_plan, PreflightError
from research_y.pubmed_checkpoint_store import _snapshot_from_db, CheckpointIntegrityError
from research_y.pubmed_metadata_store import iter_retained_efetch_records
from research_y.pubmed_cooldown import retry_not_before
from research_y.wos_checkpoint_store import _job, _validate_verification_receipts, WoSCheckpointError
from research_y.publication_identity import _hash, _identifier

METHOD = "whole-run-execution-board/1"
SOURCES = frozenset(("pubmed", "wos"))


class ExecutionBoardError(ValueError):
    """Static, display-safe error codes. No path, query or private record text."""

    def __init__(self, code="run_board_unavailable"):
        self.code = code if code in (
            "run_board_unavailable", "run_board_invalid",
            "run_board_unknown_run", "run_board_stale",
        ) else "run_board_unavailable"
        super().__init__(self.code)


def _pubmed(db, run_id, query, counts):
    qid = query["query_id"]
    exists = db.execute(
        "SELECT 1 FROM pubmed_checkpoint_runs WHERE query_id=?", (qid,)
    ).fetchone() is not None
    if not exists:
        if counts["retrieved_source_records"] or counts["metadata_source_records"]:
            return "pubmed_unreconciled_legacy", "inspect_pubmed", None, None, None, (
                "provider_checkpoint_missing_for_materialised_record",)
        return "pubmed_identifiers_not_started", "inspect_pubmed", None, None, None, ()
    checkpoint = _snapshot_from_db(db, qid)
    if checkpoint.query_id != qid or len(checkpoint.pmids) != counts["retrieved_source_records"]:
        raise ExecutionBoardError("run_board_invalid")
    if counts["metadata_source_records"] > len(checkpoint.pmids):
        raise ExecutionBoardError("run_board_invalid")
    if checkpoint.stored_status == "paused":
        stage, action = "pubmed_identifier_paused", "inspect_pubmed"
    elif (checkpoint.stored_status == "identifiers_reconciled_metadata_pending" and
          checkpoint.identifiers_reconciled):
        if counts["metadata_source_records"]:
            retained = sum(1 for _ in iter_retained_efetch_records(db, qid, run_id))
            if retained != counts["metadata_source_records"]:
                raise ExecutionBoardError("run_board_invalid")
        if not checkpoint.pmids:
            stage, action = "pubmed_no_identifiers", "inspect_pubmed"
        elif counts["metadata_source_records"] == len(checkpoint.pmids):
            stage, action = "pubmed_metadata_acquired", "inspect_pubmed_metadata"
        else:
            stage, action = "pubmed_metadata_needed", "preview_pubmed_metadata"
    else:
        stage, action = "pubmed_identifiers_incomplete", "inspect_pubmed"
    return stage, action, checkpoint.pages_committed, checkpoint.pages_expected, None, ()


def _wos(db, project, query, counts):
    qid = query["query_id"]
    exists = db.execute(
        "SELECT 1 FROM wos_checkpoint_jobs WHERE query_id=?", (qid,)
    ).fetchone() is not None
    if not exists:
        if counts["retrieved_source_records"] or counts["metadata_source_records"]:
            return "wos_unreconciled_legacy", "inspect_wos", None, None, None, (
                "provider_checkpoint_missing_for_materialised_record",)
        return "wos_not_started", "preview_wos", None, None, None, ()
    # Only the original checkpoint store validates the immutable job plan.
    # Temporarily request named columns; the caller's transaction remains open.
    factory = db.row_factory
    try:
        db.row_factory = sqlite3.Row
        job = _job(db, project, qid)
        count = job["baseline_count"]
        page_size = job["plan"]["page_size"]
        expected = None if count is None else max(1, (count + page_size - 1)//page_size)
        if job["stage"] == "done":
            _validate_verification_receipts(db, qid, job, expected)
    finally:
        db.row_factory = factory
    pages = db.execute(
        "SELECT COUNT(*) FROM wos_checkpoint_pages WHERE query_id=?", (qid,)
    ).fetchone()[0]
    committed_ids = db.execute(
        "SELECT COUNT(*) FROM wos_checkpoint_ids WHERE query_id=?", (qid,)
    ).fetchone()[0]
    verified_pages = db.execute(
        "SELECT COUNT(*) FROM wos_checkpoint_verifications "
        "WHERE query_id=? AND epoch=?", (qid, job["verify_epoch"])
    ).fetchone()[0]
    unknown = db.execute(
        "SELECT COUNT(*) FROM wos_checkpoint_attempts "
        "WHERE query_id=? AND sent IS NULL", (qid,)
    ).fetchone()[0]
    if (committed_ids != counts["retrieved_source_records"] or
            committed_ids != counts["metadata_source_records"] or
            (count is not None and count != query["reported_matches"]) or
            (expected is not None and pages > expected) or
            verified_pages > pages):
        raise ExecutionBoardError("run_board_invalid")
    if job["owner_token"] is not None:
        stage, action = "wos_worker_or_recovery_active", "inspect_wos"
    elif unknown:
        stage, action = "wos_request_outcome_unknown", "inspect_wos"
    elif job["status"] == "cancelled":
        stage, action = "wos_cancelled", "inspect_wos"
    elif job["status"] == "completed_with_warnings" and job["stage"] == "done":
        if (count is None or committed_ids != count or
                pages != expected or verified_pages != expected):
            raise ExecutionBoardError("run_board_invalid")
        stage, action = "wos_enumeration_reconciled_with_warnings", "inspect_wos"
    elif job["stage"] == "done":
        raise ExecutionBoardError("run_board_invalid")
    elif job["stage"] in ("verify", "final"):
        stage, action = "wos_verification_needed", "inspect_wos"
    elif job["stage"] == "acquire":
        stage, action = "wos_acquisition_incomplete", "inspect_wos"
    else:
        raise ExecutionBoardError("run_board_invalid")
    warnings = []
    if unknown:
        warnings.append("wos_attempt_outcome_unknown_no_automatic_retry")
    if job["owner_token"] is not None:
        warnings.append("wos_worker_or_interrupted_ownership_not_proven_stopped")
    if job["not_before_utc"] is not None:
        warnings.append("wos_provider_cooldown_may_apply")
    return stage, action, pages, expected, verified_pages, tuple(warnings)


def read_run_execution_board(project, run_id: str) -> dict:
    """One coherent source/group execution view, with NO network or writes.

    Existing result-count and provider checkpoint validators remain the single
    authority for identifiers, committed metadata, and count denominators.
    Unknown is never coalesced to zero. Identity hypotheses are never labelled
    final unique publications. Exposed next steps only select safe GUI previews
    or existing checkpoint readers; none triggers provider calls on refresh.
    """
    try:
        _identifier(run_id)
    except (TypeError, ValueError):
        raise ExecutionBoardError("run_board_invalid") from None
    try:
        with _read(project) as db:
            supplements = dict(db.execute("SELECT source_name,COUNT(*) FROM source_retrievals WHERE run_id=? "
                    "AND source_name IN ('conference_jats','conference_pdf','society','manual_bibliographic') GROUP BY source_name", (run_id,)))
            projection = (result_counts._snapshot(db, project, run_id, primary=True) if supplements else
                          result_counts._snapshot(db, project, run_id))
            snapshot = db.execute("SELECT snapshot_json FROM strategy_versions WHERE strategy_version_id=?",
                                  (projection.strategy_version_id,)).fetchone()
            if snapshot is None:
                raise ExecutionBoardError("run_board_invalid")
            try:
                plan_sha = _matched_query_plan(db, run_id, projection.strategy_version_id,
                                               snapshot[0], allow_started=True)[3]
            except PreflightError:
                plan_sha = None
            named = {}
            for group in projection.groups:
                named[group["group_id"]] = group["label"]
            count_rows = {row["query_id"]:row for row in projection.queries}
            rows = db.execute(
                "SELECT query_id,group_id,source_name,exact_query,status,"
                "reported_matches FROM source_queries WHERE run_id=? "
                "ORDER BY group_id,source_name,query_id", (run_id,)
            ).fetchall()
            if len(rows) != len(count_rows):
                raise ExecutionBoardError("run_board_invalid")
            output = []
            for qid, group_id, source, exact_query, stored_status, reported in rows:
                if (source not in SOURCES or group_id not in named or
                        qid not in count_rows or
                        count_rows[qid]["source_name"] != source or
                        count_rows[qid]["group_id"] != group_id or
                        count_rows[qid]["stored_query_status"] != stored_status or
                        count_rows[qid]["reported_matches"] != reported):
                    raise ExecutionBoardError("run_board_invalid")
                count = count_rows[qid]
                query = dict(query_id=qid, group_id=group_id,
                             source_name=source, exact_query=exact_query,
                             reported_matches=reported)
                if source == "pubmed":
                    stage, action, pages, expected, verified, warnings = _pubmed(
                        db, run_id, query, count)
                else:
                    stage, action, pages, expected, verified, warnings = _wos(
                        db, project, query, count)
                output.append(dict(
                    query_id=qid, group_id=group_id, group_label=named[group_id],
                    source_name=source, exact_query=exact_query,
                    stored_query_status=stored_status, reported_matches=reported,
                    identifiers_retrieved=count["retrieved_source_records"],
                    metadata_records_retained=count["metadata_source_records"],
                    metadata_records_missing=count["identifiers_without_metadata"],
                    count_reconciliation=count["numeric_reconciliation"],
                    pages_committed=pages, pages_expected=expected,
                    verification_pages=verified,
                    source_stage=stage, next_step=action,
                    warnings=list(warnings),
                    source_retrieval_verified=False, whole_search_verified=False))
            if set(count_rows) != {row["query_id"] for row in output}:
                raise ExecutionBoardError("run_board_invalid")
            source_rows = [dict(row) for row in projection.sources]
            totals = dict(
                source_records_by_provider={
                    row["source_name"]:row["source_unique_records"]
                    for row in source_rows},
                identifiers_missing_metadata=projection.totals["identifiers_without_metadata"],
                source_record_sum=projection.totals["source_record_sum"],
                publication_identity_hypotheses=projection.totals["global_publication_identities"],
                global_unique_publications=None,
                deduplication_complete=False)
            group_rows = []
            for group in projection.groups:
                selected = [q for q in output if q["group_id"] == group["group_id"]]
                group_rows.append(dict(
                    group_id=group["group_id"], label=group["label"],
                    sources=selected,
                    publication_identity_hypotheses=group["publication_identities"],
                    group_unique_publications=None, deduplication_complete=False))
            all_enumerated = plan_sha is not None and bool(output) and all(
                q["count_reconciliation"] == "equal" and
                q["stored_query_status"] not in ("failed", "cancelled") and
                (q["source_stage"] in (
                    "pubmed_no_identifiers", "pubmed_metadata_needed",
                    "pubmed_metadata_acquired") if q["source_name"] == "pubmed"
                 else q["source_stage"] == "wos_enumeration_reconciled_with_warnings")
                for q in output)
            all_metadata = all_enumerated and all(q["source_stage"] in (
                "pubmed_no_identifiers", "pubmed_metadata_acquired",
                "wos_enumeration_reconciled_with_warnings") for q in output)
            reviewed = retained_union(db, projection, primary=bool(supplements))
            reviewed_run_total = None
            reconciled = all_metadata and projection.stored_run_status not in ("cancelled", "failed")
            if reconciled and reviewed is not None:
                reviewed_run_total = reviewed["retained_unique_publications"]
            elif reconciled and projection.totals["source_record_sum"] == projection.totals["metadata_source_records"] == 0:
                reviewed_run_total = 0
            pubmed_deadline = retry_not_before(db)
            inputs = [METHOD, projection.revision, plan_sha, output, group_rows, totals]
            if supplements:
                inputs.append(supplements)
            if pubmed_deadline is not None:
                inputs.append(pubmed_deadline)
            revision = _hash(inputs)
            return dict(
                method=METHOD, project_id=str(project.identifier), run_id=run_id,
                strategy_version_id=projection.strategy_version_id,
                stored_run_status=projection.stored_run_status,
                revision=revision, source_count_revision=projection.revision, supplementary_source_records=supplements,
                groups=group_rows, queries=output,
                query_count=len(output), group_count=len(group_rows),
                source_totals=source_rows, totals=totals,
                approved_query_inventory_matches=plan_sha is not None,
                pubmed_retry_not_before_utc=pubmed_deadline,
                primary_source_enumerations_reconciled=all_enumerated,
                available_primary_metadata_acquired=all_metadata,
                reviewed_retained_master=reviewed,
                reconciled_primary_run_unique_publications=reviewed_run_total,
                global_unique_publications=None,
                deduplication_complete=False, source_retrieval_verified=False,
                whole_search_verified=False, verified_complete=False,
                no_network_requests=True,
                warnings=list(projection.warnings) + (
                    ["approved_query_inventory_unverified"] if plan_sha is None else []) + [
                    "execution_board_is_not_a_provider_snapshot",
                    "complete_bibliography_and_multisource_acceptance_not_verified",
                    "provisional_publication_identities_not_final_unique_count",
                ])
    except ExecutionBoardError:
        raise
    except (ApplicationInspectionError, result_counts.CountIntegrityError,
            CheckpointIntegrityError, WoSCheckpointError,
            sqlite3.Error, KeyError, ValueError, TypeError, IndexError, RecursionError):
        raise ExecutionBoardError("run_board_unavailable") from None
