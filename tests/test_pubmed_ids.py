"""P1-04a ESearch ID paging fixtures: real transport contract, no live API."""

from __future__ import annotations

from urllib.error import HTTPError
from urllib.parse import parse_qs
import json

import pytest

from research_y.pubmed_ids import (
    PubMedIdentifierPage, parse_identifier_page, retrieve_bounded_identifiers,
)
from research_y.pubmed_probe import PubMedESearchProbeClient, PubMedProbeError

QUERY = '("right ventricle"[All Fields] OR "ECMO"[All Fields])'
UTC = "2026-10-24T18:00:00+00:00"


def _result(*, count: int = 5, offset: int = 0, ids=None,
            translation=QUERY, **kwargs):
    data = {
        "count": str(count), "retstart": str(offset),
        "retmax": str(len(ids)) if ids is not None else "0",
        "idlist": list(ids) if ids is not None else [],
        "querytranslation": translation,
        "warninglist": {"outputmessages": [], "quotedphrasesnotfound": []},
        "errorlist": {"phrasesnotfound": [], "fieldsnotfound": []},
    }
    data.update(kwargs)
    return json.dumps({"esearchresult": data}).encode()


def _provider(pmid_count=5, *, overrides=None, output=None):
    all_ids = tuple(str(100000 + i) for i in range(pmid_count))
    submitted = []
    overrides = overrides or {}

    def transport(req, timeout):
        args = {k: v[0] for k, v in parse_qs(req.data.decode()).items()}
        submitted.append(args)
        start = int(args.get("retstart", "0"))
        maxreturn = int(args["retmax"])
        if maxreturn == 0:
            return _result(count=pmid_count)
        if start in overrides:
            return overrides[start]
        return _result(count=pmid_count, offset=start,
                       ids=all_ids[start:start+maxreturn])

    ticks = [1.0]
    def clock():
        return ticks[0]
    def sleep(dt):
        ticks[0] += dt

    client = PubMedESearchProbeClient(
        email="synthetic@example.org", api_key="SYNTHETIC-DO-NOT-SHARE",
        transport=transport, clock=clock, sleep=sleep,
    )
    return client, all_ids, submitted


def test_three_real_pages_reconcile_ids_but_never_full_retrieval():
    client, expected, requests = _provider(5)
    verified = []
    result = retrieve_bounded_identifiers(client, QUERY, page_size=2,
                                          on_verified_page=verified.append)
    assert result.status == "identifiers_reconciled_metadata_pending"
    assert result.identifiers_reconciled
    assert result.source_retrieval_verified is False
    assert result.reported_matches == 5
    assert result.pmids == expected
    assert len(result.pages) == len(verified) == 3
    assert [p.retstart for p in verified] == [0, 2, 4]
    assert [len(p.pmids) for p in verified] == [2, 2, 1]
    assert [r["retmax"] for r in requests] == ["0", "2", "2", "1"]
    assert [r.get("retstart", "0") for r in requests] == ["0", "0", "2", "4"]
    assert all(req["db"] == "pubmed" and req["term"] == QUERY for req in requests)
    assert all(len(p.response_sha256) == 64 for p in verified)
    assert "SYNTHETIC-DO-NOT-SHARE" not in repr(result)


def test_true_zero_requires_only_count_request():
    client, expected, requests = _provider(0)
    result = retrieve_bounded_identifiers(client, QUERY)
    assert result.identifiers_reconciled
    assert result.pmids == expected == ()
    assert result.reported_matches == 0
    assert not result.source_retrieval_verified
    assert len(requests) == 1


def test_count_exceeding_safe_window_never_reads_partial_first_ten_thousand():
    client, _, requests = _provider(9001)
    result = retrieve_bounded_identifiers(client, QUERY)
    assert result.status == "partition_required"
    assert result.reported_matches == 9001
    assert result.pmids == ()
    assert len(requests) == 1


def test_custom_smaller_ceiling_requires_partition_and_never_truncates():
    client, _, requests = _provider(10)
    result = retrieve_bounded_identifiers(client, QUERY, max_records=9)
    assert result.status == "partition_required"
    assert len(requests) == 1


def test_review_required_on_initial_translation_refuses_pages():
    client, _, requests = _provider(3)
    original=client._transport
    def review_first(req, timeout):
        if parse_qs(req.data.decode())["retmax"] == ["0"]:
            return _result(count=3, translation='("a"[All Fields] AND "b"[All Fields])')
        return original(req, timeout)
    client._transport = review_first
    result = retrieve_bounded_identifiers(client, QUERY)
    assert result.status == "query_review_required"
    assert len(requests) == 0
    assert result.pmids == ()


def test_provider_count_drift_retains_only_verified_preceding_page():
    client, ids, _ = _provider(5, overrides={2: _result(count=6, offset=2, ids=["100002", "100003"])})
    result = retrieve_bounded_identifiers(client, QUERY, page_size=2)
    assert result.status == "incomplete"
    assert result.pmids == ids[:2]
    assert len(result.pages) == 1
    assert "changed" in result.errors[0]


def test_missing_second_page_is_incomplete_not_silent_success():
    client, ids, _ = _provider(4, overrides={2:_result(count=4, offset=2, ids=[])})
    result = retrieve_bounded_identifiers(client, QUERY, page_size=2)
    assert result.status == "incomplete"
    assert result.pmids == ids[:2]
    assert "shorter" in result.errors[0]


def test_repeated_pmid_across_pages_is_not_counted_as_distinct():
    client, ids, _ = _provider(4, overrides={2:_result(count=4, offset=2, ids=["100001", "100003"])})
    result = retrieve_bounded_identifiers(client, QUERY, page_size=2)
    assert result.status == "incomplete"
    assert result.pmids == ids[:2]
    assert "overlapping" in result.errors[0]


def test_provider_translation_change_in_later_page_never_assimilated():
    client, ids, _ = _provider(4, overrides={2:_result(count=4, offset=2, ids=["100002", "100003"],
        translation='("bad"[MeSH Terms])')})
    report=retrieve_bounded_identifiers(client, QUERY, page_size=2)
    assert report.status=="query_review_required"
    assert report.pmids==ids[:2]
    assert report.source_retrieval_verified is False


def test_retryable_http_error_keeps_first_page_results():
    client, ids, _=_provider(4)
    underlying=client._transport
    def fail_at_two(req, timeout):
        start=int(parse_qs(req.data.decode()).get("retstart", ["0"])[0])
        if start == 2:
            raise HTTPError(req.full_url, 503, "Service unavailable", {}, None)
        return underlying(req,timeout)
    client._transport=fail_at_two
    report=retrieve_bounded_identifiers(client,QUERY,page_size=2)
    assert report.status=="incomplete"
    assert report.pmids==ids[:2]
    assert len(report.pages)==1
    assert "503" in report.errors[0]


def test_failed_checkpoint_preserves_only_previously_saved_pages():
    client, ids, _=_provider(4)
    committed=[]
    def store(page):
        if page.retstart == 2:
            raise RuntimeError("Sensitive path / secret")
        committed.append(page)
    report=retrieve_bounded_identifiers(client,QUERY,page_size=2,on_verified_page=store)
    assert report.status=="incomplete"
    assert report.pmids==ids[:2]
    assert len(committed)==1
    assert "Sensitive" not in repr(report)
    assert "checkpoint failed" in report.errors[0]


def test_repeated_pmid_within_single_page_is_rejected():
    with pytest.raises(PubMedProbeError, match="repeated"):
        parse_identifier_page(_result(count=2,offset=0,ids=["123","123"]),
                              exact_query=QUERY,retstart=0,retmax=2,retrieved_at_utc=UTC)


@pytest.mark.parametrize("bad_id", ["", "0", "-10", "123a", 44, "0123", " 123", "12.5"])
def test_invalid_pmids_refused(bad_id):
    with pytest.raises(PubMedProbeError, match="PMID"):
        parse_identifier_page(_result(count=1,offset=0,ids=[bad_id]),
                              exact_query=QUERY,retstart=0,retmax=1,retrieved_at_utc=UTC)


def test_wrong_page_start_is_rejected():
    with pytest.raises(PubMedProbeError, match="boundaries"):
        parse_identifier_page(_result(count=5,offset=3,ids=["123"]),
                              exact_query=QUERY,retstart=2,retmax=1,retrieved_at_utc=UTC)


def test_bad_id_list_and_invalid_reported_count_fail_closed():
    with pytest.raises(PubMedProbeError, match="ID list"):
        parse_identifier_page(_result(count=3,offset=0,ids=None,idlist=None),
                              exact_query=QUERY,retstart=0,retmax=3,retrieved_at_utc=UTC)
    with pytest.raises(PubMedProbeError, match="reported count"):
        parse_identifier_page(_result(count=-2,offset=0,ids=["123"]),
                              exact_query=QUERY,retstart=0,retmax=1,retrieved_at_utc=UTC)


def test_page_warnings_remain_visible_as_review_required():
    response=_result(count=1,offset=0,ids=["101"],
                     warninglist={"quotedphrasesnotfound":["rare phrase"]})
    page=parse_identifier_page(response, exact_query=QUERY,
                               retstart=0,retmax=1,retrieved_at_utc=UTC)
    assert page.review_required
    assert len(page.warnings)==1
    assert "rare phrase" in page.warnings[0]


@pytest.mark.parametrize("start,size", [(-1,10),(0,1001),(9990,20),(1,0),(False,2),(5,True)])
def test_direct_client_enforces_page_bounds_before_network(start,size):
    client, _, requests=_provider(2)
    with pytest.raises(ValueError):
        client.fetch_esearch_page(QUERY,retstart=start,retmax=size)
    assert requests == []


def test_direct_client_reuses_post_and_rate_limit_for_counts_and_pages():
    client,ids,requests=_provider(2)
    assert client.probe(QUERY).reported_matches==2
    raw=client.fetch_esearch_page(QUERY,retstart=0,retmax=2)
    page=parse_identifier_page(raw,exact_query=QUERY,retstart=0,retmax=2,
                               retrieved_at_utc=UTC)
    assert page.pmids==ids
    assert [r["retmax"] for r in requests]==["0","2"]


@pytest.mark.parametrize("size", [0, 1001, True, 1.5])
def test_invalid_page_size_rejected(size):
    client,_,request=_provider(2)
    with pytest.raises(ValueError,match="page_size"):
        retrieve_bounded_identifiers(client,QUERY,page_size=size)
    assert request==[]


def test_original_payload_digest_is_stable_and_not_payload_echo():
    payload=_result(count=1,offset=0,ids=["123"])
    page=parse_identifier_page(payload,exact_query=QUERY,retstart=0,
                               retmax=1,retrieved_at_utc=UTC)
    assert len(page.response_sha256)==64
    assert "123" not in page.response_sha256


@pytest.mark.parametrize("payload", [
    b"", b"not-json", b"\xff", b"[]", b"{}",
    json.dumps({"error": "synthetic failure"}).encode(),
    json.dumps({"esearchresult":{"ERROR":"synthetic failure"}}).encode(),
])
def test_invalid_provider_payloads_cannot_be_considered_ids(payload):
    with pytest.raises(PubMedProbeError):
        parse_identifier_page(payload,exact_query=QUERY,retstart=0,retmax=2,
                              retrieved_at_utc=UTC)


def test_oversized_provider_page_refused():
    with pytest.raises(PubMedProbeError,match="oversized"):
        parse_identifier_page(b"a"*(512*1024+1), exact_query=QUERY,retstart=0,
                              retmax=1,retrieved_at_utc=UTC)


@pytest.mark.parametrize("change", [
    {"querytranslation":None}, {"retstart":-1}, {"retstart":None},
    {"retmax":"oops"}, {"retmax":"20"}, {"warninglist":"not a list"},
    {"errorlist":["unexpected shape"]},
])
def test_malformed_provider_page_fields_fail_closed(change):
    with pytest.raises(PubMedProbeError):
        parse_identifier_page(_result(count=2,offset=0,ids=["101", "102"], **change),
                              exact_query=QUERY,retstart=0,retmax=2,
                              retrieved_at_utc=UTC)


def test_invalid_page_type_and_invalid_boundaries_are_rejected():
    with pytest.raises(PubMedProbeError, match="invalid identifier"):
        parse_identifier_page("a string",exact_query=QUERY,retstart=0,
                              retmax=1,retrieved_at_utc=UTC)
    with pytest.raises(ValueError, match="nonnegative"):
        parse_identifier_page(_result(count=1,offset=0,ids=["123"]),
                              exact_query=QUERY,retstart=-1,retmax=1,
                              retrieved_at_utc=UTC)
    with pytest.raises(ValueError, match="window"):
        parse_identifier_page(_result(count=1,offset=0,ids=["123"]),
                              exact_query=QUERY,retstart=9999,retmax=2,
                              retrieved_at_utc=UTC)


def test_source_sized_id_page_is_rejected_before_any_checkpoint():
    client,ids,_ = _provider(2, overrides={0:_result(count=2,offset=0,ids=["100000", "100001", "100002"],retmax="2")})
    report = retrieve_bounded_identifiers(client,QUERY,page_size=2)
    assert report.status=="incomplete"
    assert report.pmids==()
    assert "exceeded" in report.errors[0]


def test_bad_pacing_config_does_not_start_provider_calls():
    client,_,requests=_provider(2)
    with pytest.raises(ValueError, match="max_records"):
        retrieve_bounded_identifiers(client,QUERY,max_records=9001)
    with pytest.raises(TypeError, match="callable"):
        retrieve_bounded_identifiers(client,QUERY,on_verified_page=object())
    assert requests==[]


def test_network_count_error_is_incomplete_not_fabricated_zero():
    def bad(_req,_timeout):
        raise HTTPError("https://eutils.ncbi.nlm.nih.gov/",429,"rate limited",{},None)
    client=PubMedESearchProbeClient(email="synthetic@example.org",transport=bad)
    report=retrieve_bounded_identifiers(client,QUERY)
    assert report.status=="incomplete"
    assert report.reported_matches is None
    assert report.pmids==()
    assert "429" in report.errors[0]


def test_checkpoint_raising_provider_exception_cannot_leak_private_path():
    client,ids,_ = _provider(4)
    def persist(page):
        if page.retstart == 2:
            raise PubMedProbeError("SECRET private-storage /users/home/db.sqlite3")
    result=retrieve_bounded_identifiers(client,QUERY,page_size=2,
                                        on_verified_page=persist)
    assert result.status=="incomplete"
    assert result.pmids==ids[:2]
    assert len(result.pages)==1
    assert "SECRET" not in repr(result)
    assert "checkpoint failed" in result.errors[0]


def test_oversized_decimal_pmid_after_valid_page_is_incomplete_not_exception():
    bad_id="1"*5000
    client,ids,_ = _provider(4,overrides={2:_result(count=4,offset=2,
                        ids=[bad_id,"100003"])})
    result=retrieve_bounded_identifiers(client,QUERY,page_size=2)
    assert result.status=="incomplete"
    assert result.pmids==ids[:2]
    assert len(result.pages)==1
    assert "invalid PMID" in result.errors[0]


def test_oversized_source_count_field_fails_as_provider_error():
    payload=_result(count="1"*5000,offset=0,ids=["123"])
    with pytest.raises(PubMedProbeError,match="reported count"):
        parse_identifier_page(payload,exact_query=QUERY,retstart=0,
                              retmax=1,retrieved_at_utc=UTC)
