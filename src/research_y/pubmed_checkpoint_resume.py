"""Resume persisted PubMed identifier partitions without refetching committed pages.

Every restart performs count/translation checks before fetching missing pages.
This never claims completed bibliography or source-level completeness.
"""

from __future__ import annotations

from research_y.projects import Project, _utc_now, _validated_project_connection
from research_y.pubmed_ids import PubMedIdentifierPage, parse_identifier_page
from research_y.pubmed_partition import DateWindow, PubMedPartitionResult, retrieve_date_partitioned_identifiers
from research_y.pubmed_probe import PubMedESearchProbeClient
from research_y.pubmed_checkpoint_store import (
    CheckpointSnapshot, CheckpointResumeResult, create_pubmed_checkpoint,
    commit_pubmed_checkpoint_page, inspect_pubmed_checkpoint,
    _load_checkpoint, _find_query, _set_checkpoint_status,
)

def _safe_probe(client: PubMedESearchProbeClient, query: str, *, internal: bool = False):
    try:
        response = client.probe(query, allow_crdt_partition=True) if internal else client.probe(query)
        if (response.review_required or type(response.reported_matches) is not int
                or response.reported_matches < 0
                or response.accepted_translation.strip() != query.strip()):
            return None
        return response
    except Exception:
        return None


def resume_pubmed_checkpoint(
    project: Project, query_id: str, client: PubMedESearchProbeClient,
) -> CheckpointResumeResult:
    """Re-check provider counts and fetch *only* missing committed-page offsets.

    Every entry is bounded by the stored page size and the 10,000-ID window.
    Returns incomplete on source drift, any request failure or lost audit.
    There are no automatic retries and no claim of complete bibliographic data.
    """
    snapshot = inspect_pubmed_checkpoint(project, query_id)
    with _validated_project_connection(project) as con:
        plan, leaves, _ = _load_checkpoint(con, query_id)
    query = plan["root_query"]

    def fail(message: str) -> CheckpointResumeResult:
        try:
            _set_checkpoint_status(
                project, query_id, "incomplete", "Provider verification incomplete",
                preserve_pause=True,
            )
        except Exception:
            # A failed status audit cannot undo previously committed pages.
            return CheckpointResumeResult(
                "incomplete", inspect_pubmed_checkpoint(project, query_id),
                "Checkpoint status update failed; earlier pages remain intact",
            )
        latest = inspect_pubmed_checkpoint(project, query_id)
        return CheckpointResumeResult(
            "paused" if latest.stored_status == "paused" else "incomplete",
            latest, message,
        )

    if snapshot.stored_status == "paused":
        try:
            _set_checkpoint_status(project, query_id, "incomplete", "Explicit resume requested")
        except Exception:
            return CheckpointResumeResult("incomplete", snapshot, "Unable to resume paused checkpoint")

    root = _safe_probe(client, query)
    if root is None or root.reported_matches != plan["root_count"]:
        return fail("PubMed root count/translation could not be reconfirmed")
    for leaf in leaves:
        expected = leaf["reported_matches"]
        if leaf["index"] >= 0:
            probe = _safe_probe(client, leaf["exact_subquery"], internal=True)
            if probe is None or probe.reported_matches != expected:
                return fail("PubMed partition count/translation changed; no pages fetched")
    for leaf in leaves:
        while True:
            snapshot = inspect_pubmed_checkpoint(project, query_id)
            if snapshot.stored_status == "paused":
                return CheckpointResumeResult("paused", snapshot, "Retrieval paused by user")
            offsets = dict(snapshot.next_offsets)
            offset = offsets[leaf["index"]]
            if offset == leaf["reported_matches"]:
                break
            requested = min(plan["page_size"], leaf["reported_matches"] - offset)
            try:
                payload = client.fetch_esearch_page(
                    leaf["exact_subquery"], retstart=offset, retmax=requested,
                )
                page = parse_identifier_page(
                    payload, exact_query=leaf["exact_subquery"],
                    retstart=offset, retmax=requested, retrieved_at_utc=_utc_now(),
                    allow_crdt_partition=leaf["index"] >= 0,
                )
                if page.review_required:
                    return fail("Provider page translation requires review")
                commit_pubmed_checkpoint_page(project, query_id, page)
            except Exception:
                return fail("PubMed page request/commit interrupted; prior checkpoints preserved")
    final = _safe_probe(client, query)
    if final is None or final.reported_matches != plan["root_count"]:
        return fail("PubMed root count/translation changed during retrieval")
    snapshot = inspect_pubmed_checkpoint(project, query_id)
    if snapshot.stored_status == "paused":
        return CheckpointResumeResult("paused", snapshot, "Retrieval paused by user")
    if not snapshot.identifiers_reconciled:
        return fail("Committed PubMed identifiers did not reconcile with source count")
    try:
        _set_checkpoint_status(
            project, query_id, "identifiers_reconciled_metadata_pending",
            "Recounted PubMed identifiers; bibliographic metadata still outstanding",
            preserve_pause=True,
        )
    except Exception:
        return CheckpointResumeResult(
            "incomplete", inspect_pubmed_checkpoint(project, query_id),
            "Final checkpoint status could not be audited; identifier pages retained",
        )
    latest = inspect_pubmed_checkpoint(project, query_id)
    if latest.stored_status == "paused":
        return CheckpointResumeResult("paused", latest, "Retrieval paused by user")
    return CheckpointResumeResult(
        "identifiers_reconciled_metadata_pending", latest,
    )


def start_checkpointed_pubmed_retrieval(
    project: Project, query_id: str, client: PubMedESearchProbeClient,
    *, date_window: DateWindow, page_size: int = 200, max_count_probes: int = 255,
) -> CheckpointResumeResult:
    """Start or resume an approved, persisted PubMed query.

    A complete partition plan is journalled *before* its first identifier
    page. The existing P1-04b collector commits each validated page via a
    callback; a crash between page fetch and commit simply re-fetches that
    uncommitted page. A reopened project instead skips committed offsets.
    """
    try:
        return resume_pubmed_checkpoint(project, query_id, client)
    except KeyError:
        pass  # The caller's source query exists, but not yet a checkpoint.
    # Do not pass any credentials, absolute project paths, or provider error
    # strings through result statuses or audit detail records.
    def on_plan(result: PubMedPartitionResult) -> None:
        create_pubmed_checkpoint(project, query_id, result, page_size=page_size)

    def on_page(page: PubMedIdentifierPage) -> None:
        snap = commit_pubmed_checkpoint_page(project, query_id, page)
        if snap.stored_status == "paused":
            # The original in-memory collector understands callback errors as
            # incomplete. We preserve the durable pause and stop its next page.
            raise RuntimeError("PubMed checkpoint paused after committed page")

    result = retrieve_date_partitioned_identifiers(
        client, _source_query_text(project, query_id), date_window=date_window,
        page_size=page_size, max_count_probes=max_count_probes,
        on_plan_ready=on_plan, on_verified_page=on_page,
    )
    try:
        snap = inspect_pubmed_checkpoint(project, query_id)
    except KeyError:
        return CheckpointResumeResult(
            "incomplete", CheckpointSnapshot(query_id, result.reported_root_matches or 0,
            "incomplete", (), 0, 0, (), False),
            "A complete checkpoint plan could not be established",
        )
    if snap.stored_status == "paused":
        return CheckpointResumeResult("paused", snap, "Retrieval paused by user")
    if not result.identifiers_reconciled:
        return CheckpointResumeResult("incomplete", snap,
                                      "Initial PubMed retrieval incomplete; checkpoint retained")
    # This repeats source-count verification, *not* already committed pages.
    return resume_pubmed_checkpoint(project, query_id, client)


def _source_query_text(project: Project, query_id: str) -> str:
    with _validated_project_connection(project) as con:
        return _find_query(con, query_id)[1]
