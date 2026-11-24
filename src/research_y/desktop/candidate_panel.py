"""A focused, evidence-preserving comparison of two possible duplicates."""
import json
from contextlib import nullcontext
from research_y.desktop.feedback import explain


WARNINGS = {
    'incomplete_comparison_fields': 'Some citation details are missing. A matching title alone does not establish that these are the same article.',
    'prior_run_metadata_unchanged': 'These records match a previously reviewed pair. Check the earlier decision before recording this search.',
    'prior_run_metadata_changed': 'Database details changed since the earlier review. Reassess this pair.',
    'prior_run_decision_outdated': 'The earlier identity or review evidence changed. Reassess this pair.',
}
SOURCES = {'pubmed': 'PubMed', 'wos': 'Web of Science'}


def display_value(value):
    if value is None or value == '' or value == []:
        return 'Not supplied'
    if isinstance(value, list):
        return '; '.join(display_value(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def decision_options(pair):
    """Only a current-run original may move in a cross-run comparison."""
    result = []
    for index, rid in enumerate(pair['retrieval_ids']):
        if pair.get('cross_run') and not any(
                s['retrieval_id'] == rid and s['run_id'] == pair['run_id'] for s in pair['sources']):
            continue
        result.append((rid, 'B' if index == 0 else 'A', 'first' if index == 0 else 'second'))
    return result


def review_values(pair, researcher, drafts):
    """Preserve text through validation errors, scoped to the exact evidence."""
    return drafts.setdefault(pair['revision'], dict(actor=researcher, evidence='', acknowledged=False))


def render_candidate_review(ui, state, act, *, workspace=None, error=None):
    pair = state['candidate_offer']
    if pair is None:
        return
    values = review_values(pair, state.get('researcher_name', ''), workspace.candidate_drafts if workspace else {})
    dialog = ui.dialog(value=True).props('maximized persistent') if workspace else None
    with dialog if dialog else nullcontext():
        with ui.element('section').classes('task-screen candidate-screen').props('data-testid=candidate-screen'):
            with ui.element('header').classes('review-header'):
                ui.label('Compare possible duplicates').classes('section-title').props('data-testid=candidate-heading')
                ui.button('Back to Results', on_click=lambda: act('candidate_review_dismiss')).props('flat data-testid=candidate-dismiss')
            with ui.column().classes('task-body'):
                ui.label('Are these the same article? Compare the citations and record your decision. Both original source records are retained.').classes('review-hint')
                if error:
                    ui.label(explain(error)).classes('message error').props('role=alert')
                with ui.element('div').classes('citation-pair'):
                    for index, side in enumerate(('left', 'right')):
                        source = pair['sources'][index]
                        with ui.element('section').classes('citation-card'):
                            ui.label('Record ' + ('A' if index == 0 else 'B') + ' · ' + SOURCES.get(source['source_name'], source['source_name'])).classes('section-title').props('data-testid=candidate-source')
                            for field in pair['comparison']:
                                if field['field'] not in ('title', 'authors', 'year', 'journal', 'pages', 'doi', 'pmid', 'accession'):
                                    continue
                                label = {'doi': 'DOI', 'pmid': 'PMID'}.get(field['field'], field['field'].capitalize())
                                ui.label(label + ' · ' + display_value(field[side]['value'])).props('data-testid=candidate-comparison')
                            if pair.get('cross_run'):
                                ui.label('From the current search' if source['run_id'] == pair['run_id'] else 'From an earlier search').classes('review-hint')
                for warning in pair['warnings']:
                    ui.label(WARNINGS.get(warning, warning.replace('_', ' ').capitalize())).classes('message warning').props('data-testid=candidate-warning')
                if pair.get('confidence') == 'automatic_high_confidence':
                    ui.label('Previously confirmed matching records recur unchanged. This is a suggestion; your decision is still required.').classes('message info').props('data-testid=candidate-confidence')
                with ui.expansion('Full comparison and review history'):
                    for field in pair['comparison']:
                        ui.label(field['field'].replace('_', ' ').capitalize() + ' · ' + field['comparison'].replace('_', ' '))
                        ui.label('A: ' + display_value(field['left']['value']) + ' (' + field['left']['status'].replace('_', ' ') + ')')
                        ui.label('B: ' + display_value(field['right']['value']) + ' (' + field['right']['status'].replace('_', ' ') + ')')
                    ui.label('Recorded status: ' + pair['status'].replace('_', ' ') + '. Earlier decisions: ' + str(pair['prior_decision_count']))
                    if pair['prior_decisions_omitted']:
                        ui.label(str(pair['prior_decisions_omitted']) + ' older decisions remain in the project audit.')
                    for previous in pair['recent_decisions']:
                        ui.label(previous['actor'] + ' · ' + previous['status'].replace('_', ' ') + ' · ' + previous['evidence']).props('data-testid=candidate-audit')
                        if previous.get('confidence_suggestion'):
                            ui.label('Earlier suggestion: ' + display_value(previous['confidence_suggestion']))
                    with ui.expansion('Technical identifiers'):
                        ui.label(json.dumps(pair, ensure_ascii=False, indent=2)).classes('diagnostic-text')
                ui.label('Your decision').classes('section-title')
                reviewer = ui.input('Researcher').bind_value(values, 'actor').props('data-testid=candidate-reviewer')
                rationale = ui.textarea('Evidence or reason for your decision').bind_value(values, 'evidence').props('rows=2 data-testid=candidate-rationale')
                acknowledge = ui.checkbox('I have reviewed the citations and every warning above').bind_value(values, 'acknowledged').props('data-testid=candidate-acknowledge')
                if not pair['pair_already_associated']:
                    # Show the consequences of each direction before its confirmation.
                    for rid, target, position in decision_options(pair):
                        with ui.element('section').classes('decision-card'):
                            ui.label('Same article · combine under record ' + target).classes('review-theme')
                            plan = pair.get('move_dispositions', {}).get(rid)
                            if plan:
                                ui.label(f"{plan['classifications']} classification records and {plan['documents']} documents stay with their original entry.")
                                if plan['sole_source']:
                                    ui.label('The combined entry links back to that history and its documents.')
                                ui.label(f"The source brings {plan['roles']} society roles and {plan['containers']} container links; {plan['retained_roles']} roles and {plan['retained_containers']} links remain with the original entry.")
                                if plan['apply_fields']:
                                    ui.label('Citation choices carried over: ' + ', '.join(plan['apply_fields']))
                                if plan['keep_target_fields']:
                                    ui.label('Existing choices kept: ' + ', '.join(plan['keep_target_fields']))
                            ui.button('Confirm same article · use ' + target, on_click=lambda rid=rid: act('candidate_review_decide', dict(
                                decision='confirmed_match', offer_revision=pair['revision'], move_retrieval_id=rid,
                                actor=reviewer.value, evidence=rationale.value, acknowledged=acknowledge.value))).props('data-testid=candidate-match-' + position)
                    ui.button('Different articles · keep separate', on_click=lambda: act('candidate_review_decide', dict(
                        decision='rejected_match', offer_revision=pair['revision'], move_retrieval_id=None,
                        actor=reviewer.value, evidence=rationale.value, acknowledged=acknowledge.value))).props('outline data-testid=candidate-reject')
                else:
                    ui.label('These records are already associated. To separate them, first review the current association using the reversal controls in Results.').classes('message info')
