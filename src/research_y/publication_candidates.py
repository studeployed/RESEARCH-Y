"""Bounded candidate review and immutable explicit match/rejection receipts.

Reads never materialise or merge publications. Confirmation uses the identity
operation's existing guards in the SAME transaction as its decision receipt.
Prior-run receipts are visible, not automatically applied. No final count,
provider completeness, universal candidate discovery or automatic match claim.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import sqlite3
from typing import Any

from research_y.projects import Project, _utc_now, _validated_project_connection
from research_y import publication_identity as identity
from research_y.publication_match_evidence import RULE_VERSION, compare_sources

DECISION_EVENT = "publication_candidate_decision_v1"
MAX_CANDIDATE_BATCH = 32


@dataclass(frozen=True, slots=True)
class CandidateSnapshot:
    retrieval_ids: tuple[str, str]
    revision: str
    publication_ids: tuple[str, str]
    publication_revisions: tuple[str, str]
    sources: tuple[dict[str, Any], ...]
    comparison: dict[str, Any]
    status: str
    warnings: tuple[str, ...]
    prior_decisions: tuple[dict[str, Any], ...]
    automatic_match_allowed: bool = False
    deduplication_complete: bool = False


def _pair(left: str, right: str) -> tuple[str, str]:
    identity._identifier(left)
    identity._identifier(right)
    if left == right:
        raise ValueError("Two distinct source retrievals are required")
    return tuple(sorted((left, right)))


def _source_key(source: dict) -> list[str]:
    payload = source["original_metadata"]
    # A source identifier is namespaced; identical text in another database
    # must not inherit a decision. No normalisation guesses at source identity.
    namespace = payload.get("database", "") if source["source_name"] == "wos" else ""
    if not isinstance(namespace, str):
        raise identity.PublicationIntegrityError("Invalid source database namespace")
    return [source["source_name"], namespace, source["source_record_id"]]


def _state(db: sqlite3.Connection, pair: tuple[str, str]):
    snapshots, sources = [], []
    for retrieval_id in pair:
        link = identity._link(db, retrieval_id)
        if link is None:
            raise ValueError("Materialise both retrievals before reviewing candidates")
        snapshot = identity._snapshot(db, link[0])
        snapshots.append(snapshot)
        sources.append(next(s for s in snapshot.retrievals if s["retrieval_id"] == retrieval_id))
    comparison = compare_sources(*sources)
    keys = sorted(_source_key(s) for s in sources)
    state = identity._hash([RULE_VERSION, pair, [s.revision for s in snapshots], comparison])
    return snapshots, sources, comparison, keys, state


def _hash_text(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _comparison_receipt(comparison: dict) -> dict:
    """Retain comparison outcomes/paths/hashes, not licensed source text."""
    return {
        "rule_version": comparison["rule_version"],
        "comparisons": comparison["comparisons"], "warnings": comparison["warnings"],
        "candidate_hint": comparison["candidate_hint"],
        "sides": [{"retrieval_id": side["retrieval_id"], "source_sha256": side["source_sha256"],
                   "fields": {name: {"path": field["path"], "status": field["status"],
                                     "value_sha256": identity._hash(field["value"]),
                                     "normalised_sha256": identity._hash(field["normalised"])}
                              for name, field in side["fields"].items()}}
                  for side in comparison["sides"]],
    }


def _receipts(db: sqlite3.Connection, keys: list[list[str]] | None) -> list[dict]:
    """Fail closed on unsupported/corrupt receipts; no audit schema migration.

    This bounded first increment scans candidate receipts, not all source pairs.
    Indexed project-wide discovery and large-history performance are later work.
    keys=None returns all validated receipts for a single-pass count projection.
    """
    related = []
    previous: dict[tuple[str, str], int] = {}
    for (event_id,) in db.execute("SELECT event_id FROM audit_events WHERE event_type=? ORDER BY event_id",
                                  (DECISION_EVENT,)):
        event = identity._event(db, event_id, DECISION_EVENT)
        try:
            pair = event["pair"]
            valid = (
                isinstance(pair, list) and len(pair) == 2
                and list(_pair(*pair)) == pair
                and isinstance(event["source_keys"], list) and len(event["source_keys"]) == 2
                and all(isinstance(k, list) and len(k) == 3 and all(isinstance(v, str) for v in k)
                        for k in event["source_keys"])
                and event["source_keys"] == sorted(event["source_keys"])
                and event["status"] in ("confirmed_match", "rejected_match")
                and isinstance(event["method"], str) and bool(event["method"])
                and isinstance(event["warnings_acknowledged"], list)
                and all(isinstance(v, str) for v in event["warnings_acknowledged"])
                and all(_hash_text(event[k]) for k in (
                    "request_sha256", "post_state_sha256", "input_revision", "comparison_sha256"))
                and isinstance(event["source_hashes"], list) and len(event["source_hashes"]) == 2
                and all(_hash_text(h) for h in event["source_hashes"])
                and event["previous_event_id"] == previous.get(tuple(pair))
                and isinstance(event["comparison"], dict)
                and identity._hash(event["comparison"]) == event["comparison_sha256"]
                and isinstance(event["reviewed_context"], dict)
            )
            identity._text(event["actor"], 200)
            identity._text(event["evidence"])
            if not valid:
                raise ValueError("Invalid receipt")
            if event["status"] == "rejected_match":
                if event["association_event_id"] is not None or event["moved_retrieval_id"] is not None:
                    raise ValueError("Invalid rejection")
            else:
                if event["moved_retrieval_id"] not in pair:
                    raise ValueError("Invalid confirmation")
                if event["association_event_id"] is not None:
                    association = identity._event(db, event["association_event_id"], identity.IDENTITY_EVENT)
                    if (event["association_event_id"] >= event_id
                            or association.get("status") != "confirmed_match"
                            or association.get("source_sha256") != event["source_hashes"][pair.index(event["moved_retrieval_id"])]
                            or association.get("action") != "associate"
                            or association.get("retrieval_id") != event["moved_retrieval_id"]
                            or association.get("actor") != event["actor"]
                            or association.get("evidence") != event["evidence"]):
                        raise ValueError("Inconsistent confirmation")
        except (ValueError, TypeError, KeyError):
            raise identity.PublicationIntegrityError("Invalid candidate decision receipt") from None
        previous[tuple(pair)] = event_id
        if keys is None or event["source_keys"] == keys:
            related.append({"event_id": event_id, **event})
    return related


def _view(db: sqlite3.Connection, pair: tuple[str, str]) -> tuple[CandidateSnapshot, str]:
    snapshots, sources, comparison, keys, state = _state(db, pair)
    receipts = _receipts(db, keys)
    current = next((r for r in reversed(receipts) if r["pair"] == list(pair)), None)
    status = "review_required"
    warnings = set(comparison["warnings"])
    if current is not None:
        if (current["post_state_sha256"] == state and current["method"] == RULE_VERSION
                and receipts[-1]["event_id"] == current["event_id"]):
            status = current["status"]
        else:
            warnings.add("prior_decision_needs_review")
    if any(r["pair"] != list(pair) for r in receipts):
        warnings.add("prior_run_decision_available")
    revision = identity._hash([state, receipts])
    public_sources = tuple({k: source[k] for k in (
        "retrieval_id", "run_id", "source_name", "source_record_id", "source_sha256",
        "run_status", "memberships")} for source in sources)
    return CandidateSnapshot(
        pair, revision, tuple(s.publication_id for s in snapshots),
        tuple(s.revision for s in snapshots), public_sources, comparison, status,
        tuple(sorted(warnings)), tuple(receipts)), state


def read_candidate(project: Project, left_retrieval_id: str, right_retrieval_id: str) -> CandidateSnapshot:
    """Compare one explicit pair in a consistent snapshot, without writes."""
    pair = _pair(left_retrieval_id, right_retrieval_id)
    with _validated_project_connection(project) as db:
        db.execute("BEGIN")
        return _view(db, pair)[0]


def find_candidates(project: Project, retrieval_ids: tuple[str, ...]) -> tuple[CandidateSnapshot, ...]:
    """Return supported pairs in an explicitly bounded batch, never truncate.

    Exact normalised title/identifier agreement is a review hint, not proof.
    Previously decided pairs remain visible even when their evidence changes.
    This is NOT exhaustive project-wide or fuzzy duplicate discovery.
    """
    if (not isinstance(retrieval_ids, (tuple, list)) or not 2 <= len(retrieval_ids) <= MAX_CANDIDATE_BATCH):
        raise ValueError("Candidate batches require 2–32 explicit retrieval identifiers")
    ordered = sorted(identity._identifier(r) for r in retrieval_ids)
    if len(set(ordered)) != len(ordered):
        raise ValueError("Candidate batch identifiers must be distinct")
    with _validated_project_connection(project) as db:
        db.execute("BEGIN")
        candidates = []
        for i, left in enumerate(ordered):
            for right in ordered[i + 1:]:
                candidate, _ = _view(db, (left, right))
                if candidate.comparison["candidate_hint"] or candidate.prior_decisions:
                    candidates.append(candidate)
        return tuple(candidates)


def decide_candidate(project: Project, left_retrieval_id: str, right_retrieval_id: str, *,
                     expected_revision: str, decision: str, actor: str, evidence: str,
                     acknowledged_warnings: tuple[str, ...], decision_confirmed: bool,
                     move_retrieval_id: str | None = None) -> CandidateSnapshot:
    """Append an explicit decision; confirmation atomically associates ONE record.

    Rejection never splits an existing identity; reverse it first. Researcher
    assertions do not authenticate a person's identity or verify source claims.
    This accepts only a fresh internally reconstructed review token. Caller-
    supplied comparison dictionaries are never accepted as authoritative.
    """
    pair = _pair(left_retrieval_id, right_retrieval_id)
    identity._text(actor, 200)
    identity._text(evidence)
    if not _hash_text(expected_revision) or decision not in ("confirmed_match", "rejected_match"):
        raise ValueError("A current review token and explicit match/rejection are required")
    if decision_confirmed is not True:
        raise ValueError("Explicit researcher decision confirmation is required")
    if (not isinstance(acknowledged_warnings, (tuple, list))
            or any(not isinstance(w, str) for w in acknowledged_warnings)
            or len(set(acknowledged_warnings)) != len(acknowledged_warnings)):
        raise ValueError("Explicit current warnings are required")
    warnings = sorted(acknowledged_warnings)
    if ((decision == "confirmed_match" and move_retrieval_id not in pair)
            or (decision == "rejected_match" and move_retrieval_id is not None)):
        raise ValueError("Confirmation specifies one contributing retrieval; rejection moves none")
    request = identity._hash([pair, expected_revision, decision, actor, evidence, warnings,
                              move_retrieval_id, RULE_VERSION])
    with _validated_project_connection(project) as db:
        db.execute("BEGIN IMMEDIATE")
        current, state = _view(db, pair)
        prior = next((r for r in reversed(current.prior_decisions) if r["pair"] == list(pair)), None)
        if prior and prior["request_sha256"] == request:
            if (prior["post_state_sha256"] != state or prior["method"] != RULE_VERSION
                    or current.prior_decisions[-1]["event_id"] != prior["event_id"]):
                raise identity.StalePublicationError("Decision evidence changed; reopen before retrying")
            return current
        if current.revision != expected_revision:
            raise identity.StalePublicationError("Candidate evidence changed; reopen before deciding")
        if warnings != list(current.warnings):
            raise ValueError("Acknowledge every current warning before deciding")
        association_event = None
        if decision == "confirmed_match":
            moving = pair.index(move_retrieval_id)
            other = 1 - moving
            before = identity._link(db, move_retrieval_id)
            identity._associate_in_transaction(
                db, move_retrieval_id, current.publication_ids[other],
                expected_source_revision=current.publication_revisions[moving],
                expected_target_revision=current.publication_revisions[other],
                actor=actor, evidence=evidence, same_publication_confirmed=True,
            )
            after = identity._link(db, move_retrieval_id)
            if after[1] != before[1]:
                association_event = after[1]
        elif current.publication_ids[0] == current.publication_ids[1]:
            raise ValueError("Reverse the existing association before rejecting this pair")
        _, sources, comparison, keys, after_state = _state(db, pair)
        receipt = dict(
            version=1, at_utc=_utc_now(), method=RULE_VERSION, pair=list(pair), source_keys=keys,
            source_hashes=[s["source_sha256"] for s in sources],
            comparison=_comparison_receipt(comparison),
            comparison_sha256=identity._hash(_comparison_receipt(comparison)),
            reviewed_context={"publication_ids": list(current.publication_ids),
                              "publication_revisions": list(current.publication_revisions),
                              "sources": list(current.sources)}, input_revision=expected_revision,
            previous_event_id=prior["event_id"] if prior else None, actor=actor, evidence=evidence,
            status=decision, warnings_acknowledged=warnings, request_sha256=request,
            post_state_sha256=after_state, association_event_id=association_event,
            moved_retrieval_id=move_retrieval_id,
        )
        identity._audit(db, DECISION_EVENT, receipt)
        return _view(db, pair)[0]
