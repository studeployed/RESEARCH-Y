"""One-use approval of up to TWO existing 64-record materialisation commits.

This is a deliberately finite, foreground-only trusted-host operation, NOT
unattended processing of an entire run. Each batch uses the unchanged
production service, retaining its own immediate SQLite transaction and audit.
A failure after batch one leaves that batch durable and forces a NEW preview;
the original consent can never be replayed to materialise a different batch.
"""
from __future__ import annotations

from research_y import publication_identity as identity
from research_y.application_inspection import _read
from research_y.original_source_scope import original_scope_digest
from research_y.publication_run_materialisation import (
    MAX_BATCH, MaterialisationConflict, _plan, materialise_run_batch,
)
from research_y.projects import Project

METHOD = "explicit-two-batch-materialisation/1"
MAX_BATCHES = 2
MAX_SESSION_RECORDS = MAX_BATCH * MAX_BATCHES

_PENDING_SQL = (
    "SELECT r.retrieval_id FROM source_retrievals r "
    "LEFT JOIN publication_retrievals l ON l.retrieval_id=r.retrieval_id "
    "WHERE r.run_id=? AND l.retrieval_id IS NULL "
    "ORDER BY r.retrieval_id LIMIT ?"
)

def _plan_window(db, project: Project, run_id: str) -> tuple[dict, tuple[str, ...], str, str]:
    first, first_ids = _plan(db, project, run_id, MAX_BATCH)
    selected = tuple(row[0] for row in db.execute(
        _PENDING_SQL, (run_id, MAX_SESSION_RECORDS)))
    pending = first["unmaterialised_retrievals"]
    if len(selected) != min(pending, MAX_SESSION_RECORDS):
        raise MaterialisationConflict("Materialisation window changed")
    if selected[:len(first_ids)] != first_ids:
        raise MaterialisationConflict("Materialisation first batch changed")
    scope = original_scope_digest(db)
    revision = identity._hash(
        [METHOD, first["revision"], str(project.identifier), run_id,
         MAX_BATCHES, selected, scope])
    batches = [len(selected[:MAX_BATCH])]
    if len(selected) > MAX_BATCH:
        batches.append(len(selected[MAX_BATCH:]))
    if batches == [0]:
        batches = []
    return {
        "method": METHOD,
        "project_id": str(project.identifier),
        "run_id": run_id,
        "revision": revision,
        "source_records_retained": first["source_records_retained"],
        "unmaterialised_retrievals": pending,
        "existing_publication_hypotheses": first["existing_publication_hypotheses"],
        "batch_sizes": batches,
        "batch_count": len(batches),
        "proposed_source_records": len(selected),
        "maximum_source_records": MAX_SESSION_RECORDS,
        "maximum_batches": MAX_BATCHES,
        "requires_explicit_confirmation": True,
        "unattended_processing": False,
        "materialisation_complete": pending == 0,
        "global_unique_publications": None,
        "deduplication_complete": False,
        "source_retrieval_verified": False,
        "verified_complete": False,
        "no_network_requests": True,
    }, selected, scope, first["revision"]


def preview_two_batch_materialisation(project: Project, run_id: str) -> dict:
    """A reviewable immutable consent token for at most 128 source records."""
    identity._identifier(run_id)
    with _read(project) as db:
        preview, _, _, _ = _plan_window(db, project, run_id)
        return preview


def confirm_two_batch_materialisation(
    project: Project, run_id: str, *, expected_revision: str,
    actor: str, confirmed: bool,
) -> dict:
    """Commit at most two original 64-row transactions after one approval.

    A crash between commits is recoverable by re-opening the original project.
    This call is *never* idempotently replayed: the consumed initial revision
    is invalid as soon as any first batch commits. No new consent is inferred.
    """
    identity._identifier(run_id)
    identity._text(actor, 200)
    if confirmed is not True:
        raise ValueError("Explicit two-batch confirmation required")
    if (type(expected_revision) is not str or len(expected_revision) != 64
            or any(c not in "0123456789abcdef" for c in expected_revision)):
        raise ValueError("Canonical two-batch preview revision required")

    with _read(project) as db:
        preview, selected, original_scope, first_revision = _plan_window(
            db, project, run_id)
    if expected_revision != preview["revision"]:
        raise MaterialisationConflict("Two-batch approval is stale; preview again")
    if not selected:
        raise ValueError("No unmaterialised source retrievals remain")

    # Only the original production one-batch writer modifies SQLite. Each
    # commit has its own audited <=64-source transaction and failure rollback.
    results = []
    for index, size in enumerate(preview["batch_sizes"]):
        expected_ids = selected[index * MAX_BATCH:index * MAX_BATCH + size]
        if index == 0:
            revision = first_revision
        else:
            # A new original scope, source list or new competing association
            # invalidates this one-use approval. Never silently substitute
            # another next batch after an interrupted or concurrent change.
            with _read(project) as db:
                next_plan, next_ids = _plan(db, project, run_id, MAX_BATCH)
            if (next_ids != expected_ids or
                    next_plan["unmaterialised_retrievals"] !=
                        preview["unmaterialised_retrievals"] - sum(
                            r["materialised_in_batch"] for r in results)):
                raise MaterialisationConflict(
                    "Original scope or approved next batch changed; preview again")
            revision = next_plan["revision"]
        receipt = materialise_run_batch(
            project, run_id, expected_revision=revision,
            actor=actor, confirmed=True, batch_size=MAX_BATCH,
            _expected_original_scope_sha256=original_scope,
            _expected_retrieval_ids=expected_ids)
        if (receipt["materialised_in_batch"] != size or
                receipt["unmaterialised_retrievals_remaining"] !=
                preview["unmaterialised_retrievals"] - sum(
                    r["materialised_in_batch"] for r in results) - size):
            raise MaterialisationConflict(
                "Materialisation receipt differs; re-open original evidence")
        results.append(receipt)
    return {
        "method": METHOD,
        "project_id": str(project.identifier),
        "run_id": run_id,
        "committed_batches": len(results),
        "materialised_in_session": sum(r["materialised_in_batch"] for r in results),
        "unmaterialised_retrievals_remaining":
            results[-1]["unmaterialised_retrievals_remaining"],
        "materialisation_complete": results[-1]["materialisation_complete"],
        "requires_new_preview_for_next_session": True,
        "partial_commits_possible_if_interrupted": True,
        "unattended_processing": False,
        "source_retrieval_verified": False,
        "deduplication_complete": False,
        "verified_complete": False,
        "global_unique_publications": None,
        "no_network_requests": True,
    }
