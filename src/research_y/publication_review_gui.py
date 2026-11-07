"""Read and explicitly decide bounded publication candidate pairs in the local GUI.

This is an adapter over the existing conservative candidate/identity services.
It never discovers every duplicate, exposes original abstracts, launches source
requests, promotes unique counts or silently associates equal identifiers.
"""
from __future__ import annotations

from research_y.application_inspection import _read
from research_y import publication_identity as identity, publication_candidates as candidates
from research_y import result_counts
from research_y.publication_results import DETAIL_FIELDS, _value

METHOD = "local-publication-review/1"


class PublicationReviewError(RuntimeError):
    """Fixed client-safe error codes, never source text or credential values."""

    def __init__(self, code="publication_review_unavailable"):
        self.code = code if code in (
            "publication_review_unavailable", "publication_review_invalid",
            "publication_review_stale", "publication_review_wrong_run",
            "publication_review_no_reversal", "publication_review_confirmation_required",
        ) else "publication_review_unavailable"
        super().__init__(self.code)


def _digest(value):
    if (type(value) is not str or len(value) != 64 or
            any(ch not in "0123456789abcdef" for ch in value)):
        raise PublicationReviewError("publication_review_invalid")
    return value


def _context(db, project, run_id, revision):
    counts = result_counts._snapshot(db, project, run_id)
    if counts.revision != revision:
        raise PublicationReviewError("publication_review_stale")
    return counts


def _pair(db, run_id, left, right):
    snapshot, _ = candidates._view(db, candidates._pair(left, right))
    if any(source["run_id"] != run_id for source in snapshot.sources):
        raise PublicationReviewError("publication_review_wrong_run")
    return snapshot


def _safe_pair(snapshot, project, run_id, run_revision):
    fields = []
    for name in DETAIL_FIELDS:
        outcome = snapshot.comparison["comparisons"][name]
        sides = [snapshot.comparison["sides"][i]["fields"][name]
                 for i in range(2)]
        fields.append(dict(field=name, comparison=outcome,
                           left=_value(sides[0]), right=_value(sides[1]),
                           left_path=sides[0]["path"], right_path=sides[1]["path"]))
    # The original full audit/decision receipts remain in SQLite. Present only
    # bounded user-authored actor/reason history, never raw comparison payloads.
    decisions = snapshot.prior_decisions[-10:]
    prior = [dict(event_id=r["event_id"], status=r["status"],
                  recorded_at_utc=r["at_utc"], actor=r["actor"],
                  evidence=r["evidence"], association_event_id=r["association_event_id"])
             for r in decisions]
    return dict(
        method=METHOD, project_id=str(project.identifier), run_id=run_id,
        run_revision=run_revision, revision=snapshot.revision,
        retrieval_ids=list(snapshot.retrieval_ids),
        publication_ids=list(snapshot.publication_ids),
        sources=[dict(retrieval_id=s["retrieval_id"],
                      source_name=s["source_name"],
                      source_record_id=s["source_record_id"]) for s in snapshot.sources],
        comparison=fields, warnings=list(snapshot.warnings),
        status=snapshot.status,
        pair_already_associated=snapshot.publication_ids[0] == snapshot.publication_ids[1],
        prior_decision_count=len(snapshot.prior_decisions),
        recent_decisions=prior,
        prior_decisions_omitted=max(0, len(snapshot.prior_decisions)-len(prior)),
        automatic_match_allowed=False, abstract_text_displayed=False,
        no_network_requests=True, deduplication_complete=False,
        global_unique_publications=None, verified_complete=False,
    )


def preview_candidate_review(project, run_id, left, right, *, run_revision):
    """Compare two explicitly selected source retrievals in one run, read-only."""
    try:
        identity._identifier(run_id)
        identity._identifier(left); identity._identifier(right)
        _digest(run_revision)
        with _read(project) as db:
            _context(db, project, run_id, run_revision)
            snapshot = _pair(db, run_id, left, right)
            return _safe_pair(snapshot, project, run_id, run_revision)
    except PublicationReviewError:
        raise
    except Exception:
        raise PublicationReviewError() from None


def record_candidate_review(project, run_id, left, right, *, run_revision,
                            expected_revision, decision, move_retrieval_id,
                            actor, evidence, warnings_acknowledged, confirmed):
    """Commit match or rejection using the original candidate receipt transaction.

    No browser-supplied comparison or warning list is trusted. A changed
    candidate receipt, association or source/run evidence fails closed.
    """
    if confirmed is not True or warnings_acknowledged is not True:
        raise PublicationReviewError("publication_review_confirmation_required")
    if decision not in ("confirmed_match", "rejected_match"):
        raise PublicationReviewError("publication_review_invalid")
    try:
        identity._identifier(run_id)
        identity._identifier(left); identity._identifier(right)
        _digest(run_revision); _digest(expected_revision)
        identity._text(actor, 200); identity._text(evidence)
        if decision == "confirmed_match":
            if move_retrieval_id not in (left, right):
                raise PublicationReviewError("publication_review_invalid")
        elif move_retrieval_id is not None:
            raise PublicationReviewError("publication_review_invalid")
        with _read(project) as db:
            _context(db, project, run_id, run_revision)
            snapshot = _pair(db, run_id, left, right)
            if snapshot.revision != expected_revision:
                raise PublicationReviewError("publication_review_stale")
            warnings = tuple(snapshot.warnings)
        decided = candidates.decide_candidate(
            project, left, right, expected_revision=expected_revision,
            decision=decision, actor=actor, evidence=evidence,
            acknowledged_warnings=warnings, decision_confirmed=True,
            move_retrieval_id=move_retrieval_id,
        )
        if decided.status != decision:
            raise PublicationReviewError("publication_review_unavailable")
        return dict(
            method=METHOD, project_id=str(project.identifier), run_id=run_id,
            decision=decision, resulting_candidate_revision=decided.revision,
            # A returned worker outcome still needs a new authoritative preview.
            requires_reinspection=True, no_network_requests=True,
            global_unique_publications=None, deduplication_complete=False,
            verified_complete=False,
        )
    except PublicationReviewError:
        raise
    except identity.StalePublicationError:
        raise PublicationReviewError("publication_review_stale") from None
    except (TypeError, ValueError):
        raise PublicationReviewError("publication_review_invalid") from None
    except Exception:
        raise PublicationReviewError() from None


def _reversal(db, project, run_id, retrieval_id, run_revision):
    _context(db, project, run_id, run_revision)
    source = identity._source(db, retrieval_id)
    if source["run_id"] != run_id:
        raise PublicationReviewError("publication_review_wrong_run")
    link = identity._link(db, retrieval_id)
    if link is None or link[2].get("action") != "associate":
        raise PublicationReviewError("publication_review_no_reversal")
    record = link[2]
    if record.get("status") != "confirmed_match" or not record.get("before"):
        raise PublicationReviewError("publication_review_no_reversal")
    current = identity._snapshot(db, link[0])
    restored = identity._snapshot(db, record["before"])
    evidence_revision = identity._hash([
        METHOD, str(project.identifier), run_id, run_revision, retrieval_id,
        link[1], current.revision, restored.revision,
    ])
    return dict(
        method=METHOD, project_id=str(project.identifier), run_id=run_id,
        run_revision=run_revision, revision=evidence_revision,
        retrieval_id=retrieval_id, association_event_id=link[1],
        current_publication_id=current.publication_id,
        restored_publication_id=restored.publication_id,
        current_publication_revision=current.revision,
        restored_publication_revision=restored.revision,
        original_decision_actor=record["actor"],
        original_decision_evidence=record["evidence"],
        explicit_confirmation_required=True,
        no_network_requests=True, global_unique_publications=None,
        deduplication_complete=False, verified_complete=False,
    )


def preview_candidate_reversal(project, run_id, retrieval_id, *, run_revision):
    """Read the *current* reversible link. Older or absent decisions cannot undo."""
    try:
        identity._identifier(run_id); identity._identifier(retrieval_id)
        _digest(run_revision)
        with _read(project) as db:
            return _reversal(db, project, run_id, retrieval_id, run_revision)
    except PublicationReviewError:
        raise
    except Exception:
        raise PublicationReviewError() from None


def confirm_candidate_reversal(project, run_id, retrieval_id, *, run_revision,
                               expected_revision, actor, evidence, confirmed):
    if confirmed is not True:
        raise PublicationReviewError("publication_review_confirmation_required")
    try:
        identity._identifier(run_id); identity._identifier(retrieval_id)
        _digest(run_revision); _digest(expected_revision)
        identity._text(actor, 200); identity._text(evidence)
        with _read(project) as db:
            plan = _reversal(db, project, run_id, retrieval_id, run_revision)
            if plan["revision"] != expected_revision:
                raise PublicationReviewError("publication_review_stale")
        result = identity.reverse_association(
            project, retrieval_id, plan["association_event_id"],
            expected_current_revision=plan["current_publication_revision"],
            expected_restored_revision=plan["restored_publication_revision"],
            actor=actor, evidence=evidence,
        )
        if result.publication_id != plan["restored_publication_id"]:
            raise PublicationReviewError("publication_review_unavailable")
        return dict(
            method=METHOD, project_id=str(project.identifier), run_id=run_id,
            reversal_of_event_id=plan["association_event_id"],
            restored_publication_id=result.publication_id,
            requires_reinspection=True, no_network_requests=True,
            global_unique_publications=None, deduplication_complete=False,
            verified_complete=False,
        )
    except PublicationReviewError:
        raise
    except identity.StalePublicationError:
        raise PublicationReviewError("publication_review_stale") from None
    except (ValueError, TypeError):
        raise PublicationReviewError("publication_review_invalid") from None
    except Exception:
        raise PublicationReviewError() from None


def read_current_retrieval_link(project, run_id, retrieval_id, *, run_revision):
    """Check the current identity receipt without exposing original metadata.

    Used after a possible lost reversal reply: only a current reverse event
    referencing the exact original association proves that undo was committed.
    """
    try:
        identity._identifier(run_id); identity._identifier(retrieval_id)
        _digest(run_revision)
        with _read(project) as db:
            _context(db, project, run_id, run_revision)
            if identity._source(db, retrieval_id)["run_id"] != run_id:
                raise PublicationReviewError("publication_review_wrong_run")
            link = identity._link(db, retrieval_id)
            if link is None:
                raise PublicationReviewError("publication_review_unavailable")
            return dict(
                method=METHOD, project_id=str(project.identifier),
                run_id=run_id, run_revision=run_revision,
                retrieval_id=retrieval_id, publication_id=link[0],
                event_id=link[1], action=link[2].get("action"),
                reverses_event_id=link[2].get("reverses_event_id"),
                decision_status=link[2].get("status"),
                actor=link[2].get("actor"), evidence=link[2].get("evidence"),
                no_network_requests=True, global_unique_publications=None,
                deduplication_complete=False, verified_complete=False,
            )
    except PublicationReviewError:
        raise
    except Exception:
        raise PublicationReviewError() from None
