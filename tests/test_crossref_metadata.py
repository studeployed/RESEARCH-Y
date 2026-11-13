from contextlib import closing
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from research_y.crossref_metadata import inspect_enrichment, record_work_response
from research_y.crossref_client import enrich_publication
from research_y.projects import open_project
from research_y.publication_identity import materialise_retrieval, StalePublicationError
from test_publication_identity import store, protected_rows, db_rows

DOI = "10.1234/sample"


def setup_target(store, dois=(DOI,)):
    project, ids = store
    record = {"source":"NCBI PubMed EFetch XML", "record":{"pmid":"1","identifiers":{"doi":list(dois)}}}
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute("UPDATE source_retrievals SET original_metadata_json=? WHERE retrieval_id=?",
                   (json.dumps(record), ids[0]))
    pub = materialise_retrieval(project, ids[0], actor="Test")
    return project, pub.publication_id


def fixture(target, *, status=200, data=None):
    return dict(expected_revision=target["revision"], requested_doi=target["doi"], status_code=status,
                body=json.dumps(data if data is not None else {
                    "status":"ok","message-type":"work","message":{"DOI":DOI,"title":["Reference title"]}
                }).encode(), retrieved_at_utc="2026-11-13T00:00:00Z", actor="Researcher", confirmed=True)


def test_positive_work_response_retains_original_record_and_primary_counts(store):
    p, pub = setup_target(store)
    target = inspect_enrichment(p,pub)["target"]
    assert target["status"] == "ready" and target["request_url"].endswith("10.1234%2Fsample")
    originals = protected_rows(p)
    publications = db_rows(p,"publications")
    args = fixture(target)
    receipt = record_work_response(p,pub,**args)
    assert receipt["fields"] == {"title":["Reference title"]} and "abstract" in receipt["gaps"]
    assert receipt["source_evidence"][0]["path"] == ["record","identifiers","doi"]
    assert receipt["rights_review_required"] and receipt["outcome"] == "metadata_available"
    reopened = open_project(p.root)
    assert record_work_response(reopened,pub,**args) == receipt
    assert inspect_enrichment(reopened,pub) == dict(target=target,current=receipt,prior_receipts=[receipt["event_id"]])
    assert protected_rows(p) == originals and db_rows(p,"publications") == publications


@pytest.mark.parametrize(("dois","reason"), [([], "missing_doi"), ([DOI,"10.1234/other"], "ambiguous_doi")])
def test_no_unambiguous_original_doi_cannot_attach_any_response(store, dois, reason):
    p, pub = setup_target(store,dois)
    view = inspect_enrichment(p,pub)
    assert view["target"]["status"] == reason and view["target"]["request_url"] is None
    with pytest.raises(StalePublicationError):
        record_work_response(p,pub,**fixture(view["target"],status=404))
    assert inspect_enrichment(p,pub)["current"] is None


@pytest.mark.parametrize(("status","outcome"),[(404,"not_found"),(503,"unavailable"),(429,"unavailable")])
def test_missing_and_unavailable_are_explicit_gaps_without_new_search_results(store,status,outcome):
    p,pub = setup_target(store)
    before = protected_rows(p)
    view = inspect_enrichment(p,pub)
    receipt = record_work_response(p,pub,**fixture(view["target"],status=status,data={"private":"error body"}))
    assert receipt["outcome"] == outcome and receipt["fields"] == {} and "title" in receipt["gaps"]
    assert "error body" not in json.dumps(receipt) and protected_rows(p) == before


def test_wrong_doi_fails_atomically(store):
    p,pub = setup_target(store)
    target = inspect_enrichment(p,pub)["target"]
    with pytest.raises(ValueError, match="DOI"):
        record_work_response(p,pub,**fixture(target,data={"status":"ok","message-type":"work",
                            "message":{"DOI":"10.1234/other"}}))
    assert inspect_enrichment(p,pub)["prior_receipts"] == []


def test_polite_lookup_reopen_cache_and_persisted_provider_wait(store):
    p,pub = setup_target(store)
    view = inspect_enrichment(p,pub)["target"]
    clock = [datetime(2026,11,13,tzinfo=timezone.utc)]
    contact = "test@example.org"
    calls = []
    def get(request):
        calls.append(request)
        url = urlsplit(request.full_url)
        assert url.scheme == "https" and url.hostname == "api.crossref.org" and url.path == "/works/10.1234%2Fsample"
        assert parse_qs(url.query) == {"mailto":[contact]}
        return 200, {"x-rate-limit-limit":"3","x-rate-limit-interval":"5s","retry-after":"120"},fixture(view)["body"]
    args = dict(contact=contact,actor="Reviewer",expected_revision=view["revision"],confirmed=True,
                now=lambda:clock[0],transport=get)
    before = protected_rows(p)
    first = enrich_publication(p,pub,**args)
    assert first["status"] == "metadata_available"
    assert enrich_publication(open_project(p.root),pub,**args)["status"] == "cached"
    assert enrich_publication(p,pub,refresh=True,**args)["status"] == "provider_hold"
    assert len(calls) == 1 and contact not in json.dumps(db_rows(p,"audit_events"))
    clock[0] += timedelta(seconds=120)
    assert enrich_publication(p,pub,refresh=True,**args)["requested"] and len(calls) == 2
    assert protected_rows(p) == before


def test_missing_doi_never_opens_transport(store):
    p,pub = setup_target(store,())
    target = inspect_enrichment(p,pub)["target"]
    result = enrich_publication(p,pub,contact="test@example.org",actor="Reviewer",expected_revision=target["revision"],
                     confirmed=True,transport=lambda _:pytest.fail("Unexpected request"))
    assert result == {"status":"missing_doi", "requested":False}
