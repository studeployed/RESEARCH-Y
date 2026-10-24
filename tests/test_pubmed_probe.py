"""Offline ESearch count-only source acceptance tests; no network calls."""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

import pytest

from research_y.pubmed_probe import (
    ESEARCH_URL, MAX_RESPONSE_BYTES, PubMedESearchProbeClient, PubMedProbeError,
    parse_esearch_count, probe_compiled_group,
)
from research_y.query_compiler import CompiledGroup, CompiledSource, QueryChunk

Q = '("right ventricle"[All Fields] OR "ECMO"[All Fields])'
T = '2026-10-24T13:00:00+00:00'


def response(query=Q, count="42", **kwargs):
    data = {"count": count, "retmax": "0", "retstart": "0", "idlist": [],
            "querytranslation": query, "errorlist": {"phrasesnotfound": [], "fieldsnotfound": []},
            "warninglist": {"outputmessages": [], "quotedphrasesnotfound": []}}
    data.update(kwargs)
    return json.dumps({"esearchresult": data}).encode()


def test_exact_query_no_warnings_count_only_is_not_verified_retrieval():
    result = parse_esearch_count(response(), Q, checked_at_utc=T)
    assert result.exact_query == Q
    assert result.accepted_translation == Q
    assert result.reported_matches == 42
    assert result.checked_at_utc == T
    assert result.review_required is False
    assert result.translation_matches_submitted
    assert result.retrieved_records == 0
    assert result.retrieval_verified is False


def test_genuine_zero_distinguished_from_provider_error():
    result = parse_esearch_count(response(count="0"), Q, checked_at_utc=T)
    assert result.reported_matches == 0
    with pytest.raises(PubMedProbeError, match="valid count"):
        parse_esearch_count(response(count=None), Q, checked_at_utc=T)


@pytest.mark.parametrize("count", [-1, "-1", True, 1.5, "five", None])
def test_missing_or_invalid_counts_never_silently_become_zero(count):
    with pytest.raises(PubMedProbeError, match="valid count"):
        parse_esearch_count(response(count=count), Q, checked_at_utc=T)


def test_provider_error_inside_http_200_is_not_a_valid_result():
    with pytest.raises(PubMedProbeError, match="valid search result"):
        parse_esearch_count(b'{"esearchresult":{"ERROR":"invalid query"}}', Q, checked_at_utc=T)
    with pytest.raises(PubMedProbeError, match="provider error"):
        parse_esearch_count(b'{"error":"Rate limit exceeded"}', Q, checked_at_utc=T)


@pytest.mark.parametrize("bad", [b"", b"not json", b"\xff", b"{}", b"[]"])
def test_corrupt_or_missing_response_fails_closed(bad):
    with pytest.raises(PubMedProbeError):
        parse_esearch_count(bad, Q, checked_at_utc=T)


def test_invalid_or_missing_accepted_translation_fails():
    with pytest.raises(PubMedProbeError, match="omitted"):
        parse_esearch_count(response(query=""), Q, checked_at_utc=T)
    with pytest.raises(PubMedProbeError, match="omitted"):
        parse_esearch_count(response(query=None), Q, checked_at_utc=T)


def test_unexpected_returned_ids_do_not_count_as_count_only():
    with pytest.raises(PubMedProbeError, match="record IDs"):
        parse_esearch_count(response(idlist=["123"]), Q, checked_at_utc=T)
    with pytest.raises(PubMedProbeError, match="retmax=0"):
        parse_esearch_count(response(retmax="25"), Q, checked_at_utc=T)


def test_warnings_always_require_manual_review_without_erasing_count():
    result = parse_esearch_count(
        response(warninglist={"quotedphrasesnotfound": ["right ventricle"],
                              "outputmessages": ["No items found."]}), Q, checked_at_utc=T)
    assert result.reported_matches == 42
    assert result.review_required
    assert any("quotedphrasesnotfound" in w for w in result.warnings)
    assert any("warnings/errors" in reason for reason in result.review_reasons)


def test_source_errorlist_phrase_index_problem_requires_review():
    result = parse_esearch_count(response(errorlist={"phrasesnotfound": ["right ventricle"]}), Q, checked_at_utc=T)
    assert result.review_required
    assert result.reported_matches == 42


def test_silent_translation_change_never_claimed_identical():
    changed = '("right"[All Fields] AND "ventricle"[All Fields])'
    result = parse_esearch_count(response(query=changed), Q, checked_at_utc=T)
    assert not result.translation_matches_submitted
    assert result.review_required
    assert any("AND/NOT" in x for x in result.review_reasons)


def test_unexpected_mesh_mapping_is_explicitly_flagged():
    mapping = '"Heart Failure"[MeSH Terms] OR "right ventricle"[All Fields]'
    result = parse_esearch_count(response(query=mapping), Q, checked_at_utc=T)
    assert result.review_required
    assert any("Medical Subject Headings" in x for x in result.review_reasons)


def test_and_inside_quoted_literal_is_not_treated_as_boolean_operator():
    q = '("research AND education"[All Fields])'
    result = parse_esearch_count(response(query=q), q, checked_at_utc=T)
    assert not any("AND/NOT" in x for x in result.review_reasons)


def test_bad_provider_warning_shape_fails_instead_of_discarding():
    with pytest.raises(PubMedProbeError, match="invalid warninglist"):
        parse_esearch_count(response(warninglist="silent data"), Q, checked_at_utc=T)


def test_oversized_payload_is_not_processed():
    with pytest.raises(PubMedProbeError, match="oversized"):
        parse_esearch_count(b"x" * (MAX_RESPONSE_BYTES + 1), Q, checked_at_utc=T)


def test_request_is_fixed_https_post_with_tool_email_and_retmax_zero():
    seen = []
    def transport(request, timeout):
        seen.append((request, timeout))
        return response()
    client = PubMedESearchProbeClient(email="tester@example.org", tool="ResearchY", transport=transport)
    result = client.probe(Q)
    request, timeout = seen[0]
    assert request.full_url == ESEARCH_URL
    assert urlsplit(request.full_url).query == ""
    assert request.get_method() == "POST"
    params = parse_qs(request.data.decode())
    assert params["term"] == [Q]
    assert params["db"] == ["pubmed"]
    assert params["retmode"] == ["json"]
    assert params["retmax"] == ["0"]
    assert params["tool"] == ["ResearchY"]
    assert params["email"] == ["tester@example.org"]
    assert "api_key" not in params
    assert timeout == 20
    assert result.reported_matches == 42


def test_key_remains_in_body_only_and_is_never_returned():
    secret = "AN-EXAMPLE-PRIVATE-KEY"
    def transport(request, timeout):
        assert urlsplit(request.full_url).query == ""
        params = parse_qs(request.data.decode())
        assert params["api_key"] == [secret]
        return response()
    client = PubMedESearchProbeClient(email="tester@example.org", api_key=secret, transport=transport)
    assert secret not in repr(client.probe(Q))


def test_http_429_retryability_and_no_secret_leak():
    secret = "SENSITIVE_TEST_KEY"
    def denied(request, timeout):
        raise HTTPError(request.full_url, 429, "Too many requests", {}, None)
    client = PubMedESearchProbeClient(email="tester@example.org", api_key=secret, transport=denied)
    with pytest.raises(PubMedProbeError) as exc:
        client.probe(Q)
    assert exc.value.http_status == 429
    assert exc.value.retryable
    assert secret not in str(exc.value)


def test_provider_transport_errors_dont_invent_counts_or_leak_details():
    def offline(req, timeout):
        raise URLError("PRIVATE-CONNECTION-PARAMETERS")
    client = PubMedESearchProbeClient(email="tester@example.org", transport=offline)
    with pytest.raises(PubMedProbeError, match="network error") as err:
        client.probe(Q)
    assert err.value.retryable
    assert "PRIVATE-CONNECTION-PARAMETERS" not in str(err.value)


@pytest.mark.parametrize("email", ["", "missing-at", "a@b", "a b@example.com"])
def test_client_requires_ncbI_contact_email(email):
    with pytest.raises(ValueError, match="contact email"):
        PubMedESearchProbeClient(email=email)


def test_client_rejects_tool_spaces_and_nonpositive_timeouts():
    with pytest.raises(ValueError, match="tool identifier"):
        PubMedESearchProbeClient(email="tester@example.org", tool="Research Y")
    with pytest.raises(ValueError, match="timeout"):
        PubMedESearchProbeClient(email="tester@example.org", timeout=0)


def test_multiple_eseach_calls_rate_paced_below_3_per_second():
    times = [10.0]
    pauses = []
    def clock():
        return times[0]
    def sleep(seconds):
        pauses.append(seconds)
        times[0] += seconds
    client = PubMedESearchProbeClient(email="tester@example.org", transport=lambda r, t: response(), clock=clock, sleep=sleep)
    client.probe(Q)
    client.probe(Q)
    client.probe(Q)
    assert pauses == pytest.approx([0.4, 0.4])


def make_group(source="pubmed", queries=(Q,), *, group_id="g1"):
    chunks = tuple(QueryChunk(i + 1, query, (f"term-{i}",)) for i, query in enumerate(queries))
    group = CompiledGroup(group_id, "Study", len(chunks), len(chunks), Q if chunks else None, chunks)
    return CompiledSource(source, "f" * 64, "Field coverage", (group,), Q, True, None, ())


def test_single_unpartitioned_group_exposes_count_without_verified_completion():
    client = PubMedESearchProbeClient(email="tester@example.org", transport=lambda req, timeout: response())
    group = probe_compiled_group(make_group(), "g1", client)
    assert group.reported_group_matches == 42
    assert group.status == "count_reported_not_retrieved"
    assert group.retrieval_verified is False


def test_partitioned_group_never_sums_overlapping_counts():
    chunks = ('("right ventricle"[All Fields])', '("ECMO"[All Fields])')
    def count_fixture(request, timeout):
        query = parse_qs(request.data.decode())["term"][0]
        return response(query=query, count="70")
    class Clock:
        value = 12.0
        def __call__(self):
            return self.value
    times = Clock()
    client = PubMedESearchProbeClient(email="tester@example.org", transport=count_fixture,
                                    clock=times, sleep=lambda dt: setattr(times, "value", times.value + dt))
    report = probe_compiled_group(make_group(queries=chunks), "g1", client)
    assert len(report.chunk_results) == 2
    assert [r.reported_matches for r in report.chunk_results] == [70, 70]
    assert report.reported_group_matches is None
    assert report.status == "partitioned_requires_identifier_union"
    assert report.retrieval_verified is False


def test_disabled_group_returns_explicit_unsearched_status_without_request():
    class FailIfCalled:
        def probe(self, query):
            raise AssertionError("disabled group must not send any requests")
    report = probe_compiled_group(make_group(queries=()), "g1", FailIfCalled())
    assert report.status == "unsearched_disabled_group"
    assert report.reported_group_matches is None


def test_wos_compiled_queries_cannot_be_sent_to_pubmed():
    client = PubMedESearchProbeClient(email="tester@example.org", transport=lambda req, timeout: response())
    with pytest.raises(ValueError, match="only supports compiled PubMed"):
        probe_compiled_group(make_group(source="wos"), "g1", client)


def test_unknown_group_refused_before_provider_requests():
    client = PubMedESearchProbeClient(email="tester@example.org", transport=lambda req, timeout: response())
    with pytest.raises(KeyError):
        probe_compiled_group(make_group(), "missing", client)


def test_real_approved_snapshot_compiles_and_probes_without_record_retrieval():
    """Exercise the actual approved-strategy compiler and ESearch fixture together."""
    from research_y.query_compiler import compile_source

    frozen = {
        "format_version": 1,
        "theme": "Right ventricular failure",
        "logic": "OR",
        "approved_by": "Researcher",
        "groups": [
            {
                "group_id": "rv",
                "label": "Right ventricular failure",
                "group_order": 0,
                "terms": [
                    {"text": "right ventricle", "origin": "researcher",
                     "approved": True, "rationale": "", "enabled": True},
                    {"text": "ECMO", "origin": "researcher",
                     "approved": True, "rationale": "", "enabled": True},
                ],
            },
        ],
    }
    compiled = compile_source(frozen, "pubmed")
    sent_queries = []
    def fake_esearch(request, timeout):
        query = parse_qs(request.data.decode())["term"][0]
        sent_queries.append(query)
        return response(query=query, count="218")
    client = PubMedESearchProbeClient(
        email="tester@example.org", transport=fake_esearch
    )
    result = probe_compiled_group(compiled, "rv", client)
    assert sent_queries == [
        '("right ventricle"[All Fields] OR "ECMO"[All Fields])'
    ]
    assert result.reported_group_matches == 218
    assert result.status == "count_reported_not_retrieved"
    assert result.retrieval_verified is False
    assert result.chunk_results[0].translation_matches_submitted


def test_actual_compiled_group_flags_provider_phrase_fallback_for_review():
    from research_y.query_compiler import compile_source

    frozen = {
        "format_version": 1,
        "theme": "Phrase safety",
        "logic": "OR",
        "approved_by": "Researcher",
        "groups": [
            {
                "group_id": "phrase",
                "label": "Example",
                "group_order": 0,
                "terms": [
                    {"text": "right ventricle", "origin": "researcher",
                     "approved": True, "rationale": "", "enabled": True}
                ],
            }
        ],
    }
    compiled = compile_source(frozen, "pubmed")
    def fake_esearch(request, timeout):
        return response(
            query='("right"[All Fields] AND "ventricle"[All Fields])',
            warninglist={"quotedphrasesnotfound": ["right ventricle"]},
        )
    client = PubMedESearchProbeClient(
        email="tester@example.org", transport=fake_esearch
    )
    result = probe_compiled_group(compiled, "phrase", client)
    assert result.status == "translation_review_required"
    assert result.chunk_results[0].review_required
    assert result.retrieval_verified is False
