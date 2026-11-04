"""Host-confirmed PubMed identifier retrieval through existing durable checkpoints.

The read and preview operations perform no provider calls. The network-capable
operation is bounded, never returns PubMed identifiers or private credentials
to the graphical client, and cannot certify whole-source bibliography.
"""
from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from research_y.application_inspection import _read, ApplicationInspectionError
from research_y.preflight_review import _inspect, PreflightError
from research_y.pubmed_checkpoint_store import (
    _load_checkpoint, _snapshot_from_db, CheckpointIntegrityError,
)
from research_y.pubmed_checkpoint_resume import start_checkpointed_pubmed_retrieval
from research_y.pubmed_partition import DateWindow
from research_y.pubmed_probe import PubMedESearchProbeClient, PubMedProbeError

MAX_PUBMED_REQUESTS = 128  # per explicit session, including count probes
MAX_COUNT_PROBES = 100
PUBMED_PAGE_SIZE = 200
SAFE_CODES = frozenset((
    "pubmed_plan_unverified", "pubmed_checkpoint_invalid",
    "pubmed_contact_required", "pubmed_session_confirmation_required",
    "pubmed_identifier_budget_invalid", "pubmed_coverage_invalid",
    "pubmed_coverage_changed", "pubmed_provider_incomplete",
    "pubmed_worker_recovery_required", "pubmed_source_unavailable",
    "pubmed_query_not_ready",
))


class PubMedSourceError(ValueError):
    """Codes only: raw source responses, private paths and keys never echoed."""

    def __init__(self, code="pubmed_source_unavailable"):
        self.code = code if code in SAFE_CODES else "pubmed_source_unavailable"
        super().__init__(self.code)


def _uuid(value):
    try:
        if type(value) is not str or str(UUID(value)) != value:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise PubMedSourceError("pubmed_plan_unverified") from None
    return value


def _sha(value):
    if (type(value) is not str or len(value) != 64 or
            any(c not in "0123456789abcdef" for c in value)):
        raise PubMedSourceError("pubmed_plan_unverified")
    return value


def _window(start, end):
    try:
        if (type(start) is not str or type(end) is not str or
                len(start) != 10 or len(end) != 10):
            raise ValueError
        a, b = date.fromisoformat(start), date.fromisoformat(end)
        if a.isoformat() != start or b.isoformat() != end:
            raise ValueError
        return DateWindow(a, b)
    except (ValueError, TypeError, OverflowError):
        raise PubMedSourceError("pubmed_coverage_invalid") from None


def _query(db, run_id, query_id):
    row = db.execute(
        "SELECT r.run_id,r.strategy_version_id,q.source_name,"
        "q.exact_query,q.status FROM source_queries q "
        "JOIN search_runs r ON r.run_id=q.run_id "
        "WHERE q.query_id=? AND q.run_id=?",
        (query_id, run_id),
    ).fetchone()
    if (row is None or row[0] != run_id or row[2] != "pubmed" or
            type(row[3]) is not str):
        raise PubMedSourceError("pubmed_plan_unverified")
    return {"run_id": row[0], "version_id": row[1],
            "exact_query": row[3], "status": row[4]}


def _checkpoint(db, query_id):
    exists = db.execute(
        "SELECT 1 FROM pubmed_checkpoint_runs WHERE query_id=?",
        (query_id,)).fetchone() is not None
    if not exists:
        return None
    # Use one existing read transaction: never join two incompatible live
    # snapshots while a separate worker commits identifier pages.
    plan, leaves, status = _load_checkpoint(db, query_id)
    snapshot = _snapshot_from_db(db, query_id)
    parts = plan["partitions"]
    coverage = None if not parts else {
        "start": parts[0]["start"], "end": parts[0]["end"]}
    linked = db.execute(
        "SELECT COUNT(*) FROM query_retrievals "
        "WHERE query_id=? AND source_name='pubmed'", (query_id,),
    ).fetchone()[0]
    if linked > len(snapshot.pmids):
        raise PubMedSourceError("pubmed_checkpoint_invalid")
    return {
        "status": status, "reported_matches": snapshot.root_count,
        "identifiers_committed": len(snapshot.pmids),
        "pages_committed": snapshot.pages_committed,
        "pages_expected": snapshot.pages_expected,
        "identifiers_reconciled": snapshot.identifiers_reconciled,
        "metadata_records_linked": linked,
        "metadata_pending": True,
        "coverage": coverage,
    }


def inspect_pubmed_source(project, *, run_id, query_id):
    """Return a small, read-only source checkpoint inventory; NO PMID list."""
    _uuid(run_id)
    _uuid(query_id)
    try:
        with _read(project) as db:
            source = _query(db, run_id, query_id)
            checkpoint = _checkpoint(db, query_id)
            return {
                "run_id": run_id, "query_id": query_id,
                "exact_query": source["exact_query"],
                "source_query_status": source["status"],
                "checkpoint": checkpoint,
                "source_retrieval_verified": False,
                "whole_search_verified": False,
                "metadata_complete": False,
                "no_network_requests": True,
            }
    except PubMedSourceError:
        raise
    except (CheckpointIntegrityError, ApplicationInspectionError,
            KeyError, ValueError, TypeError):
        raise PubMedSourceError("pubmed_checkpoint_invalid") from None


def preview_pubmed_source(project, *, run_id, query_id):
    """Rebuild exact frozen OR plan even after sibling searches have started."""
    _uuid(run_id)
    _uuid(query_id)
    try:
        with _read(project) as db:
            plan = _inspect(db, run_id, allow_started=True)
            matches = [q for source in plan["sources"]
                       if source["source_name"] == "pubmed"
                       for q in source["queries"] if q["query_id"] == query_id]
            source = _query(db, run_id, query_id)
            if len(matches) != 1 or matches[0]["exact_query"] != source["exact_query"]:
                raise PubMedSourceError("pubmed_plan_unverified")
            checkpoint = _checkpoint(db, query_id)
            if checkpoint is None and source["status"] != "pending":
                raise PubMedSourceError("pubmed_query_not_ready")
            return {
                "run_id": run_id, "query_id": query_id,
                "group_id": matches[0]["group_id"],
                "exact_query": source["exact_query"],
                "plan_sha256": plan["plan_sha256"],
                "checkpoint": checkpoint,
                "max_session_requests": MAX_PUBMED_REQUESTS,
                "page_size": PUBMED_PAGE_SIZE,
                "max_partition_count_probes": MAX_COUNT_PROBES,
                "source_retrieval_verified": False,
                "whole_search_verified": False,
                "no_network_requests": True,
            }
    except PubMedSourceError:
        raise
    except (PreflightError, ApplicationInspectionError,
            CheckpointIntegrityError, KeyError, ValueError, TypeError):
        raise PubMedSourceError("pubmed_plan_unverified") from None


class _BudgetedESearch:
    """Count and ESearch page attempts before transport, including failures."""

    def __init__(self, client, budget):
        self.client = client
        self.budget = budget
        self.requests_made = 0

    def _reserve(self):
        if self.requests_made >= self.budget:
            raise PubMedProbeError("PubMed session request budget exhausted")
        self.requests_made += 1

    def probe(self, exact_query, *, allow_crdt_partition=False):
        self._reserve()
        return self.client.probe(
            exact_query, allow_crdt_partition=allow_crdt_partition)

    def fetch_esearch_page(self, exact_query, *, retstart, retmax):
        self._reserve()
        return self.client.fetch_esearch_page(
            exact_query, retstart=retstart, retmax=retmax)


def run_pubmed_source_session(
    project, *, run_id, query_id, expected_plan_sha256,
    coverage_start, coverage_end, confirmed, client,
):
    """One explicit bounded ESearch session; final metadata is NOT retrieved."""
    _sha(expected_plan_sha256)
    window = _window(coverage_start, coverage_end)
    if (confirmed is not True or type(client) is not PubMedESearchProbeClient):
        raise PubMedSourceError("pubmed_session_confirmation_required")
    preview = preview_pubmed_source(project, run_id=run_id, query_id=query_id)
    if preview["plan_sha256"] != expected_plan_sha256:
        raise PubMedSourceError("pubmed_plan_unverified")
    prior = preview["checkpoint"]
    if prior is not None and prior["coverage"] is not None:
        if prior["coverage"] != {"start": coverage_start, "end": coverage_end}:
            raise PubMedSourceError("pubmed_coverage_changed")
    # A completed identifier stage is not a fresh network entitlement.
    if prior is not None and prior["status"] == "identifiers_reconciled_metadata_pending":
        raise PubMedSourceError("pubmed_query_not_ready")
    budgeted = _BudgetedESearch(client, MAX_PUBMED_REQUESTS)
    try:
        result = start_checkpointed_pubmed_retrieval(
            project, query_id, budgeted, date_window=window,
            page_size=PUBMED_PAGE_SIZE,
            max_count_probes=MAX_COUNT_PROBES,
            expected_run_id=run_id,
            expected_plan_sha256=expected_plan_sha256,
        )
        saved = inspect_pubmed_source(project, run_id=run_id, query_id=query_id)
    except (CheckpointIntegrityError, KeyError, ValueError, TypeError):
        raise PubMedSourceError("pubmed_checkpoint_invalid") from None
    return {
        "run_id": run_id, "query_id": query_id,
        "plan_sha256": expected_plan_sha256,
        "session_requests_reserved": budgeted.requests_made,
        "session_request_limit": MAX_PUBMED_REQUESTS,
        "status": result.status,
        "checkpoint": saved["checkpoint"],
        "source_retrieval_verified": False,
        "whole_search_verified": False,
        "metadata_complete": False,
    }
