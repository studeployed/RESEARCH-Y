"""Phase 1 acceptance boundary for distinct retained conference abstract records."""
from contextlib import closing
import json
import sqlite3

from research_y.projects import open_project
from research_y.publication_candidates import read_candidate, decide_candidate
from research_y.publication_identity import materialise_retrieval
from research_y.pubmed_metadata import parse_efetch_xml
from research_y.pubmed_metadata_store import commit_pubmed_metadata_batch
from research_y.run_execution_board import read_run_execution_board
from test_pubmed_metadata import article_xml
from test_run_execution_board import _project, _pubmed, _wos, Clock, UTC


def test_same_supplement_doi_retains_two_distinct_reviewed_abstracts(tmp_path):
    project, run_id, queries = _project(tmp_path)
    pmids = ('111', '222')
    records = []
    for number, pmid in enumerate(pmids, 1):
        citation = article_xml(pmid, title='Supplement abstracts', doi='10.1234/shared-container')
        citation = citation.replace('Randomized Controlled Trial', 'Conference Abstract')
        citation = citation.replace('We observed <i>some</i> findings.', f'Original abstract number {number}.')
        records.append(citation)
    payload = ('<PubmedArticleSet>' + ''.join(records) + '</PubmedArticleSet>').encode()
    batch = parse_efetch_xml(payload, pmids, retrieved_at_utc=UTC)
    clock = Clock()
    for group in ('g-ecmo', 'g-rv'):
        pubmed, exact = queries[group, 'pubmed']
        _pubmed(project, pubmed, exact, pmids=pmids)
        commit_pubmed_metadata_batch(project, pubmed, batch)
        starter, exact = queries[group, 'wos']
        clock.sleep(60)
        _wos(project, starter, exact, clock=clock, count=0)
    with closing(sqlite3.connect(project.database_path)) as db:
        ids = [row[0] for row in db.execute('SELECT retrieval_id FROM source_retrievals ORDER BY source_record_id')]
        assert db.execute('SELECT COUNT(*) FROM query_retrievals').fetchone() == (4,)
    assert len(ids) == 2
    for rid in ids:
        materialise_retrieval(project, rid, actor='Fixture')
    pair = read_candidate(project, *ids)
    assert pair.comparison['comparisons']['doi'] == 'equal'
    assert 'abstract_or_container_scope_requires_review' in pair.warnings
    assert pair.status == 'review_required' and len(set(pair.publication_ids)) == 2
    assert read_run_execution_board(project, run_id)['reconciled_primary_run_unique_publications'] is None
    decide_candidate(project, *ids, expected_revision=pair.revision, decision='rejected_match',
                     actor='Fixture reviewer', evidence='Separate retained numbered abstracts',
                     acknowledged_warnings=pair.warnings, decision_confirmed=True)
    reopened = open_project(project.root)
    with closing(sqlite3.connect(reopened.database_path)) as db:
        originals = db.execute(
            'SELECT source_record_id, original_metadata_json FROM source_retrievals ORDER BY source_record_id'
        )
        retained = {pmid: json.loads(raw)['record'] for pmid, raw in originals}
        for number, pmid in enumerate(pmids, 1):
            assert retained[pmid]['publication_types'] == ['Conference Abstract']
            assert retained[pmid]['abstract_sections'][1]['text'] == f'Original abstract number {number}.'
        assert db.execute('SELECT COUNT(*) FROM query_retrievals').fetchone() == (4,)
    board = read_run_execution_board(reopened, run_id)
    assert board['reconciled_primary_run_unique_publications'] == 2
    assert board['reviewed_retained_master']['group_count_sum'] == 4
    assert not board['whole_search_verified']
