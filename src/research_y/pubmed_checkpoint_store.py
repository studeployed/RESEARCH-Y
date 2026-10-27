"""Transactional, crash-resumable PubMed identifier page and partition ledger.

P1-04c: pages and their individual PMIDs are committed atomically to the
project's authoritative SQLite database. Reopening rechecks ledger hashes,
partition geometry and count provenance before network reuse. Count and query
translation are rechecked against PubMed before resuming any missing pages.

This does not retrieve metadata or certify end-to-end search completeness.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from hashlib import sha256
import json
import re
import sqlite3
from typing import Any

from research_y.projects import Project, _utc_now, _validated_project_connection
from research_y.pubmed_ids import (
    DEFAULT_SINGLE_QUERY_CEILING,
    PubMedIdentifierPage,
    parse_identifier_page,
)
from research_y.pubmed_partition import DateWindow, PubMedPartitionResult
from research_y.pubmed_probe import PubMedESearchProbeClient
from research_y.storage import _audit

MAX_LEAF_COUNT = DEFAULT_SINGLE_QUERY_CEILING
MAX_TOTAL_COUNT = 2**63 - 1
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_PMID = re.compile(r"[1-9][0-9]{0,31}\Z")


class CheckpointIntegrityError(ValueError):
    """Persisted checkpoint is inconsistent or has been changed; do not resume."""


@dataclass(frozen=True, slots=True)
class CheckpointSnapshot:
    query_id: str
    root_count: int
    stored_status: str
    pmids: tuple[str, ...]
    pages_committed: int
    pages_expected: int
    next_offsets: tuple[tuple[int, int], ...]
    identifiers_reconciled: bool
    # No amount of identifier-only progress can verify publication metadata.
    source_retrieval_verified: bool = False


@dataclass(frozen=True, slots=True)
class CheckpointResumeResult:
    status: str
    snapshot: CheckpointSnapshot
    error: str | None = None
    source_retrieval_verified: bool = False


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False)


def _hash(payload: str) -> str:
    return sha256(payload.encode("utf-8")).hexdigest()


def _positive_count(value: Any, *, zero: bool = True) -> int:
    if type(value) is not int or value < (0 if zero else 1) or value > MAX_TOTAL_COUNT:
        raise CheckpointIntegrityError("Invalid checkpoint source count")
    return value


def _query(query: Any) -> str:
    if (not isinstance(query, str) or not query.strip()
            or any(ord(c) < 32 or ord(c) == 127 for c in query)):
        raise CheckpointIntegrityError("Invalid exact source query")
    return query


def _sha(value: Any) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise CheckpointIntegrityError("Invalid checkpoint SHA-256 digest")
    return value


def _node_from_dict(node: dict[str, Any]) -> dict[str, Any]:
    """Validate one immutable, source-counted date-partition node."""
    try:
        index, parent = node["index"], node["parent_index"]
        start, end = date.fromisoformat(node["start"]), date.fromisoformat(node["end"])
        exact, count = _query(node["exact_subquery"]), _positive_count(node["reported_matches"])
        decision, depth, rationale = node["decision"], node["depth"], node["rationale"]
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise CheckpointIntegrityError("Malformed checkpoint partition plan") from None
    if (type(index) is not int or index < 0 or (parent is not None and
            (type(parent) is not int or parent < 0 or parent >= index))
            or type(depth) is not int or depth < 0 or not isinstance(rationale, str)
            or not rationale.strip()):
        raise CheckpointIntegrityError("Invalid partition identity or ancestry")
    if decision not in ("split", "collect", "empty"):
        raise CheckpointIntegrityError("Unfinished partition is not a resumable plan")
    window = DateWindow(start, end)
    return {
        "index": index, "parent_index": parent, "start": window.start.isoformat(),
        "end": window.end.isoformat(), "exact_subquery": exact,
        "reported_matches": count, "decision": decision, "depth": depth,
        "rationale": rationale,
    }


def _validate_plan(plan: dict[str, Any], exact_source_query: str) -> list[dict[str, Any]]:
    """Check complete, connected binary date partitions and exact provider text."""
    try:
        if plan["format_version"] != 1 or plan["root_query"] != exact_source_query:
            raise CheckpointIntegrityError("Checkpoint is not for the approved source query")
        root_count = _positive_count(plan["root_count"])
        page_size = plan["page_size"]
        if type(page_size) is not int or not 1 <= page_size <= 1000:
            raise CheckpointIntegrityError("Invalid checkpoint page size")
        raw_nodes = plan["partitions"]
        if not isinstance(raw_nodes, list):
            raise CheckpointIntegrityError("Invalid checkpoint partition list")
        nodes = [_node_from_dict(x) for x in raw_nodes]
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, CheckpointIntegrityError):
            raise
        raise CheckpointIntegrityError("Malformed checkpoint retrieval plan") from None
    if not nodes:
        if root_count > MAX_LEAF_COUNT:
            raise CheckpointIntegrityError("Oversized root requires a complete date partition plan")
        return [{"index": -1, "exact_subquery": exact_source_query,
                 "reported_matches": root_count, "decision": "collect" if root_count else "empty"}]
    if len(nodes) > 10_000:
        raise CheckpointIntegrityError("Excessive number of checkpoint partitions")
    first = nodes[0]
    if (first["index"] != 0 or first["parent_index"] is not None
            or first["depth"] != 0 or first["reported_matches"] != root_count):
        raise CheckpointIntegrityError("Root date partition does not reconcile")
    children: dict[int, list[dict[str, Any]]] = {}
    for i, node in enumerate(nodes):
        if node["index"] != i:
            raise CheckpointIntegrityError("Partition IDs must be consecutive")
        if node["exact_subquery"] != DateWindow(
            date.fromisoformat(node["start"]), date.fromisoformat(node["end"])
        ).query_for(exact_source_query):
            raise CheckpointIntegrityError("Persisted date subquery differs from approved query")
        parent = node["parent_index"]
        if i and parent is None:
            raise CheckpointIntegrityError("Disconnected partition node")
        if parent is not None:
            if node["depth"] != nodes[parent]["depth"] + 1:
                raise CheckpointIntegrityError("Invalid partition depth")
            children.setdefault(parent, []).append(node)
    for node in nodes:
        kids = children.get(node["index"], [])
        count, decision = node["reported_matches"], node["decision"]
        if decision == "split":
            if count <= 0 or len(kids) != 2:
                raise CheckpointIntegrityError("Invalid or unfinished count split")
            parent_window = DateWindow(date.fromisoformat(node["start"]), date.fromisoformat(node["end"]))
            if parent_window.start == parent_window.end:
                raise CheckpointIntegrityError("Single day cannot be split by Create Date")
            left, right = parent_window.split()
            kid_windows = [DateWindow(date.fromisoformat(k["start"]), date.fromisoformat(k["end"])) for k in kids]
            if kid_windows != [left, right] or sum(k["reported_matches"] for k in kids) != count:
                raise CheckpointIntegrityError("Date partitions overlap, have gaps or count mismatch")
        else:
            if kids or count > MAX_LEAF_COUNT or (decision == "empty") != (count == 0):
                raise CheckpointIntegrityError("Leaf count exceeds safe bounded retrieval")
    return [n for n in nodes if n["decision"] != "split"]


def _plan_from_result(result: PubMedPartitionResult, page_size: int) -> dict[str, Any]:
    if not isinstance(result, PubMedPartitionResult):
        raise TypeError("Expected a PubMedPartitionResult with source-counted partitions")
    if type(page_size) is not int or not 1 <= page_size <= 1000:
        raise ValueError("page_size must be between 1 and 1000")
    root_query = _query(result.root_query)
    root_count = _positive_count(result.reported_root_matches)
    nodes = [
        {"index": n.index, "parent_index": n.parent_index,
         "start": n.interval.start.isoformat(), "end": n.interval.end.isoformat(),
         "exact_subquery": n.exact_subquery, "reported_matches": n.reported_matches,
         "decision": n.decision, "depth": n.depth, "rationale": n.rationale}
        for n in result.counted_partitions
    ]
    plan = {"format_version": 1, "root_query": root_query, "root_count": root_count,
            "page_size": page_size, "partitions": nodes}
    _validate_plan(plan, root_query)
    return plan


def _find_query(connection: sqlite3.Connection, query_id: str) -> tuple[str, str]:
    if not isinstance(query_id, str) or not query_id.strip():
        raise ValueError("query_id is required")
    row = connection.execute(
        "SELECT source_name, exact_query FROM source_queries WHERE query_id=?", (query_id,)
    ).fetchone()
    if row is None:
        raise KeyError("Unknown approved source query")
    if row[0] != "pubmed":
        raise ValueError("Only PubMed source queries support these checkpoints")
    return row


def create_pubmed_checkpoint(
    project: Project, query_id: str, result: PubMedPartitionResult, *, page_size: int = 200,
) -> CheckpointSnapshot:
    """Persist a complete counted partition plan under a real approved query.

    Existing plans are strictly immutable: an identical plan is idempotent;
    creating another on the same query with changed counts requires a *new*
    run/query, preserving the older plan and its audit history.
    """
    if result.status not in ("incomplete", "identifiers_reconciled_metadata_pending"):
        raise CheckpointIntegrityError("Unverified or rejected count plan cannot be checkpointed")
    plan = _plan_from_result(result, page_size)
    encoded, digest = _json(plan), _hash(_json(plan))
    now = _utc_now()
    with _validated_project_connection(project) as con:
        con.execute("BEGIN IMMEDIATE")
        source_name, stored_query = _find_query(con, query_id)
        if plan["root_query"] != stored_query:
            raise CheckpointIntegrityError("Approved query differs from stored source query")
        prior = con.execute(
            "SELECT plan_sha256 FROM pubmed_checkpoint_runs WHERE query_id=?", (query_id,)
        ).fetchone()
        if prior is not None:
            if prior[0] != digest:
                raise CheckpointIntegrityError("A different immutable checkpoint plan already exists")
        else:
            con.execute(
                "INSERT INTO pubmed_checkpoint_runs "
                "(query_id, root_query, root_count, plan_json, plan_sha256, created_at_utc, updated_at_utc) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (query_id, stored_query, plan["root_count"], encoded, digest, now, now),
            )
            con.execute(
                "UPDATE source_queries SET status='incomplete', reported_matches=?, "
                "executed_at_utc=? WHERE query_id=?",
                (plan["root_count"], now, query_id),
            )
            _audit(con, kind="pubmed_checkpoint_created", timestamp=now,
                   details={"query_id": query_id, "plan_sha256": digest,
                            "root_count": plan["root_count"], "partitions": len(plan["partitions"])})
    return inspect_pubmed_checkpoint(project, query_id)


def _load_checkpoint(con: sqlite3.Connection, query_id: str):
    _, source_query = _find_query(con, query_id)
    row = con.execute(
        "SELECT root_query,root_count,plan_json,plan_sha256,status "
        "FROM pubmed_checkpoint_runs WHERE query_id=?", (query_id,)
    ).fetchone()
    if row is None:
        raise KeyError("No PubMed checkpoint exists for the source query")
    root, count, encoded, digest, status = row
    try:
        if _hash(encoded) != _sha(digest):
            raise CheckpointIntegrityError("Checkpoint plan digest mismatch")
        plan = json.loads(encoded)
        leaves = _validate_plan(plan, source_query)
        if root != source_query or count != plan["root_count"]:
            raise CheckpointIntegrityError("Checkpoint metadata does not match source query")
        if status not in ("incomplete", "paused", "identifiers_reconciled_metadata_pending"):
            raise CheckpointIntegrityError("Unknown checkpoint status")
    except (TypeError, ValueError, KeyError, OverflowError) as exc:
        if isinstance(exc, CheckpointIntegrityError):
            raise
        raise CheckpointIntegrityError("Checkpoint retrieval plan is damaged") from None
    return plan, leaves, status


def _page_payload(page: PubMedIdentifierPage, partition_index: int) -> dict[str, Any]:
    return {
        "partition_index": partition_index, "retstart": page.retstart,
        "retmax": page.requested_retmax, "pmids": list(page.pmids),
        "reported_matches": page.reported_matches, "exact_query": page.exact_query,
        "accepted_translation": page.accepted_translation,
        "warnings": list(page.warnings), "review_reasons": list(page.review_reasons),
        "response_sha256": page.response_sha256, "retrieved_at_utc": page.retrieved_at_utc,
    }


def _canonical_ids(items: Any) -> tuple[str, ...]:
    if not isinstance(items, list) or len(items) > 1000:
        raise CheckpointIntegrityError("Checkpoint page has an invalid PMID array")
    for v in items:
        if not isinstance(v, str) or not _PMID.fullmatch(v):
            raise CheckpointIntegrityError("Checkpoint page contains an invalid PMID")
    if len(set(items)) != len(items):
        raise CheckpointIntegrityError("Checkpoint page contains repeated identifiers")
    return tuple(items)


def _validated_pages(con, query_id, plan, leaves):
    page_size = plan["page_size"]
    valid_leaves = {x["index"]: x for x in leaves}
    pages = con.execute(
        "SELECT partition_index,retstart,retmax,page_json,page_sha256 "
        "FROM pubmed_checkpoint_pages WHERE query_id=? "
        "ORDER BY partition_index,retstart", (query_id,)
    ).fetchall()
    by_leaf: dict[int, tuple[str, ...]] = {i: () for i in valid_leaves}
    next_offset: dict[int, int] = {i: 0 for i in valid_leaves}
    global_ids: set[str] = set()
    every_pmid: list[str] = []
    for partition, offset, requested, raw, digest in pages:
        if partition not in valid_leaves or type(offset) is not int or type(requested) is not int:
            raise CheckpointIntegrityError("Checkpoint page refers to an invalid partition")
        if _hash(raw) != _sha(digest):
            raise CheckpointIntegrityError("Checkpoint page checksum differs from committed data")
        try:
            p = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            raise CheckpointIntegrityError("Cannot decode checkpoint page") from None
        leaf = valid_leaves[partition]
        count = leaf["reported_matches"]
        expected_max = min(page_size, count - offset)
        if (offset != next_offset[partition] or requested != expected_max
                or requested <= 0 or p.get("retstart") != offset
                or p.get("retmax") != requested or p.get("partition_index") != partition
                or p.get("exact_query") != leaf["exact_subquery"]
                or p.get("reported_matches") != count
                or p.get("accepted_translation") != leaf["exact_subquery"]
                or p.get("warnings") != [] or p.get("review_reasons") != []):
            raise CheckpointIntegrityError("Checkpoint page does not match immutable partition/count")
        _sha(p.get("response_sha256"))
        ids = _canonical_ids(p.get("pmids"))
        if len(ids) != requested or global_ids.intersection(ids):
            raise CheckpointIntegrityError("Checkpoint has truncated or overlapping identifiers")
        global_ids.update(ids)
        every_pmid.extend(ids)
        by_leaf[partition] += ids
        next_offset[partition] += len(ids)
    # The identifier index is independently stored and must be the exact set
    # implied by the immutable pages. Tampering with either table is detected.
    indexed = con.execute(
        "SELECT pmid,partition_index,retstart FROM pubmed_checkpoint_ids WHERE query_id=?",
        (query_id,),
    ).fetchall()
    index_map = {(pid, partition, offset) for pid, partition, offset in indexed}
    expected_map: set[tuple[str, int, int]] = set()
    for partition, offset, _max, raw, _digest in pages:
        for pid in json.loads(raw)["pmids"]:
            expected_map.add((pid, partition, offset))
    if index_map != expected_map or len(indexed) != len(every_pmid):
        raise CheckpointIntegrityError("Checkpoint identifier index differs from committed pages")
    return pages, by_leaf, next_offset, tuple(every_pmid)


def _snapshot_from_db(con, query_id: str) -> CheckpointSnapshot:
    plan, leaves, status = _load_checkpoint(con, query_id)
    pages, by_leaf, offsets, ids = _validated_pages(con, query_id, plan, leaves)
    expected_pages = sum(
        (n["reported_matches"] + plan["page_size"] - 1) // plan["page_size"] for n in leaves
    )
    complete = (len(pages) == expected_pages
                and all(offsets[n["index"]] == n["reported_matches"] for n in leaves)
                and len(ids) == plan["root_count"] and len(set(ids)) == len(ids))
    if status == "identifiers_reconciled_metadata_pending" and not complete:
        raise CheckpointIntegrityError("Checkpoint status claims missing identifier pages")
    return CheckpointSnapshot(
        query_id, plan["root_count"], status, ids,
        len(pages), expected_pages, tuple(sorted(offsets.items())), complete,
    )


def inspect_pubmed_checkpoint(project: Project, query_id: str) -> CheckpointSnapshot:
    """Validate all stored page checksums, offsets and independent PMID index."""
    with _validated_project_connection(project) as con:
        return _snapshot_from_db(con, query_id)


def _find_leaf(leaves: list[dict[str, Any]], query: str) -> dict[str, Any]:
    matches = [leaf for leaf in leaves if leaf["exact_subquery"] == query]
    if len(matches) != 1:
        raise CheckpointIntegrityError("Page belongs to no unique planned partition")
    return matches[0]


def commit_pubmed_checkpoint_page(
    project: Project, query_id: str, page: PubMedIdentifierPage,
) -> CheckpointSnapshot:
    """Commit an already validated page, unique PMIDs and audit atomically.

    An identical offset replay is a no-op. A conflicting offset or PMID in a
    different page/partition cannot overwrite the original, even after a crash.
    """
    if not isinstance(page, PubMedIdentifierPage):
        raise TypeError("Page must be a validated PubMedIdentifierPage")
    if page.review_required or page.accepted_translation != page.exact_query or page.warnings:
        raise CheckpointIntegrityError("Only source-accepted, warning-free ID pages may be saved")
    with _validated_project_connection(project) as con:
        con.execute("BEGIN IMMEDIATE")
        plan, leaves, _state = _load_checkpoint(con, query_id)
        leaf = _find_leaf(leaves, page.exact_query)
        if (page.reported_matches != leaf["reported_matches"]
                or type(page.retstart) is not int or page.retstart < 0
                or type(page.requested_retmax) is not int
                or not 1 <= page.requested_retmax <= plan["page_size"]
                or page.retstart + page.requested_retmax > leaf["reported_matches"]
                or len(page.pmids) != page.requested_retmax
                or len(set(page.pmids)) != len(page.pmids)):
            raise CheckpointIntegrityError("Page boundaries, count or PMIDs are inconsistent")
        _sha(page.response_sha256)
        _canonical_ids(list(page.pmids))
        payload = _json(_page_payload(page, leaf["index"]))
        digest = _hash(payload)
        previous = con.execute(
            "SELECT page_json,page_sha256 FROM pubmed_checkpoint_pages "
            "WHERE query_id=? AND partition_index=? AND retstart=?",
            (query_id, leaf["index"], page.retstart),
        ).fetchone()
        if previous:
            if previous == (payload, digest):
                return _snapshot_from_db(con, query_id)
            raise CheckpointIntegrityError("Cannot replace an existing immutable PMID page")
        # Enforce sequential pages. Only committed data may be advanced past.
        _pages, _leaf_ids, offsets, _all = _validated_pages(con, query_id, plan, leaves)
        if offsets[leaf["index"]] != page.retstart:
            raise CheckpointIntegrityError("Cannot skip an uncommitted PMID page offset")
        if page.requested_retmax != min(plan["page_size"], leaf["reported_matches"] - page.retstart):
            raise CheckpointIntegrityError("Page size does not match the frozen paging plan")
        con.execute(
            "INSERT INTO pubmed_checkpoint_pages "
            "(query_id,partition_index,retstart,retmax,page_json,page_sha256,retrieved_at_utc) "
            "VALUES (?,?,?,?,?,?,?)",
            (query_id, leaf["index"], page.retstart, page.requested_retmax,
             payload, digest, page.retrieved_at_utc),
        )
        try:
            con.executemany(
                "INSERT INTO pubmed_checkpoint_ids (query_id,pmid,partition_index,retstart) "
                "VALUES (?,?,?,?)",
                [(query_id, x, leaf["index"], page.retstart) for x in page.pmids],
            )
        except sqlite3.IntegrityError:
            raise CheckpointIntegrityError("PMIDs overlap with previously committed pages") from None
        if _state != "paused":
            con.execute(
                "UPDATE pubmed_checkpoint_runs SET status='incomplete',updated_at_utc=? WHERE query_id=?",
                (_utc_now(), query_id),
            )
        _audit(con, kind="pubmed_checkpoint_page_committed", timestamp=_utc_now(),
               details={"query_id": query_id, "partition_index": leaf["index"],
                        "retstart": page.retstart, "pmid_count": len(page.pmids),
                        "page_sha256": digest, "provider_response_sha256": page.response_sha256})
        return _snapshot_from_db(con, query_id)


def _set_checkpoint_status(
    project: Project, query_id: str, status: str, reason: str,
    *, preserve_pause: bool = False,
) -> None:
    if status not in ("incomplete", "paused", "identifiers_reconciled_metadata_pending"):
        raise ValueError("A checkpoint cannot mark a source search completed_verified")
    with _validated_project_connection(project) as con:
        con.execute("BEGIN IMMEDIATE")
        previous = _snapshot_from_db(con, query_id)
        # The write lock is held. A user pause cannot be lost to a later
        # failure transition even if the pause arrived after a caller read.
        if preserve_pause and previous.stored_status == "paused":
            return
        if status == "identifiers_reconciled_metadata_pending" and not previous.identifiers_reconciled:
            raise CheckpointIntegrityError("Identifier pages have not reconciled")
        if previous.stored_status == status:
            return
        con.execute(
            "UPDATE pubmed_checkpoint_runs SET status=?,updated_at_utc=? WHERE query_id=?",
            (status, _utc_now(), query_id),
        )
        con.execute(
            "UPDATE source_queries SET status=? WHERE query_id=?",
            ("paused" if status == "paused" else "incomplete", query_id),
        )
        _audit(con, kind="pubmed_checkpoint_status", timestamp=_utc_now(),
               details={"query_id": query_id, "status": status, "reason": reason})


def pause_pubmed_checkpoint(project: Project, query_id: str) -> CheckpointSnapshot:
    _set_checkpoint_status(project, query_id, "paused", "User paused identifier retrieval")
    return inspect_pubmed_checkpoint(project, query_id)


