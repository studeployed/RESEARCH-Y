from contextlib import closing
import sqlite3

import pytest

from research_y.desktop.flow import RealProjectFlow, ProjectFlowError
from research_y.desktop.planning_draft import restore
from research_y.projects import create_project, read_research_setup
from research_y.storage import get_strategy_snapshot
from research_y import master_results, study_classification
from test_reviewed_master import populated


def seed(flow):
    flow.edit_setup('heading', dict(theme='RV failure', objectives='Diagnosis and management', approved_by='Researcher'))
    flow.edit_setup('add_group', dict(label='Right ventricular failure'))
    gid = flow.state()['strategy_draft']['groups'][0]['group_id']
    for text in ('right ventricular failure', 'right heart failure', 'right-sided heart failure'):
        flow.edit_setup('add_term', dict(group_id=gid, text=text))
    return gid


def test_unfinished_draft_reopens_and_saved_search_stays_visible(tmp_path):
    project = create_project(tmp_path, 'Test')
    with closing(RealProjectFlow()) as flow:
        flow.open_native_folder(project.root)
        seed(flow)
        flow.edit_setup('scope', dict(sources=['pubmed'], publication_year=2025))
        before = flow.state()['strategy_draft']
        flow.preview_setup()
    with closing(RealProjectFlow()) as flow:
        flow.open_native_folder(project.root)
        assert flow.state()['strategy_draft'] == before  # Preview is intentionally rebuilt.
        assert not flow.state()['runs']
        flow.preview_setup()
        admission = flow.approve_setup()['last_strategy_admission']
        frozen = get_strategy_snapshot(project, admission['strategy_version_id'])
        from research_y.desktop.search_guidance import saved_search_names
        saved_names = saved_search_names(flow.state()['runs'])
        assert next(iter(saved_names.values())).startswith('RV failure · version 1 · saved ')
        assert flow.state()['planning_mode'] == 'saved'
        assert len(flow.state()['strategy_draft']['groups'][0]['terms']) == 3
        flow.open_native_folder(project.root)
        assert flow.state()['planning_mode'] == 'saved'
        with pytest.raises(ProjectFlowError, match='Edit a copy'):
            flow.edit_setup('add_group', dict(label='Accidental edit'))
        flow.begin_plan()
        gid = flow.state()['strategy_draft']['groups'][0]['group_id']
        flow.edit_setup('add_term', dict(group_id=gid, text='RV failure'))
        assert get_strategy_snapshot(project, admission['strategy_version_id']) == frozen
        assert flow.state()['planning_base_version'] == 1
        flow.open_native_folder(project.root)
        assert len(flow.state()['strategy_draft']['groups'][0]['terms']) == 4
        assert len(flow.state()['runs']) == 1
        flow.edit_setup('heading', dict(theme='Changed question', objectives='New purpose', approved_by='Researcher'))
        assert saved_search_names(flow.state()['runs']) == saved_names


def test_two_windows_cannot_overwrite_a_draft_or_half_save_a_question(tmp_path):
    project = create_project(tmp_path, 'Test')
    with closing(RealProjectFlow()) as first, closing(RealProjectFlow()) as second:
        first.open_native_folder(project.root)
        seed(first)
        second.open_native_folder(project.root)
        first.edit_setup('add_group', dict(label='Extra group'))
        before = read_research_setup(project)
        with pytest.raises(ProjectFlowError):
            second.edit_setup('heading', dict(theme='Lost update', objectives='', approved_by='Researcher'))
        assert read_research_setup(project) == before
        with pytest.raises(ProjectFlowError, match='another window'):
            second.edit_setup('add_group', dict(label='Lost group'))
        assert len(second.state()['strategy_draft']['groups']) == 1


def test_draft_storage_rejects_invalid_terms_and_scope():
    with pytest.raises(ValueError):
        restore(dict(search_scope=dict(sources=['unknown'])))
    with pytest.raises(ValueError):
        restore(dict(groups=[dict(label='Group', terms=[dict(text='x', origin='ai', rationale='', enabled=True)])]))


@pytest.mark.parametrize('committed', [False, True])
def test_approval_recovery_survives_process_restart(tmp_path, monkeypatch, committed):
    project = create_project(tmp_path, 'Approval recovery')
    with closing(RealProjectFlow()) as flow:
        flow.open_native_folder(project.root)
        seed(flow)
        flow.preview_setup()
        original = flow._operation
        def interrupted(name, **kwargs):
            if name == 'admit_strategy':
                if committed:
                    original(name, **kwargs)
                raise ProjectFlowError('worker_interrupted')
            return original(name, **kwargs)
        monkeypatch.setattr(flow, '_operation', interrupted)
        with pytest.raises(ProjectFlowError):
            flow.approve_setup()
        request = flow._pending_admission_id
        assert request
    with closing(RealProjectFlow()) as reopened:
        reopened.open_native_folder(project.root)
        if not committed:
            assert reopened._pending_admission_id == request
            reopened.approve_setup()
        assert reopened.state()['planning_mode'] == 'saved'
        assert len(reopened.state()['runs']) == 1


def test_readonly_saved_plan_comes_from_immutable_strategy(tmp_path):
    project = create_project(tmp_path, 'Authoritative saved plan')
    with closing(RealProjectFlow()) as flow:
        flow.open_native_folder(project.root)
        seed(flow)
        flow.preview_setup()
        flow.approve_setup()
    with sqlite3.connect(project.database_path) as db:
        db.execute("INSERT INTO audit_events(occurred_at_utc,event_type,details_json) "
                   "SELECT occurred_at_utc,event_type,json_set(details_json,'$.draft.groups[0].label','Incorrect label') "
                   "FROM audit_events WHERE event_type='planning_draft_v1' ORDER BY event_id DESC LIMIT 1")
    with closing(RealProjectFlow()) as reopened:
        reopened.open_native_folder(project.root)
        assert reopened.state()['strategy_draft']['groups'][0]['label'] == 'Right ventricular failure'


def test_checkboxes_preserve_other_pages_and_selection_export(tmp_path):
    project, run, _, _ = populated(tmp_path)
    with closing(master_results.MasterResults.capture(project, run)) as results:
        rows = results.page(master_results.DEFAULT)['rows']
        first, second = [r['publication_id'] for r in rows[:2]]
        results.select_page([first], [first])
        results.select_page([second], [second])
        assert results.page(master_results.DEFAULT)['selected'] == 2
        results.select_page([first], [])
        assert [r['publication_id'] for r in results.records(master_results.DEFAULT, 'selected')] == [second]
        with pytest.raises(ValueError):
            results.select_page([first], [second])
        assert results.page(master_results.DEFAULT)['selected'] == 1


def test_classification_form_atomic_failure_replay_and_stale_review(tmp_path):
    project, run, _, _ = populated(tmp_path)
    with closing(master_results.MasterResults.capture(project, run)) as results:
        pid = results.page(master_results.DEFAULT)['rows'][0]['publication_id']
    view = study_classification.read_classification(project, pid)
    assert view['title'] == 'PRIVATE TITLE'
    choices = dict(view['current'])
    args = dict(actor='Reviewer', rationale='Checked source evidence', expected_revision=view['revision'], confirmed=True)
    invalid = dict(choices, population=['unsupported'])
    with pytest.raises(ValueError):
        study_classification.review_classifications(project, pid, choices=invalid, **args)
    assert study_classification.read_classification(project, pid) == view
    saved = study_classification.review_classifications(project, pid, choices=choices, **args)
    assert len(saved['decisions']) == len(study_classification.LABELS)
    again = study_classification.review_classifications(project, pid, choices=choices, **args)
    assert again == saved
    with pytest.raises(ValueError):
        study_classification.review_classifications(project, pid, choices=choices, **dict(args, rationale='Stale changes'))


def test_results_export_verifies_file_and_refuses_overwrite(tmp_path):
    project, run, _, _ = populated(tmp_path)
    destination = tmp_path / 'out'
    destination.mkdir()
    with closing(RealProjectFlow()) as flow:
        flow.open_native_folder(project.root)
        flow.select_run(run)
        page = flow.master_action('ensure', {})['master_results']
        flow.master_action('select_page', dict(revision=page['revision'], visible=[r['publication_id'] for r in page['rows']],
                           ids=[page['rows'][0]['publication_id']]))
        assert flow.master_action('ensure', {})['master_results']['selected'] == 1
        flow.export_master_to(destination, name='Chosen.xlsx', revision=page['revision'], scope='selected', include_abstracts=False)
        assert flow.output_path() == destination / 'Chosen.xlsx'
        with pytest.raises(ProjectFlowError, match='already exists'):
            flow.export_master_to(destination, name='Chosen.xlsx', revision=page['revision'], scope='selected', include_abstracts=False)
        (destination / 'Chosen.xlsx').write_bytes(b'changed')
        with pytest.raises(ValueError):
            flow.output_path()


def test_single_save_strategy_workbook_and_reopened_verification(tmp_path):
    project, run, _, _ = populated(tmp_path)
    destination = tmp_path / 'reports'
    destination.mkdir()
    with closing(RealProjectFlow()) as flow:
        flow.open_native_folder(project.root)
        flow.select_run(run)
        flow.save_workbook_to(destination, 'Strategy.xlsx')
        eid = flow.state()['selected_export_id']
        assert flow.output_path() == destination / 'Strategy.xlsx'
        original = (destination / 'Strategy.xlsx').read_bytes()
        with pytest.raises(ProjectFlowError, match='Previous report exports'):
            flow.save_workbook_to(destination, 'Strategy.xlsx')
    with closing(RealProjectFlow()) as flow:
        flow.open_native_folder(project.root)
        flow.select_run(run)
        flow.select_export(eid)
        flow.continue_workbook(destination)
        assert flow.output_path() == destination / 'Strategy.xlsx'
        assert (destination / 'Strategy.xlsx').read_bytes() == original


def test_empty_export_digest_and_changed_output(tmp_path):
    from research_y.export_files import Directory
    import hashlib
    (tmp_path / 'Empty.ris').write_bytes(b'')
    digest = hashlib.sha256(b'').hexdigest()
    with Directory(tmp_path) as directory:
        assert directory.verify_digest('Empty.ris', digest=digest) == (digest, 0)
        (tmp_path / 'Empty.ris').write_bytes(b'changed')
        with pytest.raises(ValueError):
            directory.verify_digest('Empty.ris', digest=digest)
