from research_y.desktop.search_path import search_steps


def test_planning_milestones_belong_to_draft():
    term = {'enabled': False}
    state = dict(saved_question={'theme': 'Example'}, strategy_draft=dict(groups=[{'terms': [term]}], preview=None),
                 selected_run_id='older-run', runs=['older-run'])
    def done():
        return [label for label, complete in search_steps(state, planning=True) if complete]
    assert done() == ['Save question']
    term['enabled'] = True
    state['strategy_draft']['preview'] = {'sources': []}
    assert done() == ['Save question', 'Add search terms', 'Preview search']


def test_pilots_and_other_runs_cannot_mark_collection_started():
    state = dict(runs=['a', 'b'], selected_run_id='a', preflight_report={'run_id': 'a', 'last_review': None},
                 run_execution_board={'run_id': 'b', 'queries': [{'reported_matches': 4}]},
                 report={'run': {'run_id': 'a'}, 'queries': [{'executed_at_utc': None}]},
                 last_pubmed_pilot={'reported_matches': 5})
    def flags():
        return [done for _, done in search_steps(state, planning=False)]
    assert flags() == [True, True, True, False, False]
    state['preflight_report']['last_review'] = {'reviewer': 'Researcher'}
    assert flags() == [True, True, True, True, False]
    state['run_execution_board'] = {'run_id': 'a', 'queries': [{'reported_matches': 0}]}
    assert flags()[-1]
    state['run_execution_board'] = None
    state['report']['queries'][0]['executed_at_utc'] = '2026-01-01T12:00:00Z'
    assert flags()[-1]
    state['selected_run_id'] = None
    assert flags() == [True, False, False, False, False]
