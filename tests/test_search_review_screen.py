"""Evidence and draft isolation for the focused saved-search review."""
from copy import deepcopy

from research_y.desktop.search_review import database_status, review_values


def test_review_edits_are_bound_to_the_run_and_frozen_plan():
    plan = dict(run_id='first', plan_sha256='a', last_review=None)
    drafts = {}
    values = review_values(plan, 'Stuart', drafts)
    assert values['same_researcher'] and values['reviewer_name'] == 'Stuart'
    assert set(values['press_items'].values()) == {'not_reviewed'}
    values['press_items']['terminology_coverage'] = 'needs_revision'
    values['review_note'] = 'Keep this unfinished observation'
    assert review_values(plan, 'Stuart', drafts) is values
    other = review_values(dict(plan, run_id='second'), 'Stuart', drafts)
    assert other['review_note'] == ''
    assert other['press_items']['terminology_coverage'] == 'not_reviewed'
    changed = review_values(dict(plan, plan_sha256='b'), 'Stuart', drafts)
    assert changed['review_note'] == ''
    assert values['review_note'] == 'Keep this unfinished observation'


def test_previous_external_answers_are_copied_without_relabelling_the_reviewer():
    receipt = dict(reviewer_name='External reviewer', reviewer_role='independent_peer_reported',
                   press_items={'spelling': 'needs_revision'}, review_note='Typo', known_relevant=['PMID 1'])
    plan = dict(run_id='first', plan_sha256='a', last_review=receipt)
    before = deepcopy(receipt)
    values = review_values(plan, 'Stuart', {})
    assert not values['same_researcher']
    assert values['reviewer_role'] == 'independent_peer_reported'
    values['press_items']['spelling'] = 'reviewed'
    assert receipt == before


def test_database_checks_do_not_treat_absent_partial_or_warning_evidence_as_a_pass():
    source = dict(source_name='pubmed', queries=[dict(query_id='a'), dict(query_id='b')])
    assert database_status(source, {})[0].startswith('Not tested yet')
    good = dict(status='count_reported_not_retrieved', translation_matches_submitted=True)
    partial = database_status(source, {'a': good})
    assert '1 of 2' in partial[0] and partial[1] == 'info'
    assert 'not tested' in partial[0]
    for suspect in (dict(status='requested_indeterminate'),
                    dict(status='probe_failed'),
                    dict(status='translation_review_required'),
                    dict(good, warnings=['Phrase not found']),
                    dict(good, translation_matches_submitted=None)):
        result = database_status(source, {'a': good, 'b': suspect})
        assert result[1] == 'warning'
    assert database_status(source, {'a': good, 'b': good})[1] == 'success'


def test_starter_response_never_claims_its_translation_was_verified():
    source = dict(source_name='wos', queries=[dict(query_id='a')])
    result = database_status(source, {'a': dict(status='count_reported_sample_not_retained')})
    assert result[1] == 'info'
    assert 'does not return its interpretation' in result[0]
