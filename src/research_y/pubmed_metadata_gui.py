"""Consent-gated, bounded PubMed EFetch metadata from reconciled identifier pages.

Reuse the existing EFetch parser and transactional source-record ledger. This
adapter is intentionally distinct from identifier ESearch and count pilots.
No PubMed identifiers, abstracts, source payloads or secrets reach the GUI.
"""
from __future__ import annotations

from research_y.application_inspection import _read, ApplicationInspectionError
from research_y.preflight_review import _inspect, PreflightError
from research_y.pubmed_checkpoint_store import (
    _snapshot_from_db, CheckpointIntegrityError,
)
from research_y.pubmed_metadata import (
    MAX_BATCH_IDS, PubMedEFetchClient, PubMedMetadataError,
)
from research_y.pubmed_metadata_store import (
    _known_query_records, _query_identity, collect_pubmed_metadata,
)
from research_y.pubmed_source_gui import _uuid, _sha

MAX_METADATA_BATCHES = 100
SAFE_CODES = frozenset((
    "pubmed_metadata_evidence_invalid", "pubmed_metadata_not_ready",
    "pubmed_metadata_already_acquired", "pubmed_metadata_plan_changed",
    "pubmed_metadata_confirmation_required", "pubmed_metadata_unavailable",
))


class PubMedMetadataGUIError(ValueError):
    def __init__(self, code="pubmed_metadata_unavailable"):
        self.code = code if code in SAFE_CODES else "pubmed_metadata_unavailable"
        super().__init__(self.code)


def inspect_pubmed_metadata(project, *, run_id, query_id):
    """One read-only SQLite snapshot of verified IDs and retained source metadata.

    The source records are checked against the *original* committed identifier
    index; a saved record outside the selected query is not silently counted.
    Unknown and zero are distinct. Returned payload never contains private
    bibliographic record text or PMIDs.
    """
    _uuid(run_id)
    _uuid(query_id)
    try:
        with _read(project) as db:
            from research_y.pubmed_source_gui import _query
            source = _query(db, run_id, query_id)
            checkpoint_exists = db.execute(
                "SELECT 1 FROM pubmed_checkpoint_runs WHERE query_id=?",
                (query_id,)).fetchone() is not None
            if not checkpoint_exists:
                return dict(
                    run_id=run_id, query_id=query_id,
                    exact_query=source["exact_query"],
                    status="identifiers_not_acquired",
                    identifier_count=None, metadata_records_committed=0,
                    metadata_records_pending=None,
                    abstract_present=0, abstract_not_supplied=0,
                    identifier_checkpoint_reconciled=False,
                    metadata_records_reconciled=False,
                    source_retrieval_verified=False, whole_search_verified=False,
                    no_network_requests=True,
                    max_batch_size=MAX_BATCH_IDS,
                    max_session_batches=MAX_METADATA_BATCHES)
            checkpoint = _snapshot_from_db(db, query_id)
            if (not checkpoint.identifiers_reconciled or
                    checkpoint.stored_status !=
                    "identifiers_reconciled_metadata_pending"):
                # A partial identifier run is not metadata admission.
                return dict(
                    run_id=run_id, query_id=query_id,
                    exact_query=source["exact_query"],
                    status="identifiers_not_reconciled",
                    identifier_count=None, metadata_records_committed=0,
                    metadata_records_pending=None,
                    abstract_present=0, abstract_not_supplied=0,
                    identifier_checkpoint_reconciled=False,
                    metadata_records_reconciled=False,
                    source_retrieval_verified=False, whole_search_verified=False,
                    no_network_requests=True,
                    max_batch_size=MAX_BATCH_IDS,
                    max_session_batches=MAX_METADATA_BATCHES)
            if _query_identity(db, query_id) != run_id:
                raise PubMedMetadataGUIError("pubmed_metadata_evidence_invalid")
            committed = _known_query_records(db, query_id, run_id)
            known = set(checkpoint.pmids)
            if not set(committed).issubset(known):
                raise PubMedMetadataGUIError("pubmed_metadata_evidence_invalid")
            expected = len(checkpoint.pmids)
            count = len(committed)
            # No source text is returned, only the two original EFetch
            # abstract-availability classifications and integer counts.
            import json
            abstract_present = 0
            abstract_not_supplied = 0
            for raw in committed.values():
                record = json.loads(raw)["record"]
                status = record.get("abstract_status")
                if status == "present":
                    abstract_present += 1
                elif status == "not_supplied_in_response":
                    abstract_not_supplied += 1
                else:
                    raise PubMedMetadataGUIError("pubmed_metadata_evidence_invalid")
            if expected == 0:
                state = "no_identifiers"
            elif count == expected:
                state = "metadata_acquired_reconciliation_pending"
            elif count:
                state = "metadata_partial"
            else:
                state = "metadata_not_started"
            return dict(
                run_id=run_id, query_id=query_id,
                exact_query=source["exact_query"],
                status=state, identifier_count=expected,
                metadata_records_committed=count,
                metadata_records_pending=expected-count,
                abstract_present=abstract_present,
                abstract_not_supplied=abstract_not_supplied,
                identifier_checkpoint_reconciled=True,
                metadata_records_reconciled=count==expected,
                source_retrieval_verified=False, whole_search_verified=False,
                no_network_requests=True, max_batch_size=MAX_BATCH_IDS,
                max_session_batches=MAX_METADATA_BATCHES)
    except PubMedMetadataGUIError:
        raise
    except (CheckpointIntegrityError, ApplicationInspectionError,
            PubMedMetadataError, KeyError, ValueError, TypeError):
        raise PubMedMetadataGUIError("pubmed_metadata_evidence_invalid") from None


def preview_pubmed_metadata(project, *, run_id, query_id):
    """Verify the original full-run OR plan and source identity without network."""
    saved = inspect_pubmed_metadata(project, run_id=run_id, query_id=query_id)
    if not saved["identifier_checkpoint_reconciled"]:
        raise PubMedMetadataGUIError("pubmed_metadata_not_ready")
    if saved["metadata_records_reconciled"]:
        raise PubMedMetadataGUIError("pubmed_metadata_already_acquired")
    try:
        with _read(project) as db:
            preflight = _inspect(db, run_id, allow_started=True)
            options = [q for src in preflight["sources"]
                       if src["source_name"] == "pubmed"
                       for q in src["queries"]
                       if q["query_id"] == query_id]
            if (len(options) != 1 or
                    options[0]["exact_query"] != saved["exact_query"]):
                raise PubMedMetadataGUIError("pubmed_metadata_evidence_invalid")
            return dict(**saved,plan_sha256=preflight["plan_sha256"],
                        group_id=options[0]["group_id"])
    except PubMedMetadataGUIError:
        raise
    except (ApplicationInspectionError, PreflightError,
            ValueError, KeyError, TypeError):
        raise PubMedMetadataGUIError("pubmed_metadata_evidence_invalid") from None


def run_pubmed_metadata_session(
    project, *, run_id, query_id, expected_plan_sha256, confirmed, client,
):
    """At most 100 distinct EFetch batches, using existing crash-safe commits.

    Missing PMIDs after an interruption are never automatically requested
    again. A separate, later user-confirmed session is required. An HTTP
    failure leaves earlier committed batches intact and cannot report
    whole-run success.
    """
    _sha(expected_plan_sha256)
    if confirmed is not True or type(client) is not PubMedEFetchClient:
        raise PubMedMetadataGUIError("pubmed_metadata_confirmation_required")
    preview = preview_pubmed_metadata(
        project, run_id=run_id, query_id=query_id)
    if preview["plan_sha256"] != expected_plan_sha256:
        raise PubMedMetadataGUIError("pubmed_metadata_plan_changed")
    try:
        progress = collect_pubmed_metadata(
            project, query_id, client, batch_size=MAX_BATCH_IDS,
            max_batches=MAX_METADATA_BATCHES)
        saved = inspect_pubmed_metadata(project, run_id=run_id, query_id=query_id)
    except (PubMedMetadataError, CheckpointIntegrityError,
            ValueError, KeyError, TypeError):
        raise PubMedMetadataGUIError("pubmed_metadata_evidence_invalid") from None
    return dict(
        run_id=run_id, query_id=query_id,
        plan_sha256=expected_plan_sha256,
        status=progress.status,
        successful_batches=progress.batches_requested,
        session_batch_limit=MAX_METADATA_BATCHES,
        metadata_records_committed=saved["metadata_records_committed"],
        metadata_records_pending=saved["metadata_records_pending"],
        original_checkpoint_status=saved["status"],
        metadata_records_reconciled=saved["metadata_records_reconciled"],
        source_retrieval_verified=False, whole_search_verified=False,
        automatically_retryable=False,
        # A failed or killed POST can have an uncertain provider outcome.
        # No attempt is automatically resent by this adapter.
        unknown_inflight_request_possible=progress.status == "incomplete",
    )
