"""P1-04i strict partition grammar; source spelling from live run 41216318046.

These are offline fixtures, not a claim of successful live retrieval.
"""

import pytest

from research_y.pubmed_date_translation import internal_create_date_equivalent

TERM = '"ECMO"[All Fields]'
RANGE = '1900/01/01:2026/11/01'
SUBMITTED = f'(({TERM})) AND ({RANGE}[crdt])'
ACCEPTED = f'{TERM} AND {RANGE}[Date - Create]'


@pytest.mark.parametrize('accepted', [
    ACCEPTED, SUBMITTED,
    f'({TERM}) AND ({RANGE}[Date - Create])',
    f'((({TERM}))) AND ((({RANGE}[crdt])))',
    f'(({TERM} AND {RANGE}[Date - Create]))',
    f'  ( {TERM} ) AND ( {RANGE}[Date - Create] )  ',
])
def test_observed_date_alias_and_only_redundant_groups_are_equivalent(accepted):
    assert internal_create_date_equivalent(SUBMITTED, accepted)


@pytest.mark.parametrize('term', [
    'research AND education', 'NOT or AND (in literal)',
    'alpha [crdt] beta', 'alpha [Date - Create] beta',
    'right (ventricle)', 'A AND B OR C', 'β-cell',
])
def test_quoted_content_is_never_rewritten_or_treated_as_operators(term):
    literal = f'"{term}"[All Fields]'
    submitted = f'(({literal})) AND ({RANGE}[crdt])'
    accepted = f'{literal} AND {RANGE}[Date - Create]'
    assert internal_create_date_equivalent(submitted, accepted)
    assert not internal_create_date_equivalent(submitted, accepted.replace(term, term + 'x'))


def test_or_clause_grouping_preserves_order_duplicates_and_date_scope():
    terms = '"ECMO"[All Fields] OR "shock"[All Fields] OR "ECMO"[All Fields]'
    submitted = f'(({terms})) AND ({RANGE}[crdt])'
    accepted = f'({terms}) AND {RANGE}[Date - Create]'
    assert internal_create_date_equivalent(submitted, accepted)
    regrouped = ('("ECMO"[All Fields] OR ("shock"[All Fields] OR '
                 f'"ECMO"[All Fields])) AND {RANGE}[Date - Create]')
    assert internal_create_date_equivalent(submitted, regrouped)
    assert not internal_create_date_equivalent(submitted, ACCEPTED)  # Dropped terms.
    reordered = accepted.replace('"ECMO"[All Fields] OR "shock"[All Fields]',
                                '"shock"[All Fields] OR "ECMO"[All Fields]', 1)
    assert not internal_create_date_equivalent(submitted, reordered)
    ungrouped = f'{terms} AND {RANGE}[Date - Create]'
    assert not internal_create_date_equivalent(submitted, ungrouped)


@pytest.mark.parametrize('bad', [
    f'{TERM} OR {RANGE}[Date - Create]',
    f'{TERM} NOT {RANGE}[Date - Create]',
    f'{TERM} AND {RANGE}[Date - Create] AND "humans"[All Fields]',
    f'{TERM} AND {RANGE}[Date - Create] OR "shock"[All Fields]',
    f'{TERM} AND ({RANGE}[Date - Create] OR "shock"[All Fields])',
    f'({TERM} AND "shock"[All Fields]) AND {RANGE}[Date - Create]',
    f'("shock"[All Fields] OR {TERM} AND {RANGE}[Date - Create])',
    f'"ECMO"[MeSH Terms] AND {RANGE}[Date - Create]',
    f'"ECMO"[Title/Abstract] AND {RANGE}[Date - Create]',
    f'"ecmo"[All Fields] AND {RANGE}[Date - Create]',
    f'"ECMO "[All Fields] AND {RANGE}[Date - Create]',
    f'" ECMO"[All Fields] AND {RANGE}[Date - Create]',
    f'"ECMO*"[All Fields] AND {RANGE}[Date - Create]',
    f'{TERM} AND {RANGE}[Date - Publication]',
    f'{TERM} AND {RANGE}[edat]',
    f'{TERM} AND {RANGE}[Create Date]',  # Not the observed canonical alias.
    f'{TERM} AND 1900/01/02:2026/11/01[Date - Create]',
    f'{TERM} AND 1900/01/01:2026/11/02[Date - Create]',
    f'{TERM} AND 1900/01/01:2026/11/01[Date - Create',
    f'{TERM} AND 1900/01/01:2026/11/01[Date - Create])',
    f'({TERM}) AND (({RANGE}[Date - Create])',
    f'{TERM} AND ({RANGE}[Date - Create])garbage',
    f'({TERM} OR) AND {RANGE}[Date - Create]',
    f'({TERM} "shock"[All Fields]) AND {RANGE}[Date - Create]',
    f'() AND {RANGE}[Date - Create]',
    f'{TERM} AND ()',
    f'{RANGE}[Date - Create] AND {TERM}',
    f'{TERM}\nAND {RANGE}[Date - Create]',
    f'{TERM}\x00 AND {RANGE}[Date - Create]',
    None, 1, '', '()',
])
def test_changed_or_malformed_expression_fails_closed(bad):
    assert not internal_create_date_equivalent(SUBMITTED, bad)


@pytest.mark.parametrize('bad_range', [
    '1900/02/29:2026/11/01', '2026/11/02:2026/11/01',
    '0000/01/01:2026/11/01', '2026/13/01:2026/14/01',
    '1900/1/1:2026/11/1',
])
def test_even_identical_invalid_intervals_do_not_pass(bad_range):
    query = f'({TERM}) AND ({bad_range}[crdt])'
    assert not internal_create_date_equivalent(query, query)


def test_alias_is_only_allowed_on_response_not_generator_side():
    assert not internal_create_date_equivalent(ACCEPTED, ACCEPTED)
    assert not internal_create_date_equivalent(TERM, TERM)


def test_deep_balanced_wrappers_are_iterative_not_recursion_limited():
    wrapped = '(' * 5000 + ACCEPTED + ')' * 5000
    assert internal_create_date_equivalent(SUBMITTED, wrapped)
    assert not internal_create_date_equivalent(SUBMITTED, wrapped[:-1])


def test_non_date_literal_field_alias_text_is_not_globally_substituted():
    submitted = f'("x [crdt]"[All Fields]) AND ({RANGE}[crdt])'
    accepted = f'"x [Date - Create]"[All Fields] AND {RANGE}[Date - Create]'
    assert not internal_create_date_equivalent(submitted, accepted)
