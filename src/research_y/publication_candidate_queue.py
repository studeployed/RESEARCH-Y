"""Read-only, project-spanning exact-key candidate discovery with bounded paging.

Every retained, materialised PubMed/WoS source record across project runs is
eligible for an in-memory inverted index. Only pairs touching the SELECTED run
appear in its queue. Matching keys are review HINTS, not publication identity.
Past candidate receipts remain discoverable even after their keys change.

No duplicate is merged, no metadata is normalised in storage, and a discovered
pair count is NEVER a final unique-publication count. Any size/integrity limit
fails explicitly instead of silently truncating the queue.
"""
from __future__ import annotations

from collections import defaultdict
from itertools import chain, combinations, product, groupby

from research_y.application_inspection import _read
from research_y import publication_identity as identity
from research_y import publication_candidates as candidates
from research_y import result_counts
from research_y.publication_match_evidence import project_source
from research_y import candidate_index_build

METHOD = "project-candidate-queue/1"
FIELDS = ("doi", "pmid", "accession", "title")
PAGE_SIZE = 20
MAX_PROJECT_RECORDS = 100_000
MAX_PAIR_CANDIDATES = 100_000


class CandidateQueueError(RuntimeError):
    """Static codes suitable for the GUI; never echo private source contents."""

    def __init__(self, code="candidate_queue_unavailable"):
        self.code = code if code in (
            "candidate_queue_unavailable", "candidate_queue_invalid",
            "candidate_queue_stale", "candidate_queue_over_limit",
        ) else "candidate_queue_unavailable"
        super().__init__(self.code)


def _digest(value, *, optional=False):
    if optional and value is None:
        return
    if (type(value) is not str or len(value) != 64 or
            any(c not in "0123456789abcdef" for c in value)):
        raise CandidateQueueError("candidate_queue_invalid")


def _cursor(value):
    if value is None:
        return None
    if (type(value) is not tuple or len(value) != 2 or
            any(type(s) is not str for s in value)):
        raise CandidateQueueError("candidate_queue_invalid")
    try:
        pair = candidates._pair(*value)
    except (ValueError, TypeError):
        raise CandidateQueueError("candidate_queue_invalid") from None
    if pair != value:
        raise CandidateQueueError("candidate_queue_invalid")
    return pair


def _bucket_pairs(bucket, records, run_id):
    """Generate ONLY pairs touching the selected run, never historical-only.

    Partitioning before enumeration avoids quadratic work in a large bucket
    made entirely of older sources. The caller applies its overall explicit
    candidate-pair budget to emitted pairs, including dense cross-run keys.
    """
    ordered = sorted(bucket)
    selected = [rid for rid in ordered if records[rid]["run_id"] == run_id]
    if not selected:
        return
    historical = [rid for rid in ordered if records[rid]["run_id"] != run_id]
    for left, right in chain(combinations(selected, 2),
                             product(selected, historical)):
        yield (left, right) if left < right else (right, left)


def _original_index(db, project, run_id):
    """One read-only SQLite snapshot; no cache, schema migration or temp writes.

    The original run-count validator and candidate receipt validator remain the
    authority for source/identity/audit evidence. A Python inverted index
    prevents all-against-all comparison for different exact citation keys.
    """
    counts = result_counts._snapshot(db, project, run_id)
    # The count projection verifies THIS run. Other runs contribute potential
    # matches and are checked from original identity-backed retrieval rows.
    index = defaultdict(list)
    records = {}
    fingerprints = []
    total = unsupported = unmaterialised = 0
    for (rid,) in db.execute(
            "SELECT retrieval_id FROM source_retrievals ORDER BY retrieval_id"):
        total += 1
        if total > MAX_PROJECT_RECORDS:
            raise CandidateQueueError("candidate_queue_over_limit")
        identity._identifier(rid)
        source = identity._source(db, rid)
        # Preserve source identity and source-record scope, even for historical
        # records outside the selected run. Unrecognised layouts do not become
        # fabricated comparable bibliography.
        if source["source_name"] in ("pubmed", "wos"):
            record = source["original_metadata"].get("record")
            name = "pmid" if source["source_name"] == "pubmed" else "uid"
            if (not isinstance(record, dict) or
                    record.get(name) != source["source_record_id"]):
                raise CandidateQueueError("candidate_queue_unavailable")
        link = identity._link(db, rid)
        fingerprints.append((
            rid, source["source_sha256"], source["run_status"],
            None if link is None else link[0],
            None if link is None else link[1],
        ))
        if link is None:
            unmaterialised += 1
            continue
        projected = project_source(source)
        if "unsupported_source_layout" in projected["warnings"]:
            unsupported += 1
            continue
        records[rid] = dict(
            retrieval_id=rid, run_id=source["run_id"],
            source_name=source["source_name"],
            source_record_id=source["source_record_id"],
            publication_id=link[0],
        )
        for field in FIELDS:
            state = projected["fields"][field]
            value = state["normalised"]
            if state["status"] == "present" and type(value) is str:
                index[field, value].append(rid)

    # All prior decisions are original persisted evidence, not discoverable
    # solely through titles. They may remain relevant after a bibliographic
    # correction or a researcher reverses an earlier association.
    receipts = candidates._receipts(db, None)
    by_pair = {}
    for r in receipts:
        pair = tuple(r["pair"])
        if (all(rid in records for rid in pair)
                and any(records[rid]["run_id"] == run_id for rid in pair)):
            by_pair[pair] = r

    pairs = {}
    for (field, _value), bucket in sorted(index.items()):
        if len(bucket) < 2:
            continue
        for pair in _bucket_pairs(bucket, records, run_id):
            fields = pairs.setdefault(pair, set())
            fields.add(field)
            if len(pairs) > MAX_PAIR_CANDIDATES:
                raise CandidateQueueError("candidate_queue_over_limit")
    for pair in by_pair:
        pairs.setdefault(pair, set())
        if len(pairs) > MAX_PAIR_CANDIDATES:
            raise CandidateQueueError("candidate_queue_over_limit")

    # A historical run or source query can change after a first-page preview.
    # Bind its context as well: current identity/review evidence depends on the
    # source's run/query statuses and memberships, not only its metadata JSON.
    project_run_context = list(db.execute(
        "SELECT run_id,strategy_version_id,status,completed_at_utc "
        "FROM search_runs ORDER BY run_id"))
    project_query_context = list(db.execute(
        "SELECT query_id,run_id,group_id,source_name,exact_query,"
        "parameters_json,reported_matches,status,executed_at_utc "
        "FROM source_queries ORDER BY query_id"))
    project_memberships = list(db.execute(
        "SELECT query_id,retrieval_id,run_id,source_name "
        "FROM query_retrievals ORDER BY query_id,retrieval_id"))
    revision = identity._hash([
        METHOD, str(project.identifier), run_id, counts.revision,
        fingerprints, project_run_context, project_query_context,
        project_memberships,
        [(r["event_id"], r["pair"], r["post_state_sha256"],
          r["comparison_sha256"], r["status"]) for r in receipts],
    ])
    return dict(
        projection=counts, revision=revision, records=records,
        pairs=pairs, by_pair=by_pair, total=total,
        unsupported=unsupported, unmaterialised=unmaterialised,
        index_backend="original_source_projection",
        index_status="not_built",
        index_generation_id=None,
    )



# The cache is a *derivative*. Its keys are only used once its transactional
# original-source mutation epoch, generation, table counters and cursor have
# been verified. A normal source insert/update/delete invalidates it inside
# that source transaction. Match/reject/reverse decisions are always resolved
# anew from canonical audit/identity records, never from cached decisions.
_CACHE_KEYS_SQL = (
    "SELECT k.field,k.value_sha256,k.retrieval_id "
    "FROM candidate_index_keys k "
    "JOIN candidate_index_records i ON i.retrieval_id=k.retrieval_id "
    "JOIN publication_retrievals l ON l.retrieval_id=k.retrieval_id "
    "WHERE i.supported=1 "
    "ORDER BY k.field,k.value_sha256,k.retrieval_id"
)


def _cached_index(db, project, run_id, cache):
    """Index-backed exact-key matching without rereading all provider payloads.

    Source-only cache keys are checked against canonical candidate details on
    the returned page. Historical decisions, statuses and memberships are
    always read from original project SQLite; a ready cache never establishes
    a verified publication or complete retrieval.
    """
    counts = result_counts._snapshot(db, project, run_id)
    total = cache["source_records"]
    if total > MAX_PROJECT_RECORDS:
        raise CandidateQueueError("candidate_queue_over_limit")
    supported = {}
    for rid, rid_run, source, external_id, pub in db.execute(
        "SELECT r.retrieval_id,r.run_id,r.source_name,r.source_record_id,"
        "l.publication_id FROM candidate_index_records i "
        "JOIN source_retrievals r ON r.retrieval_id=i.retrieval_id "
        "JOIN publication_retrievals l ON l.retrieval_id=i.retrieval_id "
        "WHERE i.supported=1 ORDER BY i.retrieval_id"
    ):
        identity._identifier(rid); identity._identifier(rid_run)
        supported[rid] = dict(
            retrieval_id=rid, run_id=rid_run, source_name=source,
            source_record_id=external_id, publication_id=pub,
        )
    # An unmaterialised source is still in the durable cache's total, but
    # cannot be a candidate without a provisional publication identity.
    unmaterialised = db.execute(
        "SELECT COUNT(*) FROM source_retrievals r LEFT JOIN "
        "publication_retrievals l ON l.retrieval_id=r.retrieval_id "
        "WHERE l.retrieval_id IS NULL"
    ).fetchone()[0]
    # Match the PR73 denominator: unsupported but LINKED source retrievals
    # are reported here; unmaterialised sources have their own denominator.
    unsupported_linked = db.execute(
        "SELECT COUNT(*) FROM candidate_index_records i "
        "JOIN publication_retrievals l ON l.retrieval_id=i.retrieval_id "
        "WHERE i.supported=0"
    ).fetchone()[0]
    receipts = candidates._receipts(db, None)
    by_pair = {}
    for receipt in receipts:
        pair = tuple(receipt["pair"])
        if (all(rid in supported for rid in pair)
                and any(supported[rid]["run_id"] == run_id for rid in pair)):
            by_pair[pair] = receipt
    pairs = {}
    # Streaming original SQLite index order, not building a Python dictionary
    # of every raw title/DOI or examining the licensed metadata again.
    for _, rows in groupby(db.execute(_CACHE_KEYS_SQL),
                           key=lambda row: (row[0], row[1])):
        bucket = []
        field = None
        for key_name, _, rid in rows:
            field = key_name
            if rid not in supported:
                raise CandidateQueueError()
            bucket.append(rid)
        if len(bucket) < 2:
            continue
        for pair in _bucket_pairs(bucket, supported, run_id):
            pairs.setdefault(pair, set()).add(field)
            if len(pairs) > MAX_PAIR_CANDIDATES:
                raise CandidateQueueError("candidate_queue_over_limit")
    for pair in by_pair:
        pairs.setdefault(pair, set())
        if len(pairs) > MAX_PAIR_CANDIDATES:
            raise CandidateQueueError("candidate_queue_over_limit")
    # A source mutation is fenced by SQLite triggers and the source epoch.
    # Changes to *other run* status, query/group context or publication links
    # still invalidate pagination even though source-only keys remain valid.
    run_context = list(db.execute(
        "SELECT run_id,strategy_version_id,status,completed_at_utc "
        "FROM search_runs ORDER BY run_id"))
    query_context = list(db.execute(
        "SELECT query_id,run_id,group_id,source_name,exact_query,"
        "parameters_json,reported_matches,status,executed_at_utc "
        "FROM source_queries ORDER BY query_id"))
    memberships = list(db.execute(
        "SELECT query_id,retrieval_id,run_id,source_name "
        "FROM query_retrievals ORDER BY query_id,retrieval_id"))
    link_context = list(db.execute(
        "SELECT retrieval_id,publication_id,decision_provenance_json "
        "FROM publication_retrievals ORDER BY retrieval_id"))
    revision = identity._hash([
        METHOD, "indexed-cache-v5", str(project.identifier), run_id,
        counts.revision,
        (cache["generation_id"], cache["source_epoch"],
         cache["running_sha256"], cache["processed_records"],
         cache["indexed_keys"], cache["unsupported_records"]),
        run_context, query_context, memberships, link_context,
        [(r["event_id"], r["pair"], r["post_state_sha256"],
          r["comparison_sha256"], r["status"]) for r in receipts],
    ])
    return dict(
        projection=counts, revision=revision, records=supported,
        pairs=pairs, by_pair=by_pair, total=total,
        unsupported=unsupported_linked,
        unmaterialised=unmaterialised,
        index_backend="verified_derived_keys_v5",
        index_status="ready",
        index_generation_id=cache["generation_id"],
    )


def _index(db, project, run_id):
    cache = candidate_index_build._state(db, full_cache_check=True)
    if cache["status"] == "ready":
        return _cached_index(db, project, run_id, cache)
    # An empty, building or stale cache is NEVER consumed. The PR73 original
    # source projection remains available offline and retains its own budget.
    original = _original_index(db, project, run_id)
    original["index_status"] = cache["status"]
    original["index_generation_id"] = cache["generation_id"]
    return original


def read_candidate_queue(project, run_id: str, *,
                         after_pair: tuple[str, str] | None = None,
                         expected_revision: str | None = None) -> dict:
    """Keyset page of exact-key/prior-receipt hints touching the selected run.

    A cursor requires the original full-project revision, so a concurrent
    source correction or review cannot silently skip newly discovered pairs.
    There is no network access, no mutable index, and no source data export.
    """
    try:
        identity._identifier(run_id)
        cursor = _cursor(after_pair)
        _digest(expected_revision, optional=True)
        if cursor is not None and expected_revision is None:
            raise CandidateQueueError("candidate_queue_invalid")
        with _read(project) as db:
            found = _index(db, project, run_id)
            if (expected_revision is not None
                    and found["revision"] != expected_revision):
                raise CandidateQueueError("candidate_queue_stale")
            if cursor is not None and cursor not in found["pairs"]:
                raise CandidateQueueError("candidate_queue_stale")
            ordered = sorted(found["pairs"])
            remaining = [pair for pair in ordered if cursor is None or pair > cursor]
            shown = remaining[:PAGE_SIZE]
            rows = []
            for pair in shown:
                candidate, _ = candidates._view(db, pair)
                # Refuse a forged/out-of-date cached hint: the original
                # canonical citation comparison must still substantiate each
                # field shown as an exact match. A prior-only decision pair
                # legitimately has no matching current key.
                if (found["index_backend"] == "verified_derived_keys_v5" and
                        any(candidate.comparison["comparisons"].get(field) != "equal"
                            for field in found["pairs"][pair])):
                    raise CandidateQueueError()
                # The detailed comparison may contain restricted source values.
                # Do not return it through the queue; preserve only reason codes.
                records = [found["records"][rid] for rid in pair]
                rows.append(dict(
                    retrieval_ids=list(pair),
                    sources=[dict(record) for record in records],
                    matched_exact_fields=sorted(found["pairs"][pair]),
                    candidate_status=candidate.status,
                    warnings=list(candidate.warnings),
                    current_publication_ids=list(candidate.publication_ids),
                    pair_already_associated=(
                        candidate.publication_ids[0] == candidate.publication_ids[1]),
                    prior_decisions_recorded=len(candidate.prior_decisions),
                    last_decision_event_id=(
                        candidate.prior_decisions[-1]["event_id"]
                        if candidate.prior_decisions else None),
                    both_in_selected_run=all(s["run_id"] == run_id for s in records),
                    auto_merge_allowed=False,
                ))
            return dict(
                method=METHOD, project_id=str(project.identifier),
                run_id=run_id, revision=found["revision"],
                selected_run_revision=found["projection"].revision,
                after_pair=None if cursor is None else list(cursor),
                rows=rows, page_size=PAGE_SIZE,
                next_after_pair=list(shown[-1]) if len(remaining) > PAGE_SIZE else None,
                has_more=len(remaining) > PAGE_SIZE,
                candidate_pair_total=len(ordered),
                project_source_records=found["total"],
                index_backend=found["index_backend"],
                index_status=found["index_status"],
                index_generation_id=found["index_generation_id"],
                unmaterialised_project_records=found["unmaterialised"],
                unsupported_project_records=found["unsupported"],
                prior_receipt_pairs=len(found["by_pair"]),
                discovery_scope="project_sources_pairs_touching_selected_run",
                discovery_methods=list(FIELDS) + ["prior_candidate_receipts"],
                exact_rule_coverage_complete=True,
                exhaustive_duplicate_discovery=False,
                candidate_discovery_complete=False,
                source_retrieval_verified=False, verified_complete=False,
                deduplication_complete=False, global_unique_publications=None,
                no_network_requests=True,
                warnings=[
                    "exact_title_identifier_matches_are_review_hints_not_merges",
                    "unsupported_or_unmaterialised_sources_not_compared",
                    "no_fuzzy_or_full_text_duplicate_discovery",
                    "historical_cross_run_pairs_require_separate_review",
                    "not_a_verified_global_unique_publication_count",
                    *([] if found["index_status"] == "ready"
                      else ["derived_source_key_cache_not_ready_original_scan_used"]),
                ],
            )
    except CandidateQueueError:
        raise
    except Exception:
        raise CandidateQueueError() from None
