"""Count-reconciled PubMed Create Date partitions for large ESearch queries.

P1-04b: bounded and auditable in-memory retrieval. This module does NOT claim
that PubMed contains all records within the caller's supplied date window,
that an identified record's metadata has been fetched, or that results can be
resumed after a process exits. Those are later separately verified steps.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Protocol

from research_y.pubmed_ids import (
    DEFAULT_PAGE_SIZE,
    DEFAULT_SINGLE_QUERY_CEILING,
    PubMedIdentifierResult,
    PubMedIdentifierPage,
    retrieve_bounded_identifiers,
)
from research_y.pubmed_probe import PubMedCountProbe, PubMedProbeError

# NCBI PubMed indexes record Create Date [crdt]; choose it rather than
# publication date because historical publication dates can be imprecise.
DATE_FIELD = "crdt"
DEFAULT_COUNT_PROBE_BUDGET = 255


class _CountClient(Protocol):
    def probe(
        self, exact_query: str, *, allow_crdt_partition: bool = False,
    ) -> PubMedCountProbe: ...

    def fetch_esearch_page(self, exact_query: str, *, retstart: int, retmax: int) -> bytes: ...


@dataclass(frozen=True, slots=True)
class DateWindow:
    start: date
    end: date

    def __post_init__(self) -> None:
        if not isinstance(self.start, date) or not isinstance(self.end, date):
            raise TypeError("Date windows require two absolute dates")
        if isinstance(self.start, datetime) or isinstance(self.end, datetime):
            raise TypeError("Provide calendar dates, not timestamps")
        if self.end < self.start:
            raise ValueError("Date window end must not precede start")

    def split(self) -> tuple[DateWindow, DateWindow]:
        """Split a multi-day inclusive date interval with no overlap or gaps."""
        if self.start == self.end:
            raise ValueError("Single-day interval cannot be partitioned by date")
        midpoint = self.start + timedelta(days=(self.end - self.start).days // 2)
        return DateWindow(self.start, midpoint), DateWindow(midpoint + timedelta(days=1), self.end)

    def query_for(self, approved_query: str) -> str:
        """Constrain only retrieval partition date; concepts remain OR-only."""
        left = self.start.isoformat().replace("-", "/")
        right = self.end.isoformat().replace("-", "/")
        return f"({approved_query}) AND ({left}:{right}[{DATE_FIELD}])"


@dataclass(frozen=True, slots=True)
class CountedPartition:
    index: int
    parent_index: int | None
    interval: DateWindow
    exact_subquery: str
    reported_matches: int
    depth: int
    decision: str  # split, collect, empty, unsplittable
    rationale: str


@dataclass(frozen=True, slots=True)
class PubMedPartitionResult:
    root_query: str
    date_window: DateWindow
    reported_root_matches: int | None
    status: str
    pmids: tuple[str, ...]
    counted_partitions: tuple[CountedPartition, ...]
    collected_leaves: tuple[PubMedIdentifierResult, ...]
    errors: tuple[str, ...] = ()
    # Identifiers alone do not verify metadata or final search completeness.
    source_retrieval_verified: bool = False

    @property
    def identifiers_reconciled(self) -> bool:
        return self.status == "identifiers_reconciled_metadata_pending"


class _PartitionStopped(Exception):
    def __init__(self, status: str, reason: str):
        self.status = status
        self.reason = reason
        super().__init__(reason)


def retrieve_date_partitioned_identifiers(
    client: _CountClient,
    approved_query: str,
    *,
    date_window: DateWindow,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_records: int = DEFAULT_SINGLE_QUERY_CEILING,
    max_count_probes: int = DEFAULT_COUNT_PROBE_BUDGET,
    on_plan_ready: Callable[[PubMedPartitionResult], None] | None = None,
    on_verified_page: Callable[[PubMedIdentifierPage], None] | None = None,
) -> PubMedPartitionResult:
    """Recursively count and collect an exact, non-overlapping date partition.

    The caller provides the intended global date coverage explicitly; none
    is invented. A baseline count is mandatory and every split must satisfy
    parent count == sum(disjoint child counts), with root == covered date total.
    Any unaccounted record, unverified translation, oversized single-day range,
    provider error or changing count returns an incomplete/review-required state.
    Full metadata acquisition and persistent checkpoints are later work.
    """
    if (not isinstance(approved_query, str) or not approved_query.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in approved_query)):
        raise ValueError("An approved exact query without control characters is required")
    if not isinstance(date_window, DateWindow):
        raise TypeError("date_window must be a DateWindow")
    if type(max_records) is not int or not 1 <= max_records <= DEFAULT_SINGLE_QUERY_CEILING:
        raise ValueError("max_records must be within the bounded ESearch ceiling")
    if type(page_size) is not int or not 1 <= page_size <= 1000:
        raise ValueError("page_size must be between 1 and 1000")
    if type(max_count_probes) is not int or not 1 <= max_count_probes <= 10000:
        raise ValueError("max_count_probes must be an integer from 1 to 10000")

    if on_plan_ready is not None and not callable(on_plan_ready):
        raise TypeError("on_plan_ready must be callable")
    if on_verified_page is not None and not callable(on_verified_page):
        raise TypeError("on_verified_page must be callable")

    partitions: list[CountedPartition] = []
    leaves: list[CountedPartition] = []
    collected: list[PubMedIdentifierResult] = []
    identifiers: list[str] = []
    seen: set[str] = set()
    root_count: int | None = None

    def report(status: str, *reasons: str) -> PubMedPartitionResult:
        return PubMedPartitionResult(
            approved_query, date_window, root_count, status, tuple(identifiers),
            tuple(partitions), tuple(collected), tuple(reasons),
        )

    try:
        try:
            baseline = client.probe(approved_query)
        except Exception:
            return report("incomplete", "PubMed baseline count request failed")
        root_count = baseline.reported_matches
        if baseline.review_required:
            return report("query_review_required", "Base query translation requires review")
        if root_count < 0:
            return report("incomplete", "Invalid source-reported baseline count")
        if root_count <= max_records:
            if on_plan_ready is not None:
                try:
                    on_plan_ready(report("incomplete"))
                except Exception:
                    return report("incomplete", "PubMed checkpoint plan could not be committed")
            # For bounded queries the original exact search can be collected
            # without introducing any administrative date constraint.
            try:
                small = retrieve_bounded_identifiers(
                    client, approved_query, page_size=page_size, max_records=max_records,
                    on_verified_page=on_verified_page,
                )
            except Exception:
                return report("incomplete", "Bounded identifier request failed; no completion is claimed")
            if small.identifiers_reconciled and small.reported_matches == root_count:
                identifiers.extend(small.pmids)
                collected.append(small)
                return report("identifiers_reconciled_metadata_pending")
            collected.append(small)
            return report("query_review_required" if small.status == "query_review_required"
                          else "incomplete", "Bounded identifier retrieval not reconciled")

        def count_window(window: DateWindow, parent: int | None, depth: int) -> tuple[int, int]:
            if len(partitions) >= max_count_probes:
                raise _PartitionStopped("incomplete", "Configured date-partition probe budget exceeded")
            query = window.query_for(approved_query)
            # Do not propagate provider exceptions that may include local or
            # credential details from an injected client implementation.
            try:
                probe = client.probe(query, allow_crdt_partition=True)
            except Exception as exc:
                raise _PartitionStopped("incomplete", "Date-partition count request failed") from None
            if probe.review_required:
                raise _PartitionStopped(
                    "query_review_required", "Partition query translation requires researcher review"
                )
            count = probe.reported_matches
            if type(count) is not int or count < 0:
                raise _PartitionStopped("incomplete", "Invalid partition count")
            if parent is None and count != root_count:
                raise _PartitionStopped(
                    "incomplete", "Requested Create Date range does not account for the unfiltered query count"
                )
            idx = len(partitions)
            decision = "empty" if count == 0 else "collect" if count <= max_records else (
                "unsplittable" if window.start == window.end else "split"
            )
            partitions.append(CountedPartition(
                idx, parent, window, query, count, depth, decision,
                "Count-only Create Date interval; administrative partition, not a concept restriction",
            ))
            if decision == "unsplittable":
                raise _PartitionStopped(
                    "incomplete", "Single Create Date still exceeds the safe ESearch identifier window"
                )
            if decision == "split":
                left, right = window.split()
                _, left_count = count_window(left, idx, depth + 1)
                _, right_count = count_window(right, idx, depth + 1)
                if left_count + right_count != count:
                    raise _PartitionStopped(
                        "incomplete", "Date partition child counts do not reconcile with their parent"
                    )
            elif decision == "collect":
                leaves.append(partitions[idx])
            return idx, count

        count_window(date_window, None, 0)
        if on_plan_ready is not None:
            try:
                on_plan_ready(report("incomplete"))
            except Exception:
                return report("incomplete", "PubMed checkpoint partition plan could not be committed")
        for leaf in leaves:
            try:
                result = retrieve_bounded_identifiers(
                    client, leaf.exact_subquery, page_size=page_size,
                    max_records=max_records, allow_crdt_partition=True,
                    on_verified_page=on_verified_page,
                )
            except Exception:
                return report("incomplete", "Date partition identifier retrieval failed; prior leaves retained")
            collected.append(result)
            if not result.identifiers_reconciled or result.reported_matches != leaf.reported_matches:
                return report(
                    "query_review_required" if result.status == "query_review_required" else "incomplete",
                    "Date partition identifier pages do not reconcile with count-only probe",
                )
            if seen.intersection(result.pmids):
                return report("incomplete", "PMIDs overlapped across disjoint Create Date intervals")
            seen.update(result.pmids)
            identifiers.extend(result.pmids)
        if len(seen) != root_count:
            return report("incomplete", "Unique PubMed ID union does not reconcile with the baseline count")
        # A changing PubMed collection can invalidate an otherwise consistent
        # partition run. Recheck the unfiltered count after the last page.
        try:
            final_probe = client.probe(approved_query)
        except Exception:
            return report("incomplete", "Final PubMed baseline recount failed")
        if final_probe.review_required:
            return report("query_review_required", "Final source query translation requires review")
        if final_probe.reported_matches != root_count:
            return report("incomplete", "PubMed baseline count changed during partition collection")
        return report("identifiers_reconciled_metadata_pending")
    except _PartitionStopped as stop:
        return report(stop.status, stop.reason)
    except PubMedProbeError:
        return report("incomplete", "PubMed baseline count request failed")
