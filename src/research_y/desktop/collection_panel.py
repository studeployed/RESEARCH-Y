"""Guide to the next existing, consent-preserving collection step."""
from research_y.desktop.feedback import explain

TITLES = {
    'preview_wos': 'Collect Web of Science records', 'inspect_wos': 'Collect Web of Science records',
    'inspect_pubmed': 'Collect PubMed identifiers',
    'preview_pubmed_metadata': 'Collect PubMed article details',
    'inspect_pubmed_metadata': 'Collect PubMed article details',
}


def selected_section(state, query_id):
    """Choose a screen from the freshly inspected checkpoint, never run work."""
    board = state.get('run_execution_board') or {}
    step = next((q['next_step'] for q in board.get('queries', []) if q['query_id'] == query_id), None)
    acquired = state.get('wos_acquisition') or {}
    job = acquired.get('checkpoint') or {}
    if (step == 'inspect_wos' and acquired.get('query_id') == query_id
            and acquired.get('approved_gui_retention') and job.get('stage') in ('verify', 'final')
            and not job.get('enumeration_reconciled') and not job.get('worker_active')
            and job.get('requests_unknown') == 0 and (job.get('pages_expected') or 0) > 1):
        return 'Verify Web of Science coverage'
    return TITLES.get(step)


def render_collection(ui, state, act):
    ui.label('Collect your search results').classes('section-title')
    ui.label('Work through the databases below. Each Continue opens the next step; it does not send a request.')
    board = state.get('run_execution_board')
    if not board:
        ui.button('Show collection steps', on_click=lambda: act('run_board_refresh')).props('data-testid=collection-start')
        return
    names = {g['group_id']: g['label'] for g in board['groups']}
    for row in board['queries']:
        provider = 'PubMed' if row['source_name'] == 'pubmed' else 'Web of Science'
        with ui.card().classes('collection-card'):
            ui.label(provider + ' · ' + names.get(row['group_id'], 'Search group')).classes('section-title')
            matches = row['reported_matches']
            ui.label(f"{row['identifiers_retrieved']:,} record identifiers saved · {row['metadata_records_retained']:,} article details saved")
            ui.label('Database matches: ' + ('not checked yet' if matches is None else f'{matches:,}'))
            stage = row['source_stage'].replace('pubmed_', '').replace('wos_', '').replace('_', ' ')
            ui.label(stage.capitalize()).classes('setting-summary')
            for warning in row['warnings']:
                ui.label(explain(warning)).classes('message warning')
            if row['next_step'] in TITLES:
                ui.button('Continue ' + provider, on_click=lambda q=row['query_id'], rev=board['revision']:
                          act('run_board_select', dict(query_id=q, revision=rev))).props('data-testid=collection-continue')
    ui.button('Refresh progress', on_click=lambda: act('run_board_refresh')).props('flat')
    ui.label('Keep RESEARCH-Y open during collection. Pause controls appear for a running session; saved progress is retained.').classes('review-hint')
