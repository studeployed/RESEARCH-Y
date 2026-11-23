"""Focused review of an immutable search, beside the researcher's answers."""
from contextlib import nullcontext
from datetime import date

from research_y.desktop.search_checks import CHECKS, ANSWERS, PRESS_HELP
from research_y.desktop.feedback import readable_time


SOURCE_NAMES = {'pubmed': 'PubMed', 'wos': 'Web of Science Starter'}
COVERAGE = {
    'pubmed': 'All Fields within PubMed indexed records.',
    'wos': 'Topic: titles, abstracts, author keywords and Keywords Plus.',
}


def review_values(preview, researcher, drafts):
    """Keep edits only with their exact saved run/plan in this app window."""
    key = (preview['run_id'], preview['plan_sha256'])
    if key not in drafts:
        previous = preview['last_review'] or {}
        name = previous.get('reviewer_name', researcher)
        role = previous.get('reviewer_role', 'researcher_self_check')
        drafts[key] = dict(
            reviewer_name=name, reviewer_role=role,
            same_researcher=bool(researcher and name == researcher and role == 'researcher_self_check'),
            press_items=dict(previous.get('press_items') or {k: 'not_reviewed' for k in CHECKS}),
            review_note=previous.get('review_note', ''),
            known_text='\n'.join(previous.get('known_relevant', [])),
        )
    return drafts[key]


def database_status(source, observations):
    """Summarise actual pilot receipts; a compiler check is not a provider test."""
    records = [observations.get(q['query_id']) for q in source['queries']]
    successful = {'count_reported_not_retrieved', 'translation_review_required'} if source['source_name'] == 'pubmed' else {
        'count_reported_sample_not_retained', 'quota_exhausted_after_probe', 'entitlement_unverified'}
    returned = sum(bool(r and r['status'] in successful) for r in records)
    problems = False
    for record in records:
        if record is None:
            continue
        if record['status'] not in successful or record.get('warnings') or record.get('review_reasons'):
            problems = True
        if source['source_name'] == 'pubmed' and (
                record['status'] != 'count_reported_not_retrieved' or
                record.get('translation_matches_submitted') is not True):
            problems = True
    if not any(records):
        return 'Not tested yet. Use the database pilot from Run search when ready.', 'info'
    text = f'{returned} of {len(records)} queries returned a pilot result.'
    if problems:
        return text + ' Review the test details below; a warning, incomplete test or unverified translation remains.', 'warning'
    if returned < len(records):
        return text + ' Remaining queries are not tested.', 'info'
    if source['source_name'] == 'wos':
        return text + ' Starter does not return its interpretation of the query.', 'info'
    return text + ' The returned query matched the submitted query.', 'success'


def render_context(ui, preview):
    ui.label('Saved question').classes('section-title')
    ui.label(preview['theme']).classes('review-theme').props('data-testid=review-theme')
    ui.label(preview.get('objectives') or 'No additional objective recorded.').props('data-testid=review-objective')
    with ui.element('section').classes('review-facts').props('data-testid=review-limits'):
        ui.label('Limits').classes('section-title')
        limits = preview['limitations']
        ui.label('None — no date, language, species or study-type limits.' if limits.startswith('none recorded') else limits)
    with ui.element('section').classes('review-facts').props('data-testid=review-fields'):
        ui.label('Database coverage').classes('section-title')
        for source in preview['sources']:
            ui.label(SOURCE_NAMES[source['source_name']] + ' · ' + COVERAGE[source['source_name']]).props(
                'data-testid=preflight-coverage')
        ui.label('Neither source searches article full text. Starter Topic is narrower than Web of Science web-interface All Fields.')
    group_word = 'group' if preview['active_group_count'] == 1 else 'groups'
    ui.label(f"Search terms · {preview['active_term_count']} included in {preview['active_group_count']} {group_word}").classes('section-title')
    ui.label('Match any included phrase in any group (OR).')
    with ui.element('div').classes('review-terms').props('data-testid=review-terms'):
        for group in preview['groups']:
            ui.label(group['label']).classes('review-group').props('data-testid=preflight-group')
            for term in group['terms']:
                ui.label(term['text'] + ('' if term['enabled'] else ' · excluded')).classes(
                    '' if term['enabled'] else 'review-excluded').props('data-testid=preflight-term')
    ui.label('Database checks').classes('section-title')
    ui.label('RESEARCH-Y checked the generated query structure against this saved plan. Database responses are shown separately below.').classes('message info')
    observations = preview.get('pilot_observations', {})
    for source in preview['sources']:
        text, severity = database_status(source, observations)
        ui.label(SOURCE_NAMES[source['source_name']] + ' · ' + text).classes('message ' + severity).props(
            'data-testid=review-database-status')
    if not observations:
        ui.label('Match counts and workload are not known for this saved search.').props('data-testid=preflight-unknown')
    else:
        ui.label('Pilot results estimate workload; they do not retrieve the search results.')
    with ui.expansion('Exact queries and test details').props('data-testid=review-query-details'):
        names = {g['group_id']: g['label'] for g in preview['groups']}
        for source in preview['sources']:
            ui.label(SOURCE_NAMES[source['source_name']]).classes('section-title')
            for query in source['queries']:
                ui.label(names[query['group_id']] + ' · ' + query['exact_query']).classes('query-text').props('data-testid=preflight-query')
                observed = observations.get(query['query_id'])
                if not observed:
                    ui.label('Not tested yet.')
                    continue
                ui.label('Test recorded · ' + observed['observed_utc'] + ' (UTC)')
                ui.label('Test outcome · ' + observed['status'].replace('_', ' '))
                ui.label('Reported matches · ' + str(observed['reported_matches'] if observed['reported_matches'] is not None else 'unknown'))
                if observed.get('accepted_translation'):
                    ui.label('Returned PubMed query · ' + observed['accepted_translation']).classes('query-text')
                for warning in observed.get('warnings', []) + observed.get('review_reasons', []):
                    ui.label(str(warning)).classes('message warning')
                for label, key in (('Estimated result pages', 'estimated_result_pages'), ('Estimated metadata batches before reuse', 'estimated_metadata_batches')):
                    if observed.get(key) is not None:
                        ui.label(label + ' · ' + str(observed[key]))
            for warning in source['warnings']:
                ui.label(warning).classes('message info')
        ui.label('Estimates are per query; overlap, retries, date partitioning and existing metadata can change the work required.')
        ui.label('Plan reference · ' + preview['plan_sha256']).props('data-testid=preflight-hash')
    # The unconditional legacy PubMed warning predates the receipt evidence above.
    for warning in preview['warnings']:
        if not warning.startswith(('PubMed phrase behavior', 'PRESS self-check', 'Wide search')):
            ui.label(warning).classes('message warning')
    ui.label('A broad search can return many results. Review pilot counts before collecting records.').classes('message info')


def render_summary(ui, review):
    ui.label('Reviewer · ' + review['reviewer_name'])
    ui.label('Researcher self-check' if review['reviewer_role'] == 'researcher_self_check' else 'External peer review (reported by user)')
    for key, value in review['press_items'].items():
        ui.label(CHECKS[key][0] + ' · ' + ANSWERS[value]).classes('message warning' if value == 'needs_revision' else 'setting-summary')
    if review['review_note']:
        ui.label(review['review_note']).classes('message info')
    if review['known_relevant']:
        ui.label('Known records to check · ' + ', '.join(review['known_relevant']))


def render_known_checks(ui, preview, researcher, act):
    with ui.expansion('Record a known-article check (optional)'):
        names = {g['group_id']: g['label'] for g in preview['groups']}
        choices = {q['query_id']: SOURCE_NAMES[s['source_name']] + ' · ' + names[q['group_id']] + ' · ' + q['exact_query']
                   for s in preview['sources'] for q in s['queries']}
        query = ui.select(choices, label='Exact query checked')
        identifier = ui.input('Known record identifier')
        checked = ui.input('Date checked', value=date.today().isoformat())
        outcome = ui.select(['found', 'not_found', 'inconclusive'], label='Observed outcome')
        actor = ui.input('Researcher performing the source check', value=researcher)
        basis = ui.input('How the record was checked against the exact query')
        ui.button('Record observed source check', on_click=lambda: act('record_known_check', dict(
            plan_sha256=preview['plan_sha256'], query_id=query.value, identifier=identifier.value,
            checked_on=checked.value, outcome=outcome.value, actor=actor.value, basis=basis.value)))
        for check in preview.get('known_item_checks', []):
            ui.label(f"{check['checked_on']} · {check['actor']} · {choices[check['query_id']]} · {check['identifier']} · {check['outcome']} · {check['basis']}")


def render_search_review(ui, state, act, workspace=None, error=None):
    preview = state['preflight_report']
    ui.label('Check the search plan').classes('section-title').props('data-testid=preflight-heading')
    if not state['preflight_review_reconciliation_required']:
        ui.button('Check saved plan' if preview is None else 'Refresh saved plan', on_click=lambda: act('preflight_inspect')).props('data-testid=preflight-inspect')
    if preview is None:
        ui.label('Review the saved question, terms and limits before sending a search to a database.')
        return
    previous = preview['last_review']
    if previous:
        ui.label('Search checks saved · ' + previous['reviewer_name'] + ' · ' + readable_time(previous['occurred_at_utc'])).classes('message success').props('data-testid=preflight-last-review')
        incomplete = sum(value != 'reviewed' for value in previous['press_items'].values())
        if incomplete:
            ui.label(f'{incomplete} checks still need attention. Saving answers does not mark them as passed.').classes('message warning')
    else:
        ui.label('The saved plan is ready to review. No database request has been sent by this check.')
    dialog = None
    if workspace is not None:
        dialog = ui.dialog(value=workspace.review_open).props('maximized').bind_value(workspace, 'review_open')
        ui.button('Review search', on_click=dialog.open).props('data-testid=review-open')
    with dialog if dialog is not None else nullcontext():
        with ui.element('section').classes('search-review').props('data-testid=search-review aria-label="Review saved search"'):
            with ui.element('header').classes('review-header'):
                ui.label(f"Review search {preview['version_number']} · {state['project']['name']}").classes('section-title')
                if dialog:
                    ui.button('Back to Run search', on_click=dialog.close).props('flat data-testid=review-close')
            with ui.element('footer').classes('review-footer'):
                ui.label('Draft answers are kept in this app window. Saving checks does not start a database search.').classes('review-hint')
                with ui.element('div').classes('review-actions') as actions:
                    pass
            def action_button(*args, **kwargs):
                with actions:
                    return ui.button(*args, **kwargs)
            with ui.element('div').classes('review-comparison'):
                with ui.element('section').classes('review-context').props('tabindex=0 aria-label="Saved search details"'):
                    render_context(ui, preview)
                with ui.element('section').classes('review-answers').props('tabindex=0 aria-label="Search checks"'):
                    ui.label('Search checks').classes('section-title')
                    ui.label('Compare these answers with the saved search details.').classes('review-hint')
                    ui.label('Based on PRESS · About these checks').classes('acronym').props('tabindex=0 data-testid=press-help').tooltip(PRESS_HELP)
                    if error:
                        ui.label('Could not complete that action · ' + error).classes('message error').props('data-testid=review-error')
                    candidate = state['preflight_candidate']
                    if state['preflight_review_reconciliation_required']:
                        ui.label('The save result is uncertain. Check the original save before editing.').classes('message error').props('data-testid=preflight-retry-required')
                        action_button('Check original save', on_click=lambda: act('preflight_record')).props('data-testid=preflight-retry')
                    elif candidate:
                        ui.label('Review answers locked — check before recording.').classes('message info').props('data-testid=preflight-confirmation')
                        render_summary(ui, candidate)
                        action_button('Edit answers', on_click=lambda: act('preflight_revise')).props('outline data-testid=preflight-revise')
                        action_button('Confirm and save checks', on_click=lambda: act('preflight_record')).props('data-testid=preflight-record')
                    elif previous and workspace is not None and workspace.review_saved:
                        ui.label('✓ Search checks saved').classes('message success').props('data-testid=review-saved')
                        render_summary(ui, previous)
                        ui.button('Edit checks', on_click=lambda: act('preflight_revise')).props('outline data-testid=preflight-revise')
                        if dialog:
                            action_button('Done', on_click=dialog.close)
                    else:
                        researcher = state['strategy_draft']['approved_by']
                        values = review_values(preview, researcher, workspace.review_drafts if workspace else {})
                        ui.label('Reviewer · ' + (values['reviewer_name'] or 'Enter your name below'))
                        with ui.expansion('Reviewer details', value=not bool(values['reviewer_name'])):
                            same = ui.checkbox('I am reviewing my own search').bind_value(values, 'same_researcher')
                            reviewer = ui.input('Reviewing researcher').bind_value(values, 'reviewer_name').props('data-testid=preflight-reviewer')
                            role = ui.select({'researcher_self_check': 'Researcher self-check', 'independent_peer_reported': 'External peer review (user-reported)'}, label='Review role').bind_value(values, 'reviewer_role').props('data-testid=preflight-role')
                            def use_researcher(e):
                                reviewer.set_value(researcher if e.value else '')
                                role.set_value('researcher_self_check')
                            same.on_value_change(use_researcher)
                            reviewer.bind_enabled_from(same, 'value', backward=lambda v: not v)
                            role.bind_enabled_from(same, 'value', backward=lambda v: not v)
                        for key in ('research_objective', 'terminology_coverage', 'boolean_logic', 'spelling',
                                    'source_syntax', 'search_fields', 'limits'):
                            label, help_text = CHECKS[key]
                            with ui.element('div').classes('review-check'):
                                if key == 'research_objective':
                                    ui.label('Question and search terms').classes('section-title')
                                elif key == 'source_syntax':
                                    ui.label('Database behaviour').classes('section-title')
                                elif key == 'limits':
                                    ui.label('Search limits').classes('section-title')
                                ui.label(label).tooltip(help_text).props('tabindex=0')
                                if key in ('source_syntax', 'search_fields'):
                                    ui.label(help_text).classes('review-hint')
                                ui.radio(ANSWERS).bind_value(values['press_items'], key).props('inline dense data-testid=review-check-' + key)
                        with ui.expansion('Notes and known articles (optional)'):
                            note = ui.textarea('Review notes, concerns, or limitations').bind_value(values, 'review_note').props('rows=3 data-testid=review-note')
                            known = ui.textarea('Known-relevant identifiers to check (one per line)').bind_value(values, 'known_text').props('rows=2')
                        action_button('Review answers', on_click=lambda: act('preflight_offer', dict(
                            reviewer_name=values['reviewer_name'], reviewer_role=values['reviewer_role'],
                            press_items=dict(values['press_items']), review_note=note.value or '',
                            known_relevant=tuple(line.strip() for line in (known.value or '').splitlines() if line.strip())))).props('data-testid=preflight-offer')
                    ui.label('These answers record a researcher review. Database collection requires its own confirmation.').classes('review-hint')
    render_known_checks(ui, preview, state['strategy_draft']['approved_by'], act)
