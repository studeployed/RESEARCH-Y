"""Plain-language action feedback; diagnostic codes remain available separately."""
from datetime import datetime


def readable_time(value):
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).strftime('%d %b %Y, %H:%M UTC')
    except (ValueError, AttributeError):
        return 'time unavailable'


ERRORS = {
    'wos_provider_cooldown_may_apply': 'Web of Science may require a pause before the next request. Continue to check the saved retry time.',
    'wos_attempt_outcome_unknown_no_automatic_retry': 'The last Web of Science request has an unknown outcome. Continue to inspect it before retrying.',
    'wos_worker_or_interrupted_ownership_not_proven_stopped': 'A Web of Science session may still be running. Continue to check its status before starting another.',
    'invalid_project': 'Choose the project folder containing project.ryproj.',
    'invalid_setup_input': 'Check the entry for duplicate terms, missing text or unsupported characters.',
    'strategy_preview_invalid': 'Enter a question, your name and at least one search term, then preview again. Quotes and wildcards inside a term are not supported.',
    'select_existing_request': 'An export with that name already exists. Open it under Previous exports to continue or verify it.',
    'worker_interrupted': 'The operation was interrupted. Its outcome is not yet confirmed; use the recovery action shown below.',
    'operation_unavailable': 'This action could not finish. Your saved project is unchanged; try again or save a diagnostic report from Project details.',
    'run_selection_required': 'Open a saved search first.',
    'preflight_required': 'Review and save the search checks first.',
}


def explain(code):
    if code in ERRORS:
        return ERRORS[code]
    if '_' in code and ' ' not in code:
        if 'reconciliation' in code:
            return 'The last operation has an unconfirmed outcome. Check its saved progress before starting another action.'
        return 'This action needs attention: ' + code.replace('_', ' ') + '. See the related section for the next step.'
    return code


SUCCESS = {
    'setup_edit': 'Saved.', 'save_question': 'Question saved.', 'begin_plan': 'Draft ready to edit.',
    'setup_preview': 'Preview ready.', 'setup_approve': 'Search saved. Open it in Run search.',
    'preflight_record': 'Search checks saved.', 'candidate_queue_review': 'Comparison opened below.',
    'study_queue': 'Review list updated.', 'master_results': 'Results updated.',
    'native_master_export': 'Results saved.',
}
