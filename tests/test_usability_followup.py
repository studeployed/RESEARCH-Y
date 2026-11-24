from contextlib import closing
from research_y.desktop.actions import perform_action
from research_y.desktop.collection_panel import render_collection, selected_section
from research_y.desktop.candidate_panel import decision_options, review_values
from research_y.desktop.flow import RealProjectFlow
from research_y.desktop.workspace import ProjectWorkspace
from research_y.desktop.pubmed_profile import PubMedHostProfile
from research_y.desktop.wos_profile import WoSHostProfile
from test_run_execution_board import _project, _digest


class Buttons:
    """Capture the real renderer's callbacks, not a duplicate action mapping."""
    def __init__(self):
        self.buttons = []
    def label(self, *args, **kwargs):
        return self
    def card(self):
        return self
    def button(self, label, on_click):
        self.buttons.append((label, on_click))
        return self
    def props(self, *args):
        return self
    def classes(self, *args):
        return self
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass


def test_every_rendered_continue_routes_to_its_real_offline_step(tmp_path):
    project, run, _ = _project(tmp_path)
    with closing(RealProjectFlow(pubmed_profile=PubMedHostProfile('audit@example.invalid'),
                                 wos_profile=WoSHostProfile('OFFLINE-FAKE-KEY'))) as flow:
        flow.open_native_folder(project.root)
        flow.select_run(run)
        state = flow.inspect_run_execution_board()
        before = _digest(project)
        ui = Buttons()
        render_collection(ui, state, lambda action, value=None: perform_action(flow, action, value))
        continued = 0
        for label, callback in ui.buttons:
            if not label.startswith('Continue '):
                continue
            result = callback()
            if label == 'Continue PubMed':
                assert result['pubmed_source']['checkpoint'] is None
            else:
                assert result['wos_acquisition_offer']['exact_query'].startswith('TS=')
                flow.dismiss_wos_acquisition()
            assert _digest(project) == before
            continued += 1
        assert continued == 4


def test_duplicate_choices_do_not_offer_moving_a_historical_record():
    pair = dict(retrieval_ids=['a','b'], run_id='current', cross_run=True,
                sources=[dict(retrieval_id='a',run_id='previous'),dict(retrieval_id='b',run_id='current')])
    assert decision_options(pair) == [('b','A','second')]
    assert decision_options(dict(pair,cross_run=False)) == [('a','B','first'),('b','A','second')]


def test_collection_focus_does_not_mix_groups_or_filter_other_steps():
    workspace = ProjectWorkspace()
    workspace.collection_section = 'Collect PubMed identifiers'
    workspace.collection_query = 'one'
    assert workspace.includes_collection_query('one', 'Collect PubMed identifiers')
    assert not workspace.includes_collection_query('two', 'Collect PubMed identifiers')
    assert workspace.includes_collection_query('two', 'Collect Web of Science records')


def test_comparison_draft_survives_validation_but_not_changed_evidence():
    drafts = {}
    values = review_values({'revision': 'first'}, 'Researcher', drafts)
    values.update(evidence='Checked title and DOI', acknowledged=True)
    assert review_values({'revision': 'first'}, 'Researcher', drafts) is values
    assert review_values({'revision': 'changed'}, 'Researcher', drafts) == dict(
        actor='Researcher', evidence='', acknowledged=False)


def test_continue_opens_multpage_wos_verification_without_repeating_collection(tmp_path, monkeypatch):
    from test_gui_wos_acquisition import _ready_for_long_verification
    project, flow, run, query, clock, provider = _ready_for_long_verification(tmp_path, monkeypatch)
    with closing(flow):
        before, requests = _digest(project), len(provider.calls)
        board = flow.inspect_run_execution_board()['run_execution_board']
        state = perform_action(flow, 'run_board_select', dict(query_id=query['query_id'], revision=board['revision']))
        assert selected_section(state, query['query_id']) == 'Verify Web of Science coverage'
        assert _digest(project) == before and len(provider.calls) == requests
        state['wos_acquisition']['checkpoint']['requests_unknown'] = 1
        assert selected_section(state, query['query_id']) == 'Collect Web of Science records'
