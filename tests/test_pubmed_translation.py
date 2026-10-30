"""P1-04f: actual NCBI redundant outer-group translation, with fail-closed checks.

Offline fixtures only; no provider contact, credentials or live-success claims.
"""
from __future__ import annotations

from contextlib import closing
from datetime import date
import json
import sqlite3
from urllib.parse import parse_qs

import pytest

from research_y.projects import create_project, open_project
from research_y.pubmed_checkpoint_resume import resume_pubmed_checkpoint
from research_y.pubmed_checkpoint_store import (
    CheckpointIntegrityError, commit_pubmed_checkpoint_page,
    create_pubmed_checkpoint, inspect_pubmed_checkpoint,
)
from research_y.pubmed_ids import PubMedIdentifierPage, parse_identifier_page, retrieve_bounded_identifiers
from research_y.pubmed_partition import DateWindow, PubMedPartitionResult
from research_y.pubmed_probe import (
    PubMedESearchProbeClient, _review_translation, _translation_matches_submitted,
    parse_esearch_count,
)
from research_y.storage import (
    ApprovedTerm, StrategyGroup, approve_strategy, create_search_run, plan_source_query,
)

SUBMITTED = '("ECMO"[All Fields])'
ACCEPTED = '"ECMO"[All Fields]'
UTC = "2026-10-30T13:49:51+00:00"
IDS = ("1001", "1002", "1003")


def esearch(accepted=ACCEPTED, *, count=3, start=0, ids=(), warnings=None):
    return json.dumps({"esearchresult": {
        "count": str(count), "retstart": str(start), "retmax": str(len(ids)),
        "idlist": list(ids), "querytranslation": accepted,
        "warninglist": {"outputmessages": warnings or []},
        "errorlist": {"phrasesnotfound": []},
    }}).encode("utf-8")


def provider(translation=ACCEPTED, *, count=3):
    pages = []
    def transport(request, timeout):
        fields = parse_qs(request.data.decode("utf-8"))
        assert fields["term"] == [SUBMITTED]  # Never alter the submitted query.
        size = int(fields["retmax"][0])
        offset = int(fields.get("retstart", ["0"])[0])
        if size:
            pages.append(offset)
        return esearch(translation, count=count, start=offset,
                       ids=IDS[offset:offset + size] if size else ())
    return PubMedESearchProbeClient(email="synthetic@example.org", transport=transport), pages


@pytest.mark.parametrize(("submitted", "accepted"), [
    (SUBMITTED, ACCEPTED),
    ('(( "ECMO"[All Fields] ))', ACCEPTED),
    (ACCEPTED, SUBMITTED),
    ('("right ventricle"[All Fields] OR "ECMO"[All Fields])',
     '"right ventricle"[All Fields] OR "ECMO"[All Fields]'),
    ('("(ECMO)"[All Fields])', '"(ECMO)"[All Fields]'),
])
def test_whole_expression_outer_group_only_is_equivalent(submitted, accepted):
    assert _translation_matches_submitted(submitted, accepted)
    assert not _review_translation(submitted, accepted, ())


@pytest.mark.parametrize("changed", [
    '"ECMO"[Title/Abstract]',
    '"ecmo"[All Fields]',
    '"ECMO"[All Fields] OR "other"[All Fields]',
    '"ECMO"[All Fields] AND "other"[All Fields]',
    '"ECMO"[MeSH Terms]',
    '"(ECMO)"[All Fields]',
    '("ECMO"[All Fields]',  # Unbalanced provider parentheses.
])
def test_field_term_operator_mesh_quote_and_unbalanced_changes_require_review(changed):
    assert not _translation_matches_submitted(SUBMITTED, changed)
    assert _review_translation(SUBMITTED, changed, ())


def test_removing_semantically_important_internal_group_is_never_equivalent():
    submitted = '(("a"[All Fields] OR "b"[All Fields]) AND "c"[All Fields])'
    changed = '"a"[All Fields] OR "b"[All Fields] AND "c"[All Fields]'
    assert not _translation_matches_submitted(submitted, changed)


def test_real_ncbi_translation_preserves_raw_evidence_without_false_count_failure():
    result = parse_esearch_count(esearch(), SUBMITTED, checked_at_utc=UTC)
    assert result.exact_query == SUBMITTED
    assert result.accepted_translation == ACCEPTED
    assert result.reported_matches == 3
    assert result.translation_matches_submitted is True
    assert result.warnings == ()
    assert result.review_required is False
    assert result.retrieved_records == 0 and not result.retrieval_verified


def test_even_equivalent_translation_with_provider_warning_requires_review():
    result = parse_esearch_count(esearch(warnings=["Unsupported phrase"]), SUBMITTED,
                                 checked_at_utc=UTC)
    assert result.translation_matches_submitted
    assert result.review_required
    assert result.warnings


def test_compiled_single_term_query_reaches_all_esearch_pages_without_mutation():
    client, pages = provider()
    result = retrieve_bounded_identifiers(client, SUBMITTED, page_size=2)
    assert result.status == "identifiers_reconciled_metadata_pending"
    assert result.pmids == IDS and pages == [0, 2]
    assert all(p.accepted_translation == ACCEPTED and not p.review_required
               for p in result.pages)
    assert not result.source_retrieval_verified


def test_identifier_page_still_rejects_changed_field_after_parenthesis_removal():
    page = parse_identifier_page(
        esearch('"ECMO"[Title/Abstract]', start=0, ids=IDS[:2]),
        exact_query=SUBMITTED, retstart=0, retmax=2, retrieved_at_utc=UTC)
    assert page.review_required


def test_checkpoint_accepts_raw_ncbi_translation_and_reopens_without_refetch(tmp_path):
    project = create_project(tmp_path, "Equivalent translation")
    version = approve_strategy(
        project, theme="ECMO", approved_by="Researcher", approval_confirmed=True,
        groups=(StrategyGroup("g1", "ECMO", (ApprovedTerm("ECMO", "researcher", True),)),),
    )
    run = create_search_run(project, version.strategy_version_id)
    pending = plan_source_query(
        project, run_id=run.run_id, group_id="g1",
        source_name="pubmed", exact_query=SUBMITTED,
    )
    plan = PubMedPartitionResult(
        SUBMITTED, DateWindow(date(2025, 1, 1), date(2025, 1, 2)),
        3, "incomplete", (), (), (),
    )
    create_pubmed_checkpoint(project, pending.query_id, plan, page_size=2)
    client, pages = provider()
    result = resume_pubmed_checkpoint(open_project(project.root), pending.query_id, client)
    assert result.status == "identifiers_reconciled_metadata_pending"
    assert result.snapshot.pmids == IDS and result.snapshot.pages_committed == 2
    assert pages == [0, 2]
    assert not result.source_retrieval_verified
    with closing(sqlite3.connect(project.database_path)) as db:
        raw = [json.loads(row[0]) for row in db.execute(
            "SELECT page_json FROM pubmed_checkpoint_pages ORDER BY retstart")]
        assert [p["accepted_translation"] for p in raw] == [ACCEPTED, ACCEPTED]
        assert db.execute(
            "SELECT status FROM source_queries WHERE query_id=?", (pending.query_id,)
        ).fetchone()[0] == "incomplete"

    assert inspect_pubmed_checkpoint(open_project(project.root), pending.query_id).pmids == IDS
    again = resume_pubmed_checkpoint(open_project(project.root), pending.query_id, client)
    assert again.snapshot.identifiers_reconciled and pages == [0, 2]


def test_checkpoint_refuses_forged_unreviewed_field_change(tmp_path):
    project = create_project(tmp_path, "Inconsistent page")
    version = approve_strategy(
        project, theme="ECMO", approved_by="Researcher", approval_confirmed=True,
        groups=(StrategyGroup("g1", "ECMO", (ApprovedTerm("ECMO", "researcher", True),)),),
    )
    run = create_search_run(project, version.strategy_version_id)
    pending = plan_source_query(
        project, run_id=run.run_id, group_id="g1",
        source_name="pubmed", exact_query=SUBMITTED,
    )
    create_pubmed_checkpoint(project, pending.query_id, PubMedPartitionResult(
        SUBMITTED, DateWindow(date(2025, 1, 1), date(2025, 1, 2)),
        3, "incomplete", (), (), (),
    ), page_size=2)
    page = PubMedIdentifierPage(
        SUBMITTED, 0, 2, 3, IDS[:2], '"ECMO"[Title/Abstract]',
        (), (), "a" * 64, UTC,
    )
    with pytest.raises(CheckpointIntegrityError, match="source-accepted"):
        commit_pubmed_checkpoint_page(project, pending.query_id, page)
    assert inspect_pubmed_checkpoint(project, pending.query_id).pages_committed == 0


def test_explicit_create_date_partition_remains_only_internal_and_unmodified():
    date_query = '(' + SUBMITTED + ') AND (2025/01/01:2025/01/31[crdt])'
    assert _review_translation(date_query, date_query, (), allow_crdt_partition=True) == ()
    assert any("AND/NOT" in reason
               for reason in _review_translation(date_query, date_query, ()))
    altered = '("ECMO"[All Fields] OR "shock"[All Fields]) AND (2025/01/01:2025/01/31[crdt])'
    assert _review_translation(date_query, altered, (), allow_crdt_partition=True)
