from contextlib import closing
import json
import sqlite3
from uuid import uuid4

from openpyxl import load_workbook
import pytest

from research_y.desktop.flow import RealProjectFlow
from research_y.projects import open_project
from research_y.publication_candidates import decide_candidate, read_candidate
from research_y.publication_identity import materialise_retrieval
from research_y.publication_results import read_publication_page
from research_y.run_execution_board import read_run_execution_board
from research_y.strategy_report import StrategyReport, ReportIntegrityError, canonical, capture_strategy_report
from research_y.workbook_exports import prepare_workbook_export, WorkbookExportError
from test_run_execution_board import _project, _pubmed, _efetch, _wos, Clock


def populated(tmp_path):
    project, run_id, queries = _project(tmp_path)
    clock = Clock()
    for group in ('g-ecmo', 'g-rv'):
        qid, exact = queries[group, 'pubmed']
        _pubmed(project, qid, exact, pmids=('111', '222'))
        _efetch(project, qid, pmids=('111', '222'), book_pmid='222')
        qid, exact = queries[group, 'wos']
        clock.sleep(60)
        _wos(project, qid, exact, clock=clock, title='PRIVATE TITLE')
    with closing(sqlite3.connect(project.database_path)) as db:
        ids = dict(db.execute('SELECT source_record_id,retrieval_id FROM source_retrievals'))
    for rid in ids.values():
        materialise_retrieval(project, rid, actor='Fixture')
    return project, run_id, queries, ids


def decide(project, left, right, decision):
    pair = read_candidate(project, left, right)
    return decide_candidate(project, left, right, expected_revision=pair.revision, decision=decision,
                            actor='Fixture reviewer', evidence='Explicit fixture citation comparison',
                            acknowledged_warnings=pair.warnings, decision_confirmed=True,
                            move_retrieval_id=right if decision == 'confirmed_match' else None)


def test_native_host_issues_two_reviewed_rows_and_six_memberships(tmp_path):
    project, run_id, _, ids = populated(tmp_path)
    decision = decide(project, ids['111'], ids['WOS:000000001'], 'confirmed_match')
    assert decision.status == 'confirmed_match'
    assert read_run_execution_board(project, run_id)['reviewed_retained_master'] is None
    decide(project, ids['111'], ids['222'], 'rejected_match')
    assert read_publication_page(project, run_id)['reviewed_retained_unique_publications'] == 2
    assert capture_strategy_report(project, run_id).as_dict()['format_version'] == 1
    with closing(RealProjectFlow()) as flow:
        flow.open_native_folder(project.root)
        flow.select_run(run_id)
        board = flow.inspect_run_execution_board()['run_execution_board']
        assert board['reconciled_primary_run_unique_publications'] == 2
        assert not board['verified_complete']
        master = board['reviewed_retained_master']
        assert master['source_count'] == 3 and master['group_count_sum'] == 4
        assert master['group_counts'] == {'g-ecmo': 2, 'g-rv': 2}
        summary_id = flow.prepare()['selected_export_id']
        ready = flow.prepare(reviewed_master=True)
        export_id = ready['selected_export_id']
        assert export_id != summary_id and ready['retained_export_report']['format_version'] == 2
        flow.resume()
        assert flow.observe()['observation']['audited_success']
    filename = f'reviewed-master-{run_id}.xlsx'
    with closing(load_workbook(project.root / 'exports' / filename)) as workbook:
        rows = list(workbook['Reviewed Master Results'].values)[4:]
        members = list(workbook['Reviewed Memberships'].values)[4:]
        assert sorted(row[1] for row in rows) == [1, 2]
        assert len(members) == 6 and {row[1] for row in members} == set(ids.values())
        assert {row[0] for row in members} == {row[0] for row in rows}
        assert workbook['Reviewed Master Results'].auto_filter.ref == 'A4:B6'
        for index, row in enumerate(rows, 5):
            target = workbook['Reviewed Master Results'][f'A{index}'].hyperlink.location
            assert target.startswith("'Reviewed Memberships'!")
            assert workbook['Reviewed Memberships'][target.split('!')[1]].value == row[0]
        assert workbook['Reviewed Memberships']['A3'].hyperlink.location == "'Methods'!A1"
        assert [r[2] for r in list(workbook['Reviewed Counts'].values)[4:]] == [2, 2, 2, 4]
        assert {r[3] for r in list(workbook['Review Receipts'].values)[4:]} == {'confirmed_match', 'rejected_match'}
        fragments = list(workbook['Report Snapshot'].values)[4:]
        payload = json.loads(''.join(r[3] for r in fragments))
        assert payload['format_version'] == 2 and 'PRIVATE TITLE' not in canonical(payload)
        payload['reviewed_master']['memberships'].pop()
        with pytest.raises(ReportIntegrityError):
            StrategyReport(canonical(payload))
    with pytest.raises(WorkbookExportError):
        prepare_workbook_export(project, run_id, filename, export_id=export_id)
    again = prepare_workbook_export(project, run_id, filename, export_id=export_id,
                                    reviewed_revision=board['source_count_revision'])
    assert again.export_id == export_id


def test_missing_source_coverage_or_changed_revision_never_yields_run_total(tmp_path):
    project, run_id, queries, ids = populated(tmp_path)
    decide(project, ids['111'], ids['WOS:000000001'], 'confirmed_match')
    decide(project, ids['111'], ids['222'], 'rejected_match')
    old = read_run_execution_board(project, run_id)
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute("UPDATE source_queries SET status='failed' WHERE query_id=?", (queries['g-ecmo', 'pubmed'][0],))
    reopened = open_project(project.root)
    board = read_run_execution_board(reopened, run_id)
    assert board['reconciled_primary_run_unique_publications'] is None and not board['whole_search_verified']
    with pytest.raises(WorkbookExportError):
        prepare_workbook_export(reopened, run_id, 'stale.xlsx', export_id=str(uuid4()),
                                reviewed_revision=old['source_count_revision'])
    assert not (project.root / 'exports' / 'stale.xlsx').exists()


def test_reversing_current_match_withdraws_the_reviewed_count(tmp_path):
    from research_y.publication_review_gui import preview_candidate_reversal, confirm_candidate_reversal
    project, run_id, _, ids = populated(tmp_path)
    moved = ids['WOS:000000001']
    decide(project, ids['111'], moved, 'confirmed_match')
    decide(project, ids['111'], ids['222'], 'rejected_match')
    initial = read_run_execution_board(project, run_id)
    assert initial['reconciled_primary_run_unique_publications'] == 2
    revision = initial['source_count_revision']
    offer = preview_candidate_reversal(project, run_id, moved, run_revision=revision)
    confirm_candidate_reversal(project, run_id, moved, run_revision=revision,
                               expected_revision=offer['revision'], actor='Fixture reviewer',
                               evidence='Reconsider the original citation', confirmed=True)
    current = read_run_execution_board(open_project(project.root), run_id)
    assert current['reviewed_retained_master'] is None
    assert current['reconciled_primary_run_unique_publications'] is None


def test_unstarted_is_unknown_and_all_reconciled_empty_is_zero(tmp_path):
    project, run_id, queries = _project(tmp_path)
    assert read_run_execution_board(project, run_id)['reconciled_primary_run_unique_publications'] is None
    clock = Clock()
    for (_, source), (qid, exact) in queries.items():
        if source == 'pubmed':
            _pubmed(project, qid, exact, pmids=())
        else:
            clock.sleep(60)
            _wos(project, qid, exact, clock=clock, count=0)
    board = read_run_execution_board(open_project(project.root), run_id)
    assert board['reconciled_primary_run_unique_publications'] == 0
    assert not board['verified_complete']


def test_multiple_rejections_between_same_publications_do_not_cover_missing_pair(tmp_path):
    from research_y.projects import create_project
    from research_y import result_counts
    from research_y.reviewed_master import retained_union
    from test_result_counts import new_run, add_record

    f = new_run(create_project(tmp_path, 'Distinctness evidence'))
    a, b, c, d, e = [add_record(f, identifier=str(i)) for i in range(111, 116)]
    for rid in (a, b, c, d, e):
        materialise_retrieval(f.project, rid, actor='Fixture')
    decide(f.project, a, b, 'confirmed_match')
    decide(f.project, c, d, 'confirmed_match')
    for left, right in ((a, c), (b, d), (a, e)):
        decide(f.project, left, right, 'rejected_match')
    def observed():
        with result_counts._read_connection(f.project) as db:
            counts = result_counts._snapshot(db, f.project, f.run)
            assert counts.totals['global_publication_identities'] == 3
            return retained_union(db, counts)
    assert observed() is None
    decide(f.project, c, e, 'rejected_match')
    assert observed()['retained_unique_publications'] == 3
