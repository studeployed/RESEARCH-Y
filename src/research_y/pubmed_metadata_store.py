"""Transactional PubMed EFetch metadata persistence against checked PMID IDs.

Only checkpointed PMID identifiers may be materialised. This increment stores
source records and source-query memberships but does not deduplicate across
sources or mark a source search complete. Crash recovery skips committed PMIDs.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import sqlite3
from typing import Callable
from uuid import uuid4

from research_y.projects import Project, _utc_now, _validated_project_connection
from research_y.pubmed_checkpoint_store import inspect_pubmed_checkpoint
from research_y.pubmed_metadata import (
    MAX_BATCH_IDS, PubMedEFetchClient, PubMedMetadataBatch, PubMedMetadataError,
    validate_pmids,
)
from research_y.storage import _audit


class PubMedMetadataIntegrityError(PubMedMetadataError):
    """Persisted or incoming metadata does not match checked source IDs."""


@dataclass(frozen=True, slots=True)
class PubMedMetadataProgress:
    status: str
    expected_ids: int
    committed_metadata_ids: int
    missing_pmids: tuple[str, ...]
    batches_requested: int
    error: str | None = None
    source_retrieval_verified: bool = False


def _query_identity(connection: sqlite3.Connection, query_id: str) -> str:
    if not isinstance(query_id, str) or not query_id.strip():
        raise ValueError("A valid existing source query is required")
    row = connection.execute(
        "SELECT run_id, source_name FROM source_queries WHERE query_id=?", (query_id,),
    ).fetchone()
    if row is None:
        raise KeyError("Unknown source query")
    run_id, source = row
    if source != "pubmed":
        raise PubMedMetadataIntegrityError("EFetch metadata can only be assigned to PubMed queries")
    return run_id


def _known_query_records(connection: sqlite3.Connection, query_id: str,
                         run_id: str) -> dict[str, str]:
    rows = connection.execute(
        "SELECT r.source_record_id, r.original_metadata_json "
        "FROM query_retrievals q JOIN source_retrievals r "
        "ON (q.retrieval_id=r.retrieval_id AND q.run_id=r.run_id "
        "AND q.source_name=r.source_name) "
        "WHERE q.query_id=? AND q.run_id=? AND q.source_name='pubmed'",
        (query_id, run_id),
    ).fetchall()
    records: dict[str, str] = {}
    for pmid, raw in rows:
        if pmid in records:
            raise PubMedMetadataIntegrityError("Repeated source retrieval membership")
        try:
            doc = json.loads(raw)
            if (doc["source"] != "NCBI PubMed EFetch XML"
                    or doc["record"]["pmid"] != pmid):
                raise ValueError("Source record identity mismatch")
        except (TypeError, ValueError, KeyError, IndexError):
            raise PubMedMetadataIntegrityError("Persisted PubMed metadata is inconsistent") from None
        records[pmid] = raw
    return records


def _checked_snapshot(project: Project, query_id: str):
    snapshot = inspect_pubmed_checkpoint(project, query_id)
    if not snapshot.identifiers_reconciled:
        raise PubMedMetadataIntegrityError("PubMed identifier checkpoint is not reconciled")
    return snapshot


def missing_pubmed_metadata_pmids(project: Project, query_id: str) -> tuple[str, ...]:
    """Return only checkpointed PMIDs still missing source-query metadata."""
    checkpoint = _checked_snapshot(project, query_id)
    with _validated_project_connection(project) as connection:
        run_id = _query_identity(connection, query_id)
        committed = _known_query_records(connection, query_id, run_id)
    allowed = set(checkpoint.pmids)
    if not set(committed).issubset(allowed):
        raise PubMedMetadataIntegrityError("Source metadata includes an uncheckpointed PMID")
    return tuple(pmid for pmid in checkpoint.pmids if pmid not in committed)


def commit_pubmed_metadata_batch(project: Project, query_id: str,
                                 batch: PubMedMetadataBatch) -> int:
    """Atomically insert EFetch records, memberships and one audit event.

    On repeat or cross-group discovery in a run, equivalent records are reused.
    Contradictory source data is never silently overwritten or normalised.
    """
    if not isinstance(batch, PubMedMetadataBatch):
        raise TypeError("A validated EFetch metadata batch is required")
    checkpoint = _checked_snapshot(project, query_id)
    allowed = set(checkpoint.pmids)
    validate_pmids(batch.requested_pmids)
    if not set(batch.requested_pmids).issubset(allowed):
        raise PubMedMetadataIntegrityError("EFetch contains PMIDs outside the approved checkpoint")
    if (len(batch.records) != len(batch.requested_pmids)
            or set(record.pmid for record in batch.records) != set(batch.requested_pmids)):

        raise PubMedMetadataIntegrityError("Metadata batch is missing required PMIDs")
    with _validated_project_connection(project) as connection:
        connection.execute("BEGIN IMMEDIATE")
        run_id = _query_identity(connection, query_id)
        known = _known_query_records(connection, query_id, run_id)
        if not set(known).issubset(allowed):
            raise PubMedMetadataIntegrityError("Existing source metadata is outside the checkpoint")
        created = 0
        new_associations = 0
        for record in batch.records:
            pmid = record.pmid
            original = json.loads(json.dumps(
                record.source_dict(), ensure_ascii=False, sort_keys=True, allow_nan=False,
            ))
            existing = connection.execute(
                "SELECT retrieval_id, original_metadata_json FROM source_retrievals "
                "WHERE run_id=? AND source_name='pubmed' AND source_record_id=?",
                (run_id, pmid),
            ).fetchone()
            if existing is None:
                retrieval_id = str(uuid4())
                payload = {
                    "source": batch.source,
                    "record": original,
                    "retrieved_at_utc": batch.retrieved_at_utc,
                    "response_sha256": batch.response_sha256,
                    "rights_review_required_for_abstract_redistribution": True,
                }
                connection.execute(
                    "INSERT INTO source_retrievals "
                    "(retrieval_id,run_id,source_name,source_record_id,retrieved_at_utc,original_metadata_json) "
                    "VALUES (?,?,'pubmed',?,?,?)",
                    (retrieval_id, run_id, pmid, batch.retrieved_at_utc,
                     json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False)),
                )
                created += 1
            else:
                retrieval_id, stored = existing
                try:
                    prior = json.loads(stored)
                    same_record = (prior.get("source") == batch.source
                                   and prior.get("record") == original)
                except (TypeError, ValueError, AttributeError):
                    same_record = False
                if not same_record:
                    raise PubMedMetadataIntegrityError(
                        "Existing PubMed metadata conflicts with the returned source record"
                    )
            had_member = connection.execute(
                "SELECT 1 FROM query_retrievals WHERE query_id=? AND retrieval_id=?",
                (query_id, retrieval_id),
            ).fetchone()
            if not had_member:
                connection.execute(
                    "INSERT INTO query_retrievals (query_id,retrieval_id,run_id,source_name) "
                    "VALUES (?,?,?,'pubmed')",
                    (query_id, retrieval_id, run_id),
                )
                new_associations += 1
        if created or new_associations:
            _audit(connection, kind="pubmed_efetch_metadata_committed", timestamp=_utc_now(),
                   details={"run_id": run_id, "query_id": query_id,
                            "batch_sha256": batch.response_sha256,
                            "created_records": created,
                            "new_query_memberships": new_associations})
        # Neither search_runs nor source_queries can be certified here.
    return new_associations


def collect_pubmed_metadata(project: Project, query_id: str, client: PubMedEFetchClient,
                            *, batch_size: int = MAX_BATCH_IDS, max_batches: int = 10,
                            after_commit: Callable[[PubMedMetadataBatch], None] | None = None,
                            ) -> PubMedMetadataProgress:
    """Fetch missing checkpointed PMIDs in bounded batches with crash recovery.

    A second invocation skips already committed batches. Provider failures,
    contradictory metadata, source pause and rejected payloads stay incomplete.
    No retries, silent gap filling or completed_verified transition occur.
    """
    if type(batch_size) is not int or not 1 <= batch_size <= MAX_BATCH_IDS:
        raise ValueError("EFetch batch size is outside the supported range")
    if type(max_batches) is not int or not 1 <= max_batches <= 100:
        raise ValueError("EFetch batch budget is outside the supported range")
    if after_commit is not None and not callable(after_commit):
        raise TypeError("after_commit must be callable")
    if not isinstance(client, PubMedEFetchClient):
        raise TypeError("A configured PubMed EFetch client is required")
    try:
        checkpoint = _checked_snapshot(project, query_id)
        with _validated_project_connection(project) as connection:
            _query_identity(connection, query_id)
        remaining = missing_pubmed_metadata_pmids(project, query_id)
    except (PubMedMetadataError, KeyError, ValueError, sqlite3.Error):
        return PubMedMetadataProgress("incomplete", 0, 0, (), 0,
                                      "PubMed checkpoint or query could not be validated")
    expected = len(checkpoint.pmids)

    def report(status: str, count: int, error: str | None = None) -> PubMedMetadataProgress:
        try:
            pending = missing_pubmed_metadata_pmids(project, query_id)
        except Exception:
            return PubMedMetadataProgress("incomplete", expected, 0, (), count,
                                          "Committed metadata could not be checked")
        return PubMedMetadataProgress(status, expected, expected - len(pending), pending,
                                      count, error)

    if checkpoint.stored_status == "paused":
        return report("paused", 0)
    fetched = 0
    while remaining and fetched < max_batches:
        try:
            fresh_checkpoint = _checked_snapshot(project, query_id)
            if fresh_checkpoint.stored_status == "paused":
                return report("paused", fetched)
            batch_ids = remaining[:batch_size]
            result = client.fetch(batch_ids)
            commit_pubmed_metadata_batch(project, query_id, result)
            fetched += 1
            if after_commit is not None:
                after_commit(result)
            remaining = missing_pubmed_metadata_pmids(project, query_id)
        except Exception:
            # No untrusted provider/callback/SQLite exception messages are logged.
            return report("incomplete", fetched, "PubMed metadata batch failed; previously committed records retained")
    try:
        if inspect_pubmed_checkpoint(project, query_id).stored_status == "paused":
            return report("paused", fetched)
    except Exception:
        return report("incomplete", fetched, "Checkpoint status could not be revalidated")
    return report("metadata_acquired_reconciliation_pending" if not remaining else "incomplete",
                  fetched, None if not remaining else "Batch budget reached; more metadata remains")
