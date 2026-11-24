from copy import deepcopy
from datetime import datetime

from research_y.desktop.search_guidance import saved_search_names


def test_frozen_topics_versions_repeats_and_dates_identify_runs_without_mutating_them():
    first = dict(run_id='a', version_number=1, strategy_theme='RV Failure', created_at_utc='2026-11-23T12:30:00Z')
    repeated = dict(first, run_id='b', created_at_utc='2026-11-24T12:30:00Z')
    revised = dict(first, run_id='c', version_number=2, strategy_theme='Pulmonary hypertension')
    runs = [revised, repeated, first]
    before = deepcopy(runs)
    names = saved_search_names(runs)
    assert names['a'].startswith('RV Failure · version 1 · saved ')
    assert names['b'].startswith('RV Failure · version 1 · repeat 2 · saved ')
    assert names['c'].startswith('Pulmonary hypertension · version 2 · saved ')
    local = datetime.fromisoformat(first['created_at_utc'].replace('Z', '+00:00')).astimezone()
    assert names['a'].endswith(local.strftime('%d %b %Y, %H:%M'))
    assert len(set(names.values())) == 3
    assert saved_search_names(list(reversed(runs))) == names
    assert runs == before


def test_same_time_runs_are_distinct_and_missing_legacy_title_is_explicit():
    row = dict(version_number=4, created_at_utc='2026-11-24T00:00:00Z')
    names = saved_search_names([dict(row, run_id='b'), dict(row, run_id='a')])
    assert names['a'].startswith('Untitled search · version 4 · saved ')
    assert names['b'].startswith('Untitled search · version 4 · repeat 2 · saved ')
