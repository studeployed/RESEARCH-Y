"""P1-04i: real-response-shaped offline count/page/SQLite recovery regressions.

No provider calls or real-source completeness claims. Source evidence is from
manual diagnostic 41216318046; other counts and identifiers are synthetic.
"""
from contextlib import closing
from dataclasses import replace
from datetime import date
from hashlib import sha256
import json
import re
import sqlite3
from urllib.parse import parse_qs

import pytest

from research_y.projects import create_project, open_project
from research_y.storage import (
    ApprovedTerm, StrategyGroup, approve_strategy, create_search_run, plan_source_query,
)
from research_y.pubmed_probe import (
    PubMedESearchProbeClient, _review_translation, _translation_matches_submitted,
    parse_esearch_count,
)
from research_y.pubmed_ids import parse_identifier_page
from research_y.pubmed_partition import DateWindow
from research_y.pubmed_checkpoint_resume import (
    start_checkpointed_pubmed_retrieval, resume_pubmed_checkpoint, _safe_probe,
)
from research_y.pubmed_checkpoint_store import (
    CheckpointIntegrityError, inspect_pubmed_checkpoint, pause_pubmed_checkpoint,
    commit_pubmed_checkpoint_page,
)

QUERY = '("ECMO"[All Fields])'
UTC = '2026-10-31T15:45:08+00:00'
WINDOW = DateWindow(date(2025, 1, 1), date(2025, 1, 2))
OBSERVED_SUBMITTED = '(("ECMO"[All Fields])) AND (1900/01/01:2026/11/01[crdt])'
OBSERVED_ACCEPTED = '"ECMO"[All Fields] AND 1900/01/01:2026/11/01[Date - Create]'


def response(query, *, count=19483, ids=(), offset=0, warnings=()):
    return json.dumps({'esearchresult': {
        'count': str(count), 'retstart': str(offset), 'retmax': str(len(ids)),
        'idlist': list(ids), 'querytranslation': query,
        'warninglist': {'outputmessages': list(warnings)},
        'errorlist': {'phrasesnotfound': []},
    }}).encode()


def canonical(query):
    if query == QUERY:
        return '"ECMO"[All Fields]'
    interval = re.search(r'([0-9/]+:[0-9/]+)\[crdt\]', query)
    assert interval is not None
    return f'"ECMO"[All Fields] AND {interval.group(1)}[Date - Create]'


def test_actual_count_translation_requires_explicit_internal_context():
    payload = response(OBSERVED_ACCEPTED)
    internal = parse_esearch_count(payload, OBSERVED_SUBMITTED,
                                  checked_at_utc=UTC, allow_crdt_partition=True)
    assert not internal.review_required
    assert internal.translation_matches_submitted
    assert internal.accepted_translation == OBSERVED_ACCEPTED
    assert internal.exact_query == OBSERVED_SUBMITTED
    assert internal.reported_matches == 19483
    assert not internal.retrieval_verified and internal.retrieved_records == 0
    root = parse_esearch_count(payload, OBSERVED_SUBMITTED, checked_at_utc=UTC)
    assert root.review_required and not root.translation_matches_submitted
    assert not _translation_matches_submitted(OBSERVED_SUBMITTED, OBSERVED_ACCEPTED)
    assert any('AND/NOT' in reason for reason in root.review_reasons)
    assert _review_translation(OBSERVED_SUBMITTED, OBSERVED_SUBMITTED, ())


def test_warning_is_not_erased_by_proven_date_equivalence():
    payload = response(OBSERVED_ACCEPTED, warnings=('Source warning',))
    probe = parse_esearch_count(payload, OBSERVED_SUBMITTED,
                               checked_at_utc=UTC, allow_crdt_partition=True)
    assert probe.translation_matches_submitted and probe.review_required
    assert probe.warnings == ('outputmessages: Source warning',)
    page = parse_identifier_page(
        response(OBSERVED_ACCEPTED, count=1, ids=('123',), warnings=('Source warning',)),
        exact_query=OBSERVED_SUBMITTED, retstart=0, retmax=1,
        retrieved_at_utc=UTC, allow_crdt_partition=True,
    )
    assert page.review_required


def test_page_keeps_raw_source_translation_and_shared_internal_rule():
    payload = response(OBSERVED_ACCEPTED, count=3, ids=('1', '2'))
    page = parse_identifier_page(payload, exact_query=OBSERVED_SUBMITTED,
                                retstart=0, retmax=2, retrieved_at_utc=UTC,
                                allow_crdt_partition=True)
    assert not page.review_required
    assert page.accepted_translation == OBSERVED_ACCEPTED
    assert page.exact_query == OBSERVED_SUBMITTED
    assert page.response_sha256 == sha256(payload).hexdigest()
    assert page.pmids == ('1', '2')


class PartitionSource:
    """Two synthetic source-date leaves exceeding 10k in total; real client/parser."""
    def __init__(self, *, legacy=False):
        self.ids = tuple(str(i) for i in range(1, 10006))
        self.left, self.right = WINDOW.split()
        self.data = {
            QUERY: self.ids,
            WINDOW.query_for(QUERY): self.ids,
            self.left.query_for(QUERY): self.ids[:5002],
            self.right.query_for(QUERY): self.ids[5002:],
        }
        self.legacy = legacy
        self.project = None
        self.query_id = None
        self.pause_first = False
        self.page_calls = []
        self.count_calls = []
        self.forbidden = None
        self.bad_translation = None
        self.count_drift = False

    def transport(self, request, timeout):
        fields = parse_qs(request.data.decode())
        query = fields['term'][0]
        assert query in self.data  # Original submitted queries never rewritten.
        size = int(fields['retmax'][0])
        start = int(fields.get('retstart', ['0'])[0])
        count = len(self.data[query])
        translation = query if self.legacy else canonical(query)
        if query != QUERY and self.bad_translation is not None:
            translation = self.bad_translation(translation)
        if query == QUERY and self.count_drift:
            count += 1
        if size:
            assert (query, start) != self.forbidden, 'Previously committed page fetched'
            self.page_calls.append((query, start))
            if self.pause_first and len(self.page_calls) == 1:
                pause_pubmed_checkpoint(self.project, self.query_id)
        else:
            self.count_calls.append(query)
        return response(translation, count=count, offset=start,
                        ids=self.data[query][start:start+size] if size else ())

    def client(self):
        # No sleeping and no network in controlled fixtures.
        return PubMedESearchProbeClient(
            email='synthetic@example.org', transport=self.transport,
            clock=lambda: 0.0, sleep=lambda seconds: None,
        )


def started(tmp_path, *, legacy=False):
    project = create_project(tmp_path, 'Date translation regression')
    version = approve_strategy(project, theme='ECMO', approved_by='Fixture researcher',
        approval_confirmed=True,
        groups=(StrategyGroup('g1', 'ECMO', (ApprovedTerm('ECMO', 'researcher', True),)),))
    run = create_search_run(project, version.strategy_version_id)
    pending = plan_source_query(project, run_id=run.run_id, group_id='g1',
                                source_name='pubmed', exact_query=QUERY)
    source = PartitionSource(legacy=legacy)
    source.project, source.query_id, source.pause_first = project, pending.query_id, True
    result = start_checkpointed_pubmed_retrieval(
        project, pending.query_id, source.client(), date_window=WINDOW, page_size=1000)
    assert result.status == 'paused'
    assert result.snapshot.pages_committed == 1
    assert len(result.snapshot.pmids) == 1000
    assert not result.source_retrieval_verified
    return project, pending.query_id, source


def read_pages(project, query_id):
    with closing(sqlite3.connect(project.database_path)) as db:
        return db.execute(
            'SELECT page_json,page_sha256 FROM pubmed_checkpoint_pages '
            'WHERE query_id=? ORDER BY partition_index,retstart', (query_id,)).fetchall()


@pytest.mark.parametrize('legacy', [False, True])
def test_10005_partitioned_ids_pause_reopen_resume_with_raw_translations(tmp_path, legacy):
    project, query_id, source = started(tmp_path, legacy=legacy)
    first = read_pages(project, query_id)[0]
    prior_page = source.page_calls[0]
    source.forbidden = prior_page
    source.legacy = False  # Supports checkpoints made before canonical alias handling.
    source.pause_first = False
    result = resume_pubmed_checkpoint(open_project(project.root), query_id, source.client())
    assert result.status == 'identifiers_reconciled_metadata_pending'
    assert result.snapshot.identifiers_reconciled
    assert result.snapshot.pages_committed == result.snapshot.pages_expected == 12
    assert result.snapshot.pmids == source.ids
    assert len(set(result.snapshot.pmids)) == 10005
    assert source.page_calls.count(prior_page) == 1
    assert read_pages(project, query_id)[0] == first
    assert not result.source_retrieval_verified
    assert inspect_pubmed_checkpoint(open_project(project.root), query_id).identifiers_reconciled
    for encoded, digest in read_pages(project, query_id)[1:]:
        page = json.loads(encoded)
        assert '[Date - Create]' in page['accepted_translation']
        assert '[crdt]' in page['exact_query']
        assert sha256(encoded.encode()).hexdigest() == digest
    with closing(sqlite3.connect(project.database_path)) as db:
        assert db.execute('SELECT status FROM source_queries WHERE query_id=?',
                          (query_id,)).fetchone()[0] == 'incomplete'


@pytest.mark.parametrize('mutation', [
    lambda text: text.replace('[Date - Create]', '[Date - Publication]'),
    lambda text: text.replace('2025/01/01', '2024/12/31'),
    lambda text: text.replace('"ECMO"', '"shock"'),
    lambda text: text + ' AND "humans"[All Fields]',
])
def test_resume_changed_source_interpretation_keeps_page_and_fetches_no_more(tmp_path, mutation):
    project, query_id, source = started(tmp_path)
    before = read_pages(project, query_id)
    source.bad_translation = mutation
    result = resume_pubmed_checkpoint(open_project(project.root), query_id, source.client())
    assert result.status == 'incomplete'
    assert result.snapshot.pages_committed == 1
    assert len(source.page_calls) == 1
    assert read_pages(project, query_id) == before
    assert not result.source_retrieval_verified


def test_count_drift_still_prevents_resume_after_valid_alias(tmp_path):
    project, query_id, source = started(tmp_path)
    source.count_drift = True
    result = resume_pubmed_checkpoint(project, query_id, source.client())
    assert result.status == 'incomplete' and len(source.page_calls) == 1
    assert result.snapshot.pages_committed == 1


def test_checkpoint_commit_derives_context_and_refuses_forged_clean_review_flags(tmp_path):
    project, query_id, source = started(tmp_path)
    query = source.left.query_for(QUERY)
    page = parse_identifier_page(
        response(canonical(query), count=5002, ids=source.ids[1000:2000], offset=1000),
        exact_query=query, retstart=1000, retmax=1000,
        retrieved_at_utc=UTC, allow_crdt_partition=True)
    forged = replace(page, accepted_translation=canonical(query).replace('2025/01/01', '2025/01/02'),
                     review_reasons=(), warnings=())
    with pytest.raises(CheckpointIntegrityError, match='source-accepted'):
        commit_pubmed_checkpoint_page(project, query_id, forged)
    assert inspect_pubmed_checkpoint(project, query_id).pages_committed == 1


def test_reopen_revalidates_semantics_even_with_recomputed_page_checksum(tmp_path):
    project, query_id, source = started(tmp_path)
    encoded, _ = read_pages(project, query_id)[0]
    data = json.loads(encoded)
    data['accepted_translation'] = data['accepted_translation'].replace('[Date - Create]', '[edat]')
    changed = json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    with closing(sqlite3.connect(project.database_path)) as db, db:
        names = db.execute("SELECT name FROM sqlite_master WHERE type='trigger' "
                           "AND tbl_name='pubmed_checkpoint_pages'").fetchall()
        for (name,) in names:
            db.execute('DROP TRIGGER "' + name.replace('"', '""') + '"')
        db.execute('UPDATE pubmed_checkpoint_pages SET page_json=?,page_sha256=? WHERE query_id=?',
                   (changed, sha256(changed.encode()).hexdigest(), query_id))
    with pytest.raises(CheckpointIntegrityError, match='immutable partition/count'):
        inspect_pubmed_checkpoint(project, query_id)
