"""Deterministic query compilation, field syntax and broad-OR union checks."""

from __future__ import annotations

from copy import deepcopy

import pytest

from research_y.query_compiler import (
    QueryCompilationError, QuerySizeError, compile_both, compile_source,
)


def _term(text, *, enabled=True, approved=True, origin="researcher", rationale=""):
    return {"text": text, "enabled": enabled, "approved": approved,
            "origin": origin, "rationale": rationale}


def _snapshot():
    return {
        "format_version": 1,
        "theme": "Right heart failure",
        "logic": "OR",
        "approved_by": "Researcher",
        "groups": [
            {"group_id": "g1", "label": "Right ventricle", "group_order": 0,
             "terms": [_term("right ventricle"), _term("right-ventricle", origin="deterministic"),
                       _term("unused", enabled=False)]},
            {"group_id": "g2", "label": "Membrane oxygenation", "group_order": 1,
             "terms": [_term("ECMO"), _term("venovenous", origin="ai", rationale="Approved synonym")]},
        ],
    }


def test_pubmed_all_fields_per_term_and_union_is_only_or():
    result = compile_source(_snapshot(), "pubmed")
    assert result.groups[0].exact_group_query == (
        '("right ventricle"[All Fields] OR "right-ventricle"[All Fields])'
    )
    assert result.groups[1].exact_group_query == (
        '("ECMO"[All Fields] OR "venovenous"[All Fields])'
    )
    assert result.logical_union_query == (
        '(' + result.groups[0].exact_group_query + ' OR ' + result.groups[1].exact_group_query + ')'
    )
    assert result.groups[0].active_term_count == 2
    assert result.groups[0].approved_term_count == 3
    assert "[MeSH" not in result.logical_union_query
    assert " AND " not in result.logical_union_query
    assert " NOT " not in result.logical_union_query
    assert result.executed is False
    assert result.reported_matches is None
    assert "full text" in result.source_coverage
    assert "translation" in result.source_coverage


def test_wos_topic_coverage_not_all_fields():
    result = compile_source(_snapshot(), "wos")
    assert result.groups[0].exact_group_query == 'TS=("right ventricle" OR "right-ventricle")'
    assert result.groups[1].exact_group_query == 'TS=("ECMO" OR "venovenous")'
    assert result.logical_union_query == (
        '(TS=("right ventricle" OR "right-ventricle") OR '
        'TS=("ECMO" OR "venovenous"))'
    )
    assert "Topic" in result.source_coverage
    assert "full text" in result.source_coverage
    assert "[All Fields]" not in result.logical_union_query


def test_full_union_and_groups_have_same_source_term_multiset():
    snap = _snapshot()
    for source in ("pubmed", "wos"):
        compiled = compile_source(snap, source)
        for group, entry in zip(snap["groups"], compiled.groups, strict=True):
            expect = [term["text"] for term in group["terms"] if term["enabled"]]
            assert [term for chunk in entry.chunks for term in chunk.atomic_terms] == expect
            assert entry.exact_group_query == entry.chunks[0].exact_query
        assert compiled.logical_union_query.count(' OR ') == 3


def test_configured_source_byte_cap_splits_without_dropping_or_intersecting_terms():
    snap = _snapshot()
    compiled = compile_source(snap, "pubmed", max_query_bytes=55)
    assert sum(len(group.chunks) for group in compiled.groups) > 2
    assert compiled.union_fits_limit is False
    assert all(len(chunk.exact_query.encode()) <= 55 for group in compiled.groups for chunk in group.chunks)
    assert [x for g in compiled.groups for ch in g.chunks for x in ch.atomic_terms] == (
        [t['text'] for g in snap['groups'] for t in g['terms'] if t['enabled']]
    )
    assert any("do not sum" in warning for warning in compiled.warnings)
    assert any("not the preview" in warning for warning in compiled.warnings)


def test_configured_limit_is_not_a_fictional_provider_default():
    p, w = compile_both(_snapshot())
    assert p.max_query_bytes is None and w.max_query_bytes is None
    assert p.union_fits_limit and w.union_fits_limit
    assert len(p.snapshot_sha256) == 64
    assert p.snapshot_sha256 == w.snapshot_sha256


def test_single_literal_over_budget_fails_rather_than_silently_truncating():
    with pytest.raises(QuerySizeError, match="never truncate"):
        compile_source(_snapshot(), "pubmed", max_query_bytes=10)


@pytest.mark.parametrize("source", ["pubmed", "wos"])
def test_disabled_group_retained_as_unsearched_not_zero_hits(source):
    snap = _snapshot()
    snap["groups"][0]["terms"] = [_term("disabled", enabled=False)]
    out = compile_source(snap, source)
    first = out.groups[0]
    assert first.exact_group_query is None and first.chunks == ()
    assert first.active_term_count == 0
    assert len(out.groups) == 2
    assert out.reported_matches is None
    assert any("g1 has no active terms" in w for w in out.warnings)


def test_all_terms_disabled_refuses_to_invent_unrestricted_query_or_zero_hits():
    snap = _snapshot()
    for group in snap["groups"]:
        for term in group["terms"]:
            term["enabled"] = False
    with pytest.raises(QueryCompilationError, match="No active"):
        compile_source(snap, "pubmed")


@pytest.mark.parametrize("literal", ['"heart"', 'a\\b', 'vent*', 'colo?r', 'peso$', 'quoted\nphrase'])
def test_unapproved_literal_operator_syntax_rejected_for_manual_edit(literal):
    snap = _snapshot()
    snap["groups"][0]["terms"][0]["text"] = literal
    with pytest.raises(QueryCompilationError, match="unreviewed|unsupported|control"):
        compile_source(snap, "pubmed")


@pytest.mark.parametrize("invalid", ["AND", "NOT", "anything", None])
def test_logic_must_be_or_only(invalid):
    snap = _snapshot()
    snap["logic"] = invalid
    with pytest.raises(QueryCompilationError, match="OR-only"):
        compile_source(snap, "pubmed")


def test_boolean_tokens_inside_a_single_literal_are_quoted_not_operators():
    snap = _snapshot()
    snap["groups"][0]["terms"] = [_term("research AND education")]
    p, w = compile_both(snap)
    assert '"research AND education"[All Fields]' in p.logical_union_query
    assert '"research AND education"' in w.logical_union_query


def test_only_explicitly_approved_terms_accepted():
    snap = _snapshot()
    snap["groups"][0]["terms"][0]["approved"] = False
    with pytest.raises(QueryCompilationError, match="not approved"):
        compile_source(snap, "wos")


def test_ai_term_without_rationale_refused():
    snap = _snapshot()
    snap["groups"][1]["terms"][1]["rationale"] = ""
    with pytest.raises(QueryCompilationError, match="AI rationale"):
        compile_source(snap, "pubmed")


@pytest.mark.parametrize("bad", [0, -1, 3.14, True, "500"])
def test_size_cap_must_be_an_explicit_positive_integer(bad):
    with pytest.raises(QueryCompilationError, match="positive integer"):
        compile_source(_snapshot(), "pubmed", max_query_bytes=bad)


@pytest.mark.parametrize("source", ["crossref", "medline", "all-fields", ""])
def test_unimplemented_source_compiler_rejected(source):
    with pytest.raises(QueryCompilationError, match="Unsupported source"):
        compile_source(_snapshot(), source)


@pytest.mark.parametrize("field", ["group_id", "group_order", "terms"])
def test_malformed_approved_snapshot_refused(field):
    snap = _snapshot()
    snap["groups"][0][field] = None
    with pytest.raises(QueryCompilationError):
        compile_source(snap, "pubmed")


def test_duplicate_groups_refused():
    snap = _snapshot()
    snap["groups"][1]["group_id"] = "g1"
    with pytest.raises(QueryCompilationError, match="duplicate"):
        compile_source(snap, "wos")


def test_source_plan_does_not_mutate_strategy_snapshot():
    data = _snapshot()
    before = deepcopy(data)
    compile_both(data, pubmed_max_query_bytes=60, wos_max_query_bytes=40)
    assert data == before


def test_repeatability_and_distinguishable_snapshot_digest():
    a = _snapshot()
    b = deepcopy(a)
    p1 = compile_source(a, "pubmed")
    p2 = compile_source(b, "pubmed")
    assert p1 == p2
    b["groups"][0]["terms"][0]["text"] = "changed"
    assert compile_source(b, "pubmed").snapshot_sha256 != p1.snapshot_sha256


def test_unicode_compiler_size_tracks_encoded_bytes():
    snap = _snapshot()
    snap["groups"][0]["terms"] = [_term("β-blocker")]
    result = compile_source(snap, "wos", max_query_bytes=40)
    assert result.groups[0].chunks[0].atomic_terms == ("β-blocker",)
    assert len(result.groups[0].chunks[0].exact_query.encode('utf-8')) <= 40


def test_duplicate_terms_across_groups_are_not_silently_removed():
    snap = _snapshot()
    snap['groups'][1]['terms'].append(_term('right ventricle'))
    result = compile_source(snap, 'pubmed')
    assert result.logical_union_query.count('"right ventricle"[All Fields]') == 2
