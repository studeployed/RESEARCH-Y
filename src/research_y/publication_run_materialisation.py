"""Explicit, bounded materialisation of a run's retained source records.

Each source retrieval starts as an independent, REVIEW-REQUIRED publication
hypothesis. Equal DOI/title/supplement metadata NEVER authorises a merge.
Existing researcher decisions and source/group/run rows are untouched.

This is an offline, explicitly confirmed preparation step for the future master
results interface; it is not duplicate discovery, final counts, or an
unattended GUI action. Small transactions support reopen/re-preview recovery.
"""
from __future__ import annotations

from uuid import uuid4

from research_y import publication_identity as identity
from research_y import result_counts
from research_y.application_inspection import _read
from research_y.projects import Project, _validated_project_connection

METHOD = "run-publication-materialisation/1"
MAX_BATCH = 64
EVIDENCE = "One retained source retrieval; publication equivalence not assessed"


class MaterialisationConflict(ValueError):
    """An approved preview no longer describes the source/identity evidence."""


def _batch_size(value: int) -> int:
    if type(value) is not int or not 1 <= value <= MAX_BATCH:
        raise ValueError("Materialisation batch size must be 1–64")
    return value


def _plan(db, project: Project, run_id: str, batch_size: int) -> tuple[dict, tuple[str, ...]]:
    # The canonical count projection validates the complete run evidence and
    # every existing association. Never use a second, competing source count.
    projection = result_counts._snapshot(db, project, run_id)
    pending = db.execute(
        "SELECT COUNT(*) FROM source_retrievals r "
        "LEFT JOIN publication_retrievals l ON l.retrieval_id=r.retrieval_id "
        "WHERE r.run_id=? AND l.retrieval_id IS NULL", (run_id,)
    ).fetchone()[0]
    if pending != projection.totals["unmaterialised_retrievals"]:
        raise MaterialisationConflict("Run materialisation counts differ")
    ids = tuple(row[0] for row in db.execute(
        "SELECT r.retrieval_id FROM source_retrievals r "
        "LEFT JOIN publication_retrievals l ON l.retrieval_id=r.retrieval_id "
        "WHERE r.run_id=? AND l.retrieval_id IS NULL "
        "ORDER BY r.retrieval_id LIMIT ?", (run_id, batch_size)
    ))
    if len(ids) != min(batch_size, pending):
        raise MaterialisationConflict("Run materialisation page changed")
    revision = identity._hash(
        [METHOD, str(project.identifier), run_id, batch_size, projection.revision, ids]
    )
    return {
        "method": METHOD,
        "project_id": str(project.identifier),
        "run_id": run_id,
        "source_records_retained": projection.totals["metadata_source_records"],
        "unmaterialised_retrievals": pending,
        "existing_publication_hypotheses": projection.totals["global_publication_identities"],
        "batch_size": batch_size,
        "batch_count": len(ids),
        "revision": revision,
        "materialisation_complete": pending == 0,
        "deduplication_complete": False,
        "global_unique_publications": None,
        "source_retrieval_verified": False,
        "verified_complete": False,
        "no_network_requests": True,
    }, ids


def preview_run_materialisation(
    project: Project, run_id: str, *, batch_size: int = MAX_BATCH
) -> dict:
    """Read-only preview. Its revision must be rechecked during confirmation."""
    identity._identifier(run_id)
    _batch_size(batch_size)
    with _read(project) as db:
        plan, _ = _plan(db, project, run_id, batch_size)
        return plan


def materialise_run_batch(
    project: Project, run_id: str, *, expected_revision: str,
    actor: str, confirmed: bool, batch_size: int = MAX_BATCH
) -> dict:
    """Atomically create at most 64 independent publication hypotheses.

    A batch is all-or-nothing. A crash before commit leaves no partial new
    identities; a committed batch is discovered by the next read-only preview.
    Reusing a previous revision is rejected instead of accidentally consuming
    a different next batch. Existing identity links are NEVER reconsidered.
    """
    identity._identifier(run_id)
    _batch_size(batch_size)
    identity._text(actor, 200)
    if confirmed is not True:
        raise ValueError("Explicit run materialisation confirmation is required")
    if (type(expected_revision) is not str or len(expected_revision) != 64
            or any(c not in "0123456789abcdef" for c in expected_revision)):
        raise ValueError("A canonical materialisation preview revision is required")
    with _validated_project_connection(project) as db:
        db.execute("BEGIN IMMEDIATE")
        plan, ids = _plan(db, project, run_id, batch_size)
        if expected_revision != plan["revision"]:
            raise MaterialisationConflict("Materialisation preview is stale; inspect again")
        if not ids:
            raise ValueError("No unmaterialised source retrievals remain in this run")
        for retrieval_id in ids:
            source = identity._source(db, retrieval_id)
            if source["run_id"] != run_id or identity._link(db, retrieval_id) is not None:
                raise MaterialisationConflict("Source identity changed during materialisation")
            publication_id = str(uuid4())
            db.execute(
                "INSERT INTO publications(publication_id,created_at_utc) VALUES(?,?)",
                (publication_id, identity._utc_now()),
            )
            identity._record_link(
                db, source, before=None, after=publication_id,
                previous_event_id=None, status="review_required",
                action="materialise", actor=actor, evidence=EVIDENCE,
            )
        return {
            "method": METHOD,
            "project_id": plan["project_id"],
            "run_id": run_id,
            "materialised_in_batch": len(ids),
            "unmaterialised_retrievals_remaining": plan["unmaterialised_retrievals"] - len(ids),
            "materialisation_complete": plan["unmaterialised_retrievals"] == len(ids),
            "deduplication_complete": False,
            "global_unique_publications": None,
            "source_retrieval_verified": False,
            "verified_complete": False,
            "no_network_requests": True,
            "requires_new_preview_for_next_batch": True,
        }
