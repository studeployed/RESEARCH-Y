"""Offline EFetch XML, metadata provenance and interruption/recovery fixtures."""

from __future__ import annotations

from contextlib import closing
from datetime import date
import json
import sqlite3
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs

import pytest

from research_y.pubmed_metadata import (
    EFETCH_URL, MAX_BATCH_IDS, MAX_EFETCH_BYTES, PubMedEFetchClient,
    PubMedMetadataError, PubMedMetadataTransportError, parse_efetch_xml,
    validate_pmids,
)
from research_y.pubmed_metadata_store import (
    PubMedMetadataIntegrityError, collect_pubmed_metadata,
    commit_pubmed_metadata_batch, missing_pubmed_metadata_pmids,
)
from research_y.pubmed_probe import PubMedESearchProbeClient
from research_y.projects import create_project, open_project
from research_y.storage import ApprovedTerm, StrategyGroup, approve_strategy, create_search_run, plan_source_query
from research_y.pubmed_checkpoint_store import create_pubmed_checkpoint, commit_pubmed_checkpoint_page, pause_pubmed_checkpoint
from research_y.pubmed_partition import DateWindow, PubMedPartitionResult
from research_y.pubmed_ids import PubMedIdentifierPage

Q = '("right ventricle"[All Fields])'
UTC = "2026-10-27T00:00:00+00:00"


def article_xml(pmid: str, *, title: str = "A <i>ventricular</i> study",
                doi: str = "10.1000/example", abstract: bool = True) -> str:
    abstract_text = ("<Abstract><AbstractText Label=\"BACKGROUND\" NlmCategory=\"BACKGROUND\">Intro &amp; context.</AbstractText>"
                     "<AbstractText Label=\"RESULTS\">We observed <i>some</i> findings.</AbstractText>"
                     "<CopyrightInformation>Copyright Author 2026</CopyrightInformation></Abstract>"
                     if abstract else "")
    return f"""<PubmedArticle><MedlineCitation Status="MEDLINE"><PMID Version="1">{pmid}</PMID>
    <Article><Journal><ISSN IssnType="Print">1234-5678</ISSN><JournalIssue><Volume>19</Volume>
      <Issue>2</Issue><PubDate><Year>2026</Year><Month>Oct</Month><Day>11</Day></PubDate></JournalIssue>
      <Title>Journal of Critical Care</Title><ISOAbbreviation>J Crit Care</ISOAbbreviation></Journal>
      <ArticleTitle>{title}</ArticleTitle><Pagination><MedlinePgn>155-160</MedlinePgn></Pagination>
      {abstract_text}
      <AuthorList CompleteYN="Y"><Author ValidYN="Y"><LastName>Smith</LastName><ForeName>Jane</ForeName>
        <Initials>J</Initials><Identifier Source="ORCID">0000-0002-1234-5678</Identifier>
        <AffiliationInfo><Affiliation>Hospital A</Affiliation></AffiliationInfo></Author>
        <Author><CollectiveName>Research Consortium</CollectiveName></Author></AuthorList>
      <Language>eng</Language><PublicationTypeList><PublicationType>Randomized Controlled Trial</PublicationType>
      </PublicationTypeList><ELocationID EIdType="doi">{doi}</ELocationID></Article>
      <KeywordList><Keyword>ECMO</Keyword></KeywordList>
      <MeshHeadingList><MeshHeading><DescriptorName UI="D006801" MajorTopicYN="N">Humans</DescriptorName>
      </MeshHeading></MeshHeadingList></MedlineCitation>
    <PubmedData><History><PubMedPubDate PubStatus="pubmed"><Year>2026</Year><Month>10</Month><Day>15</Day>
    </PubMedPubDate></History><ArticleIdList><ArticleId IdType="pubmed">{pmid}</ArticleId>
    <ArticleId IdType="doi">{doi}</ArticleId><ArticleId IdType="pmc">PMC12345</ArticleId></ArticleIdList></PubmedData>
    </PubmedArticle>"""


def response(*ids: str, abstract: bool = True) -> bytes:
    return ('<?xml version="1.0"?><!DOCTYPE PubmedArticleSet PUBLIC "-//NLM//DTD PubMedArticle" '
            '"https://dtd.nlm.nih.gov/ncbi/pubmed/out/pubmed_250101.dtd">'
            '<PubmedArticleSet>' + ''.join(article_xml(p, abstract=abstract) for p in ids)
            + '</PubmedArticleSet>').encode()


def make_client(transport):
    return PubMedEFetchClient(
        PubMedESearchProbeClient(email="test@example.org", transport=lambda r, t: b"unused"),
        transport=transport,
    )


def test_pubmed_xml_metadata_and_multisection_abstract_are_preserved():
    batch = parse_efetch_xml(response("111"), ("111",), retrieved_at_utc=UTC)
    r = batch.records[0]
    assert r.pmid == "111" and r.title == "A ventricular study"
    assert [(x['label'], x['text']) for x in r.abstract_sections] == [
        ("BACKGROUND", "Intro & context."), ("RESULTS", "We observed some findings.")]
    assert r.abstract_status == "present"
    assert r.abstract_copyright == "Copyright Author 2026"
    assert r.authors[0]["last_name"] == "Smith"
    assert r.authors[0]["identifiers"] == [{"source": "ORCID", "value": "0000-0002-1234-5678"}]
    assert r.authors[1]["collective_name"] == "Research Consortium"
    assert r.journal["title"] == "Journal of Critical Care"
    assert r.journal["volume"] == "19" and r.journal["pages"] == "155-160"
    assert r.identifiers["pmc"] == ("PMC12345",)
    assert r.identifiers["doi"] == ("10.1000/example",)
    assert r.languages == ("eng",) and r.publication_types == ("Randomized Controlled Trial",)
    assert r.keywords == ("ECMO",)
    assert r.mesh_headings[0]["descriptor"] == "Humans"
    assert any(x["kind"] == "journal_pub_date" for x in r.publication_dates)
    assert any(x["kind"] == "pubmed_history_pubmed" for x in r.publication_dates)
    assert r.citation_status == "MEDLINE"
    assert batch.response_sha256 and len(batch.response_sha256) == 64
    assert not batch.source_retrieval_verified


def test_no_abstract_is_not_fabricated_or_labelled_absent_from_all_sources():
    r = parse_efetch_xml(response("111", abstract=False), ("111",), retrieved_at_utc=UTC).records[0]
    assert r.abstract_sections == ()
    assert r.abstract_status == "not_supplied_in_response"
    assert r.abstract_copyright is None


@pytest.mark.parametrize("ids", [(), ("0",), ("01",), ("abc",), ("2", "2"),
                                  ("1\n",), tuple(str(i) for i in range(1, MAX_BATCH_IDS + 2))])
def test_invalid_pmid_inputs_are_rejected(ids):
    with pytest.raises(ValueError):
        validate_pmids(ids)


def test_missing_unexpected_or_duplicate_pubmed_records_fail_atomically():
    for payload, expected in [(response("111"), ("111", "222")),
                              (response("111", "222"), ("111",)),
                              (response("111", "111"), ("111", "222"))]:
        with pytest.raises(PubMedMetadataError, match="do not match"):
            parse_efetch_xml(payload, expected, retrieved_at_utc=UTC)


@pytest.mark.parametrize("xml", [b"", b"not XML", b"<PubmedArticleSet>",
                                     b"<Error>Invalid PMID</Error>",
                                     b"<!DOCTYPE PubmedArticleSet [<!ENTITY x 'BAD'>]><PubmedArticleSet>&x;</PubmedArticleSet>",
                                     b"<PubmedArticleSet><DeleteCitation/></PubmedArticleSet>",
                                     b"<PubmedArticleSet><PubmedBookArticle/></PubmedArticleSet>",
                                     b"<PubmedArticleSet><PubmedArticle/></PubmedArticleSet>"])
def test_corrupt_provider_xml_fails_without_invented_records(xml):
    with pytest.raises(PubMedMetadataError):
        parse_efetch_xml(xml, ("111",), retrieved_at_utc=UTC)


def test_response_size_cap_rejects_oversized_payload():
    with pytest.raises(PubMedMetadataError, match="oversized"):
        parse_efetch_xml(b"A" * (MAX_EFETCH_BYTES + 1), ("111",), retrieved_at_utc=UTC)


def test_efetch_is_fixed_https_post_with_reuse_of_contact_and_key():
    requests = []
    key = "SECRET_NEVER_LOGGED"
    esearch = PubMedESearchProbeClient(email="test@example.org", api_key=key)
    def transport(req, timeout):
        requests.append((req, timeout))
        return response("111", "222")
    result = PubMedEFetchClient(esearch, transport=transport).fetch(["111", "222"])
    request, timeout = requests[0]
    assert request.get_method() == "POST"
    assert request.full_url == EFETCH_URL and request.full_url.startswith("https://")
    assert '?' not in request.full_url
    form = parse_qs(request.data.decode())
    assert form["db"] == ["pubmed"] and form["retmode"] == ["xml"]
    assert form["id"] == ["111,222"]
    assert form["email"] == ["test@example.org"]
    assert form["api_key"] == [key]
    assert key not in repr(result)
    assert timeout == 20.0


def test_http_429_retryability_and_no_secret_in_exception():
    def blocked(req, timeout):
        raise HTTPError(req.full_url, 429, "SECRET_API_KEY", {}, None)
    client = PubMedEFetchClient(
        PubMedESearchProbeClient(email="test@example.org", api_key="SECRET_API_KEY"),
        transport=blocked)
    with pytest.raises(PubMedMetadataTransportError) as err:
        client.fetch(["111"])
    assert err.value.http_status == 429 and err.value.retryable
    assert "SECRET_API_KEY" not in str(err.value)


def test_transport_disconnect_errors_are_sanitised():
    def offline(req, timeout):
        raise URLError("PRIVATE-SERVER-PATH")
    with pytest.raises(PubMedMetadataTransportError) as err:
        make_client(offline).fetch(["111"])
    assert err.value.retryable
    assert "PRIVATE-SERVER-PATH" not in str(err.value)


def test_shared_pacing_across_efetch_calls():
    now = [1.0]
    slept = []
    def clock():
        return now[0]
    def sleep(seconds):
        slept.append(seconds)
        now[0] += seconds
    esearch = PubMedESearchProbeClient(email="test@example.org", clock=clock, sleep=sleep)
    client = PubMedEFetchClient(esearch, transport=lambda req, timeout: response("111"))
    client.fetch(["111"])
    client.fetch(["111"])
    assert slept == pytest.approx([0.4])


def project_with_pmids(tmp_path, pmids=("111", "222", "333")):
    p = create_project(tmp_path, "EFetch fixtures")
    version = approve_strategy(
        p, theme="Right ventricle",
        groups=(StrategyGroup("g1", "Right ventricle", (ApprovedTerm("right ventricle", "researcher", True),)),),
        approved_by="Researcher", approval_confirmed=True,
    )
    run = create_search_run(p, version.strategy_version_id)
    query = plan_source_query(p, run_id=run.run_id, group_id="g1", source_name="pubmed", exact_query=Q)
    root = PubMedPartitionResult(Q, DateWindow(date(2025, 1, 1), date(2025, 1, 2)), len(pmids),
                                 "identifiers_reconciled_metadata_pending", (), (), ())
    create_pubmed_checkpoint(p, query.query_id, root, page_size=max(1, len(pmids)))
    if pmids:
        page = PubMedIdentifierPage(
            exact_query=Q, retstart=0, requested_retmax=len(pmids), reported_matches=len(pmids),
            pmids=tuple(pmids), accepted_translation=Q, warnings=(), review_reasons=(),
            response_sha256="a" * 64, retrieved_at_utc=UTC,
        )
        commit_pubmed_checkpoint_page(p, query.query_id, page)
    return p, query.query_id


def _count_db(project, query_id):
    with closing(sqlite3.connect(project.database_path)) as con:
        rows = con.execute("SELECT COUNT(*) FROM source_retrievals").fetchone()[0]
        links = con.execute("SELECT COUNT(*) FROM query_retrievals WHERE query_id=?", (query_id,)).fetchone()[0]
        audit = con.execute("SELECT COUNT(*) FROM audit_events WHERE event_type='pubmed_efetch_metadata_committed'").fetchone()[0]
        source_status = con.execute("SELECT status FROM source_queries WHERE query_id=?", (query_id,)).fetchone()[0]
    return rows, links, audit, source_status


def test_metadata_batch_commit_is_atomic_and_source_stays_incomplete(tmp_path):
    p, query_id = project_with_pmids(tmp_path, ("111", "222"))
    batch = parse_efetch_xml(response("111", "222"), ("111", "222"), retrieved_at_utc=UTC)
    assert commit_pubmed_metadata_batch(p, query_id, batch) == 2
    assert _count_db(p, query_id) == (2, 2, 1, "incomplete")
    assert missing_pubmed_metadata_pmids(p, query_id) == ()
    with closing(sqlite3.connect(p.database_path)) as db:
        actual = [json.loads(row[0]) for row in db.execute("SELECT original_metadata_json FROM source_retrievals")]
        assert all(x["record"]["abstract_status"] == "present" for x in actual)
        assert all(x["rights_review_required_for_abstract_redistribution"] for x in actual)
    assert commit_pubmed_metadata_batch(p, query_id, batch) == 0
    assert _count_db(p, query_id) == (2, 2, 1, "incomplete")


def test_repeat_identical_records_at_different_retrieval_times_remains_idempotent(tmp_path):
    p, query_id = project_with_pmids(tmp_path, ("111",))
    b1 = parse_efetch_xml(response("111"), ("111",), retrieved_at_utc=UTC)
    b2 = parse_efetch_xml(response("111"), ("111",), retrieved_at_utc="2026-10-28T00:00:00+00:00")
    commit_pubmed_metadata_batch(p, query_id, b1)
    assert commit_pubmed_metadata_batch(p, query_id, b2) == 0
    assert _count_db(p, query_id)[:3] == (1, 1, 1)


def test_source_metadata_change_is_explicit_conflict_and_keeps_original(tmp_path):
    p, query_id = project_with_pmids(tmp_path, ("111",))
    before = parse_efetch_xml(response("111"), ("111",), retrieved_at_utc=UTC)
    after = parse_efetch_xml(response("111").replace(b"A <i>ventricular</i> study", b"Different study"),
                             ("111",), retrieved_at_utc=UTC)
    commit_pubmed_metadata_batch(p, query_id, before)
    with pytest.raises(PubMedMetadataIntegrityError, match="conflicts"):
        commit_pubmed_metadata_batch(p, query_id, after)
    assert _count_db(p, query_id)[:3] == (1, 1, 1)


def test_uncheckpointed_record_is_never_silently_inserted(tmp_path):
    p, query_id = project_with_pmids(tmp_path, ("111",))
    extra = parse_efetch_xml(response("222"), ("222",), retrieved_at_utc=UTC)
    with pytest.raises(PubMedMetadataIntegrityError, match="outside"):
        commit_pubmed_metadata_batch(p, query_id, extra)
    assert _count_db(p, query_id)[:3] == (0, 0, 0)


def test_audit_trigger_failure_rolls_back_entire_efetch_batch(tmp_path):
    p, query_id = project_with_pmids(tmp_path, ("111", "222"))
    with closing(sqlite3.connect(p.database_path)) as db, db:
        db.execute("""CREATE TRIGGER block_pubmed_metadata_audit BEFORE INSERT ON audit_events
                 WHEN NEW.event_type='pubmed_efetch_metadata_committed'
                 BEGIN SELECT RAISE(ABORT,'SECRET-DATABASE-TOKEN'); END""")
    batch = parse_efetch_xml(response("111", "222"), ("111", "222"), retrieved_at_utc=UTC)
    with pytest.raises(sqlite3.DatabaseError):
        commit_pubmed_metadata_batch(p, query_id, batch)
    assert _count_db(p, query_id)[:3] == (0, 0, 0)
    with closing(sqlite3.connect(p.database_path)) as db, db:
        db.execute("DROP TRIGGER block_pubmed_metadata_audit")
    assert commit_pubmed_metadata_batch(p, query_id, batch) == 2


def test_reopen_project_recovers_only_missing_metadata_batches(tmp_path):
    p, query_id = project_with_pmids(tmp_path)
    calls = []
    def transport(req, timeout):
        pmids = parse_qs(req.data.decode())["id"][0].split(",")
        calls.append(pmids)
        return response(*pmids)
    client = make_client(transport)
    first = collect_pubmed_metadata(p, query_id, client, batch_size=2, max_batches=1)
    assert first.status == "incomplete" and first.committed_metadata_ids == 2
    assert first.missing_pmids == ("333",)
    reopened = open_project(p.root)
    second = collect_pubmed_metadata(reopened, query_id, client, batch_size=2)
    assert second.status == "metadata_acquired_reconciliation_pending"
    assert second.committed_metadata_ids == 3
    assert calls == [["111", "222"], ["333"]]
    assert _count_db(p, query_id) == (3, 3, 2, "incomplete")
    assert not second.source_retrieval_verified


def test_network_failure_after_one_batch_keeps_committed_rows_and_retries_missing(tmp_path):
    p, query_id = project_with_pmids(tmp_path)
    count = [0]
    def transport(req, timeout):
        count[0] += 1
        if count[0] == 2:
            raise URLError("TOP_SECRET_API_KEY")
        return response(*parse_qs(req.data.decode())["id"][0].split(","))
    client = make_client(transport)
    partial = collect_pubmed_metadata(p, query_id, client, batch_size=2)
    assert partial.status == "incomplete" and partial.committed_metadata_ids == 2
    assert "TOP_SECRET" not in repr(partial)
    done = collect_pubmed_metadata(p, query_id, client, batch_size=2)
    assert done.committed_metadata_ids == 3
    assert done.status == "metadata_acquired_reconciliation_pending"
    assert _count_db(p, query_id)[:2] == (3, 3)


def test_pause_during_fetch_commits_inflight_batch_but_stops_next(tmp_path):
    p, query_id = project_with_pmids(tmp_path)
    calls = []
    def transport(req, timeout):
        ids = parse_qs(req.data.decode())["id"][0].split(",")
        calls.append(ids)
        pause_pubmed_checkpoint(p, query_id)
        return response(*ids)
    result = collect_pubmed_metadata(p, query_id, make_client(transport), batch_size=1)
    assert result.status == "paused" and len(calls) == 1
    assert result.committed_metadata_ids == 1
    assert _count_db(p, query_id)[-1] == "paused"


def test_callback_exception_is_sanitised_after_batch_commit(tmp_path):
    p, query_id = project_with_pmids(tmp_path)
    def explode(batch):
        raise RuntimeError("PRIVATE-CREDENTIAL-IN-CALLBACK")
    report = collect_pubmed_metadata(p, query_id, make_client(
        lambda req, timeout: response(*parse_qs(req.data.decode())["id"][0].split(","))),
        batch_size=1, after_commit=explode)
    assert report.status == "incomplete"
    assert report.committed_metadata_ids == 1
    assert "PRIVATE" not in repr(report)


def test_corrupt_checkpoint_never_causes_efetch_calls(tmp_path):
    p, query_id = project_with_pmids(tmp_path, ("111",))
    with closing(sqlite3.connect(p.database_path)) as db, db:
        db.execute("UPDATE pubmed_checkpoint_runs SET plan_sha256=? WHERE query_id=?",
                   ("0" * 64, query_id))
    calls = []
    result = collect_pubmed_metadata(p, query_id, make_client(lambda req, to: calls.append(req)), batch_size=1)
    assert result.status == "incomplete" and not calls


def test_persisted_metadata_index_mismatch_is_refused(tmp_path):
    p, query_id = project_with_pmids(tmp_path, ("111",))
    with closing(sqlite3.connect(p.database_path)) as db, db:
        db.execute("INSERT INTO source_retrievals VALUES ('bad-id',?, 'pubmed', '222',?,'{}')",
                   (db.execute("SELECT run_id FROM source_queries WHERE query_id=?",(query_id,)).fetchone()[0], UTC))
        db.execute("INSERT INTO query_retrievals VALUES (?,?,?,'pubmed')",(
            query_id,'bad-id',db.execute("SELECT run_id FROM source_queries WHERE query_id=?",(query_id,)).fetchone()[0]))
    with pytest.raises(PubMedMetadataIntegrityError):
        missing_pubmed_metadata_pmids(p, query_id)


def test_zero_hit_checkpoint_acquires_no_fabricated_metadata(tmp_path):
    p, query_id = project_with_pmids(tmp_path, ())
    calls = []
    result = collect_pubmed_metadata(p, query_id, make_client(lambda req,to: calls.append(req)))
    assert result.status == "metadata_acquired_reconciliation_pending"
    assert result.expected_ids == 0 and result.committed_metadata_ids == 0
    assert calls == []
