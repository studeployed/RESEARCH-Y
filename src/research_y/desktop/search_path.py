"""Milestones for the current draft or an explicitly opened search."""

STEP_PURPOSES = {
    'Save question': 'Record the purpose of the research and who is preparing it.',
    'Add search terms': 'Choose the phrases that should find relevant articles.',
    'Preview search': 'See the exact wording prepared for each database; no request is sent.',
    'Approve and save search': 'Keep a fixed version of the plan; collection has not started.',
    'Open and check saved plan': 'Move to Run search to review this version before collection.',
    'Open saved search': 'Choose which saved version to use.',
    'Check saved plan': 'Compare the question, terms, limits and database coverage together.',
    'Confirm plan checklist': 'Record what you checked and any concerns; this does not contact a database.',
    'Start database collection': 'Use Collect your search results and confirm a database request to retrieve records.',
}


def search_steps(state, *, planning):
    if planning:
        draft = state['strategy_draft']
        saved = state.get('planning_mode') == 'saved'
        terms = any(term['enabled'] for group in draft['groups'] for term in group['terms'])
        return [
            ('Save question', bool(state['saved_question'])),
            ('Add search terms', terms),
            ('Preview search', saved or draft['preview'] is not None),
            ('Approve and save search', saved),
            ('Open and check saved plan', False),
            ('Start database collection', False),
        ]

    selected = state['selected_run_id']
    preflight = state['preflight_report']
    checked = bool(selected and preflight and preflight['run_id'] == selected)
    report = state['report']
    board = state['run_execution_board']
    # Pilot receipts and locally prepared jobs carry no collection evidence.
    recorded = bool(selected and (
        (report and report['run']['run_id'] == selected
         and any(q['executed_at_utc'] for q in report['queries']))
        or (board and board['run_id'] == selected
            and any(q['reported_matches'] is not None for q in board['queries']))))
    return [
        ('Approve and save search', bool(state['runs'])),
        ('Open saved search', bool(selected)),
        ('Check saved plan', checked),
        ('Confirm plan checklist', bool(checked and preflight['last_review'])),
        ('Start database collection', recorded),
    ]


def render_search_steps(ui, state, *, planning):
    steps = search_steps(state, planning=planning)
    next_step = None if steps[-1][1] else next((label for label, done in steps if not done), None)
    with ui.element('section').classes('search-path').props('aria-label="Search progress"'):
        ui.label('Next · ' + next_step if next_step else 'Collection started · follow run progress').classes('path-next')
        with ui.expansion('Steps to your search' if planning else 'Saved search progress').props('dense'), ui.element('ol'):
            for label, done in steps:
                current = label == next_step
                with ui.element('li').classes('done' if done else 'current' if current else '') as item:
                    if current:
                        item.props('aria-current=step')
                    ui.label(('Done · ' if done else 'Next · ' if current else '') + label)
                    ui.label(STEP_PURPOSES[label]).classes('step-purpose')
        if not planning:
            review = (state.get('preflight_report') or {}).get('last_review')
            if review:
                unchecked = sum(v == 'not_reviewed' for v in review['press_items'].values())
                concerns = sum(v == 'needs_revision' for v in review['press_items'].values())
                ui.label(f'Checks recorded · {unchecked} unchecked · {concerns} need revision').classes('check-status')
        if not planning and steps[-1][1]:
            ui.label('Database collection has started. See run progress for coverage.')
        elif not planning and any(state[key] for key in (
                'run_coordination_pending', 'pubmed_source_pending', 'wos_acquisition_tick_pending')):
            ui.label('Collection requested. Waiting for a recorded database response.')
