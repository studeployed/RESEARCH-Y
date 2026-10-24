"""Count-only recursive date partitions and complete unique-ID union fixtures."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
import json
import re

import pytest

from research_y.pubmed_partition import (
    DATE_FIELD, CountedPartition, DateWindow, PubMedPartitionResult,
    retrieve_date_partitioned_identifiers,
)
from research_y.pubmed_probe import PubMedCountProbe, PubMedProbeError

Q = '("right ventricle"[All Fields])'
WINDOW = DateWindow(date(2025, 1, 1), date(2025, 1, 2))


class FakeClient:
    """Separate independent counts and pages with a stable, reproducible corpus."""

    def __init__(self, records: dict[date, list[str]], *, root_override: int | None = None):
        self.records = records
        self.root_override = root_override
        self.probes: list[str] = []
        self.pages: list[tuple[str, int, int]] = []
        self.bad_translation_for: str | None = None
        self.crash_page_offset: int | None = None
        self.inject_page_overlap: bool = False
        self.probe_calls: Counter[str] = Counter()
        self.changing_counts_for: str | None = None
        self.count_delta_after_first: int = 1

    def ids(self, query: str) -> list[str]:
        match = re.search(r'\((\d{4}/\d\d/\d\d):(\d{4}/\d\d/\d\d)\[crdt\]\)', query)
        if match:
            lo, hi = (date.fromisoformat(v.replace('/', '-')) for v in match.groups())
            return [v for day, values in sorted(self.records.items()) if lo <= day <= hi for v in values]
        return [v for day, values in sorted(self.records.items()) for v in values]

    def count(self, query: str) -> int:
        raw = len(self.ids(query))
        if query == Q and self.root_override is not None:
            return self.root_override
        if query == self.changing_counts_for and self.probe_calls[query] > 1:
            return raw + self.count_delta_after_first
        return raw

    def probe(
        self, query: str, *, allow_crdt_partition: bool = False,
    ) -> PubMedCountProbe:
        self.probes.append(query)
        self.probe_calls[query] += 1
        if self.bad_translation_for and self.bad_translation_for in query:
            return PubMedCountProbe(
                query, '("unexpected"[All Fields])', self.count(query),
                '2026-10-24T00:00:00+00:00', (), ('Translation changed',), False,
            )
        from research_y.pubmed_probe import _review_translation
        reasons = _review_translation(
            query, query, (), allow_crdt_partition=allow_crdt_partition,
        )
        return PubMedCountProbe(query, query, self.count(query),
                                '2026-10-24T00:00:00+00:00', (), reasons, True)

    def fetch_esearch_page(self, query: str, *, retstart: int, retmax: int) -> bytes:
        self.pages.append((query, retstart, retmax))
        if retstart == self.crash_page_offset:
            raise PubMedProbeError('Simulated fault')
        identifiers = self.ids(query)
        if self.inject_page_overlap and '2025/01/02' in query and identifiers:
            identifiers[0] = '1'
        response = {
            'esearchresult': {
                'count': str(self.count(query)), 'retstart': str(retstart),
                'retmax': str(retmax), 'idlist': identifiers[retstart:retstart + retmax],
                'querytranslation': query,
                'warninglist': {'outputmessages': []}, 'errorlist': {'phrasesnotfound': []},
            }
        }
        return json.dumps(response).encode('utf-8')


def corpus(first=5001, second=5002):
    return {
        date(2025, 1, 1): [str(i) for i in range(1, first + 1)],
        date(2025, 1, 2): [str(i) for i in range(first + 1, first + second + 1)],
    }


def run(fake, **kw):
    return retrieve_date_partitioned_identifiers(fake, Q, date_window=WINDOW, **kw)


def test_date_windows_split_at_inclusive_midpoint_without_overlap_or_gap():
    interval = DateWindow(date(2024, 2, 28), date(2024, 3, 2))
    left, right = interval.split()
    assert left == DateWindow(date(2024, 2, 28), date(2024, 2, 29))
    assert right == DateWindow(date(2024, 3, 1), date(2024, 3, 2))
    assert (right.start - left.end).days == 1
    assert DATE_FIELD == 'crdt'
    assert left.query_for(Q).endswith('2024/02/28:2024/02/29[crdt])')
    assert ' AND ' in left.query_for(Q)  # provider date partition only, not concept AND


def test_recursive_two_day_search_over_10000_reconciles_unique_ids():
    fake = FakeClient(corpus())
    result = run(fake, page_size=900)
    assert result.status == 'identifiers_reconciled_metadata_pending'
    assert result.identifiers_reconciled is True
    assert result.source_retrieval_verified is False
    assert result.reported_root_matches == 10003
    assert len(result.pmids) == len(set(result.pmids)) == 10003
    assert [v.decision for v in result.counted_partitions] == ['split', 'collect', 'collect']
    assert [v.parent_index for v in result.counted_partitions] == [None, 0, 0]
    assert [v.reported_matches for v in result.counted_partitions] == [10003, 5001, 5002]
    assert len(result.collected_leaves) == 2
    assert fake.pages and max(size for _, _, size in fake.pages) <= 900
    assert all(v.source_retrieval_verified is False for v in result.collected_leaves)
    assert all(p.exact_subquery.startswith('(' + Q + ') AND') for p in result.counted_partitions)


def test_zero_count_root_is_genuine_zero_not_missing():
    result = run(FakeClient({}), page_size=250)
    assert result.identifiers_reconciled
    assert result.reported_root_matches == 0
    assert result.pmids == () and result.counted_partitions == ()
    assert not result.source_retrieval_verified


def test_bounded_search_uses_exact_original_query_without_date_restriction():
    fake = FakeClient(corpus(3, 4))
    result = run(fake, page_size=2)
    assert result.identifiers_reconciled
    assert result.pmids == tuple(map(str, range(1, 8)))
    assert len(result.collected_leaves) == 1
    assert result.counted_partitions == ()
    assert all(query == Q for query, _, _ in fake.pages)


def test_missing_create_dates_cannot_silently_mark_complete():
    fake = FakeClient(corpus(5001, 5002), root_override=10004)
    out = run(fake)
    assert out.status == 'incomplete'
    assert out.pmids == () and out.reported_root_matches == 10004
    assert any('does not account' in e for e in out.errors)
    assert not fake.pages


def test_single_create_date_over_limit_is_never_truncated():
    fake = FakeClient({date(2025, 1, 1): list(map(str, range(1, 9003)))})
    out = run(fake)
    assert out.status == 'incomplete'
    assert any('Single Create Date' in e for e in out.errors)
    assert out.counted_partitions[-1].decision == 'unsplittable'
    assert not fake.pages


def test_count_probe_budget_explicitly_limits_recursive_requests():
    fake = FakeClient(corpus())
    out = run(fake, max_count_probes=1)
    assert out.status == 'incomplete'
    assert len(out.counted_partitions) == 1
    assert any('budget' in e for e in out.errors)
    assert not fake.pages


def test_reject_base_translation_warning_without_date_queries():
    fake = FakeClient(corpus())
    fake.bad_translation_for = 'right ventricle'
    out = run(fake)
    assert out.status == 'query_review_required'
    assert out.pmids == ()
    assert len(fake.probes) == 1


def test_reject_date_partition_translation_which_is_not_accepted():
    fake = FakeClient(corpus())
    fake.bad_translation_for = '[crdt]'
    out = run(fake)
    assert out.status == 'query_review_required'
    assert out.pmids == ()
    assert not fake.pages


def test_child_count_mismatch_never_fetches_records():
    fake = FakeClient(corpus())
    original_probe = fake.probe
    def probe(query, *, allow_crdt_partition=False):
        report = original_probe(query, allow_crdt_partition=allow_crdt_partition)
        if '2025/01/02:2025/01/02' in query:
            return PubMedCountProbe(
                query, query, report.reported_matches + 1,
                report.checked_at_utc, (), (), True,
            )
        return report
    fake.probe = probe
    result = run(fake)
    assert result.status == 'incomplete'
    assert any('child counts' in error for error in result.errors)
    assert result.pmids == ()
    assert not fake.pages


def test_mid_leaf_count_change_preserves_completed_partitions_but_not_claim_complete():
    fake = FakeClient(corpus())
    leaf_query = WINDOW.split()[1].query_for(Q)
    fake.changing_counts_for = leaf_query
    result = run(fake)
    assert result.status == 'incomplete'
    assert len(result.collected_leaves) == 2
    assert len(result.pmids) == 5001
    assert not result.source_retrieval_verified


def test_cross_date_duplicate_id_is_incomplete_even_if_counts_match():
    fake = FakeClient(corpus())
    fake.inject_page_overlap = True
    result = run(fake)
    assert result.status == 'incomplete'
    assert any('overlapped' in e for e in result.errors)
    assert len(result.pmids) == 5001


def test_failure_after_one_leaf_keeps_partial_records_without_completeness():
    fake = FakeClient(corpus())
    # Both leaf queries have offsets. Raise when second leaf reaches 200 PMIDs.
    original = fake.fetch_esearch_page
    def fetch(query, *, retstart, retmax):
        if '2025/01/02' in query and retstart == 200:
            raise PubMedProbeError('Simulated failure')
        return original(query, retstart=retstart, retmax=retmax)
    fake.fetch_esearch_page = fetch
    result = run(fake)
    assert result.status == 'incomplete'
    assert len(result.pmids) == 5001
    assert len(result.collected_leaves) == 2
    assert result.source_retrieval_verified is False


def test_degenerate_one_day_below_limit_reconciles_via_date_if_root_above_custom_cap():
    fake = FakeClient({date(2025, 1, 1): list(map(str, range(1, 102)))})
    result = run(fake, max_records=100)
    assert result.status == 'incomplete'
    assert result.counted_partitions[-1].decision == 'unsplittable'


def test_zero_subranges_preserve_log_and_id_reconciliation():
    rows = {date(2025, 1, 1): list(map(str, range(1, 4502))),
            date(2025, 1, 5): list(map(str, range(4502, 9004)))}
    fake = FakeClient(rows)
    out = retrieve_date_partitioned_identifiers(
        fake, Q, date_window=DateWindow(date(2025, 1, 1), date(2025, 1, 20)),
    )
    assert out.identifiers_reconciled
    assert any(record.decision == 'empty' for record in out.counted_partitions)
    assert len(out.pmids) == 9003


@pytest.mark.parametrize('kwargs', [
    {'max_records': 0}, {'max_records': 9001}, {'max_records': True},
    {'page_size': 0}, {'page_size': 1001}, {'page_size': False},
    {'max_count_probes': 0}, {'max_count_probes': False},
])
def test_invalid_limits_rejected_before_network(kwargs):
    fake = FakeClient(corpus())
    with pytest.raises(ValueError):
        run(fake, **kwargs)
    assert fake.probes == []


def test_bad_absolute_date_window_rejected():
    with pytest.raises(ValueError):
        DateWindow(date(2025, 1, 2), date(2025, 1, 1))
    with pytest.raises(TypeError):
        DateWindow(datetime(2025, 1, 1), date(2025, 1, 2))
    with pytest.raises(ValueError):
        DateWindow(date(2025, 1, 1), date(2025, 1, 1)).split()


def test_invalid_query_without_contact_not_submitted():
    fake = FakeClient(corpus())
    with pytest.raises(ValueError):
        retrieve_date_partitioned_identifiers(fake, '', date_window=WINDOW)
    assert fake.probes == []


def test_exception_message_from_external_count_client_is_not_returned():
    fake = FakeClient(corpus())
    original = fake.probe
    def bad(query, *, allow_crdt_partition=False):
        if '[crdt]' in query:
            raise RuntimeError('PRIVATE-API-KEY-AND-LOCAL-FILE')
        return original(query, allow_crdt_partition=allow_crdt_partition)
    fake.probe = bad
    out = run(fake)
    assert out.status == 'incomplete'
    assert 'PRIVATE-API-KEY' not in repr(out)


def test_model_fields_preserve_index_parent_dates_and_provenance():
    fake = FakeClient(corpus())
    out = run(fake)
    assert all(isinstance(node, CountedPartition) for node in out.counted_partitions)
    assert out.counted_partitions[0].parent_index is None
    assert out.counted_partitions[1].parent_index == 0
    assert out.counted_partitions[2].parent_index == 0
    assert all(node.rationale for node in out.counted_partitions)
    assert isinstance(out, PubMedPartitionResult)


def test_baseline_count_change_after_pages_invalidates_final_reconciliation():
    fake = FakeClient(corpus())
    fake.changing_counts_for = Q
    result = run(fake)
    assert result.status == 'incomplete'
    assert len(result.pmids) == 10003
    assert result.source_retrieval_verified is False
    assert any('baseline count changed' in err for err in result.errors)


def test_provenance_queries_use_four_digit_year_even_before_year_1000():
    interval = DateWindow(date(1, 1, 1), date(1, 1, 2))
    assert interval.query_for(Q).endswith('0001/01/01:0001/01/02[crdt])')


def test_unapproved_control_character_query_rejected_before_source_calls():
    fake = FakeClient(corpus())
    with pytest.raises(ValueError, match='control characters'):
        retrieve_date_partitioned_identifiers(fake, Q + "\n", date_window=WINDOW)
    assert not fake.probes


def test_caller_supplied_date_filter_is_not_treated_as_internal_partition():
    from research_y.pubmed_probe import _review_translation
    root_query = WINDOW.query_for(Q)
    assert any('AND/NOT' in r for r in _review_translation(root_query, root_query, ()))
    assert not _review_translation(root_query, root_query, (), allow_crdt_partition=True)
    fake = FakeClient(corpus(3, 4))
    out = retrieve_date_partitioned_identifiers(fake, root_query, date_window=WINDOW)
    assert out.status == 'query_review_required'
    assert not fake.pages


@pytest.mark.parametrize('at_final', [False, True])
def test_private_error_in_external_baseline_count_requests_is_sanitised(at_final):
    fake = FakeClient(corpus())
    original = fake.probe
    def fails(query, *, allow_crdt_partition=False):
        if query == Q and (not at_final or fake.probe_calls[Q] >= 1):
            raise RuntimeError('PRIVATE-TOKEN-IN-ERROR-MESSAGE')
        return original(query, allow_crdt_partition=allow_crdt_partition)
    fake.probe = fails
    out = run(fake)
    assert out.status == 'incomplete'
    assert 'PRIVATE-TOKEN' not in repr(out)
    if at_final:
        assert len(out.pmids) == 10003
    else:
        assert not out.pmids


@pytest.mark.parametrize('large', [False, True])
def test_unexpected_count_failure_inside_delegated_retrieval_is_sanitised(large):
    fake = FakeClient(corpus() if large else corpus(3, 4))
    original = fake.probe
    query_to_fail = WINDOW.split()[1].query_for(Q) if large else Q
    def crashes(query, *, allow_crdt_partition=False):
        if query == query_to_fail and fake.probe_calls[query] >= 1:
            raise RuntimeError('PRIVATE-CREDENTIAL-IN-EXCEPTION')
        return original(query, allow_crdt_partition=allow_crdt_partition)
    fake.probe = crashes
    out = run(fake)
    assert out.status == 'incomplete'
    assert not out.source_retrieval_verified
    assert 'PRIVATE-CREDENTIAL' not in repr(out)
    assert len(out.pmids) == (5001 if large else 0)
