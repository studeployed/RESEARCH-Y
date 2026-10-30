"""Offline acceptance of manual, controlled live PubMed ID recovery workflow.

No network or private credentials are needed in ordinary CI.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import re
from urllib.parse import parse_qs
from zoneinfo import ZoneInfoNotFoundError

import pytest

from research_y.projects import open_project
from research_y.pubmed_checkpoint_store import inspect_pubmed_checkpoint

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "pubmed-live-identifiers.yml"
SCRIPT = ROOT / "scripts" / "pubmed_live_identifier_validation.py"
SPEC = spec_from_file_location("_research_y_live_ids_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
live = module_from_spec(SPEC)
SPEC.loader.exec_module(live)

UTC_INSTANT = datetime(2026, 10, 30, 14, 51, tzinfo=timezone.utc)


class SyntheticNCBI:
    """Simulates a stable >10k PubMed index with two disjoint Create Dates."""

    def __init__(self, total=10_005):
        left = total // 2
        self.records = tuple(
            (str(10_000_001 + n), date(2025, 1, 1) if n < left else date(2026, 1, 1))
            for n in range(total)
        )
        self.calls = []
        self.change_root_count = False
        self.fail_from_offset = None
        self.exclude_one_from_dates = False
        self.bad_translation = False

    def __call__(self, request, timeout):
        assert request.full_url == "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        assert request.get_method() == "POST"
        assert not request.full_url.endswith("?api_key=")
        form = parse_qs(request.data.decode("utf-8"))
        query = form["term"][0]
        start = int(form.get("retstart", ["0"])[0])
        size = int(form["retmax"][0])
        self.calls.append((query, start, size))
        if self.fail_from_offset is not None and size and start >= self.fail_from_offset:
            raise OSError("simulated 503, no provider data verified")
        match = re.search(r"(\d{4}/\d{2}/\d{2}):(\d{4}/\d{2}/\d{2})\[crdt\]", query)
        if match:
            start_day, end_day = (
                date.fromisoformat(x.replace("/", "-")) for x in match.groups()
            )
            ids = [pid for pid, when in self.records if start_day <= when <= end_day]
            if self.exclude_one_from_dates and ids:
                ids = ids[:-1]
        else:
            ids = [pid for pid, _ in self.records]
        count = len(ids)
        if self.change_root_count and not match:
            count += 1
        translation = ('"ECMO"[Title/Abstract]' if self.bad_translation else
                       query if match else '"ECMO"[All Fields]')
        response = {"esearchresult": {
            "count": str(count), "retstart": str(start), "retmax": str(size),
            "idlist": ids[start:start+size] if size else [],
            "querytranslation": translation,
            "warninglist": {"outputmessages": []},
            "errorlist": {"phrasesnotfound": []},
        }}
        return json.dumps(response, sort_keys=True).encode("utf-8")


def _start(tmp_path, provider):
    return live.start_phase(
        tmp_path / "live-test", contact="synthetic@example.org",
        api_key="SYNTHETIC-DO-NOT-LOG",
        transport=provider, utc_now=UTC_INSTANT, enforce_off_peak=False,
    )


def _resume(tmp_path, provider):
    return live.resume_phase(
        tmp_path / "live-test", contact="synthetic@example.org",
        api_key="SYNTHETIC-DO-NOT-LOG",
        transport=provider, utc_now=UTC_INSTANT, enforce_off_peak=False,
    )


def test_live_workflow_is_manual_only_credential_private_and_separate_processes():
    contents = WORKFLOW.read_text(encoding="utf-8")
    assert "on:\n  workflow_dispatch:\n" in contents
    assert all(term not in contents for term in (
        "\n  push:", "\n  pull_request:", "\n  schedule:",
        "  repository_dispatch:",
    ))
    assert "permissions:\n  contents: read\n" in contents
    assert "secrets.RESEARCHY_NCBI_CONTACT_EMAIL" in contents
    assert "secrets.RESEARCHY_NCBI_API_KEY" in contents
    assert contents.count("python scripts/pubmed_live_identifier_validation.py ") == 2
    assert " start --workspace " in contents
    assert " resume --workspace " in contents
    assert "actions/upload-artifact@" in contents
    assert "identifier-evidence.json" in contents
    assert "researchy.sqlite3" not in contents
    assert "run: curl" not in contents
    assert "cancel-in-progress: false" in contents
    assert "research-y-pubmed-source-smoke" in contents


def test_actual_10005_source_ids_pause_then_reopen_reconcile_without_duplicate_page(tmp_path):
    source = SyntheticNCBI()
    first = _start(tmp_path, source)
    assert first["stage"] == "durable_pause"
    assert first["status"] == "paused"
    assert first["pages_committed"] == 1
    assert first["pages_expected"] > 20
    assert not first["identifiers_reconciled"]
    assert first["retrieved_unique_pmids"] == live.PAGE_SIZE
    assert not first["source_retrieval_verified"]

    state = json.loads((tmp_path / "live-test" / live.STATE_FILENAME).read_text())
    prior = state["first_page_query"], state["first_page_offset"]
    project = open_project(tmp_path / "live-test" / live.PROJECT_FOLDER)
    before = inspect_pubmed_checkpoint(project, state["query_id"])
    assert before.stored_status == "paused" and before.pages_committed == 1

    before_count = len(source.calls)
    final = _resume(tmp_path, source)
    later_calls = source.calls[before_count:]
    assert prior not in [(q, i) for q, i, size in later_calls if size > 0]
    assert final["identifier_acceptance_passed"]
    assert final["status"] == "identifiers_reconciled_metadata_pending"
    assert final["pages_committed"] == final["pages_expected"]
    assert final["retrieved_unique_pmids"] == 10_005
    assert final["reported_matches"] == 10_005
    assert len(final["pmid_union_sha256"]) == 64
    assert final["source_query_status"] == "incomplete"
    assert final["first_page_unchanged"]
    assert not final["source_retrieval_verified"] and not final["metadata_acquired"]
    assert sum(p["retmax"] for p in final["pages"]) == 10_005
    assert all(p["response_sha256"] and p["checkpoint_sha256"]
               for p in final["pages"])
    assert "SYNTHETIC-DO-NOT-LOG" not in json.dumps(final)

    saved = json.loads((tmp_path / "live-test" / live.EVIDENCE_FILENAME).read_text())
    assert saved["identifier_acceptance_passed"] is True
    assert saved["pmid_union_sha256"] == final["pmid_union_sha256"]


def test_changed_provider_count_preserves_first_page_and_returns_incomplete(tmp_path):
    source = SyntheticNCBI()
    assert _start(tmp_path, source)["status"] == "paused"
    source.change_root_count = True
    prior = len(source.calls)
    out = _resume(tmp_path, source)
    assert not out["identifier_acceptance_passed"]
    assert out["status"] == "incomplete"
    assert out["pages_committed"] == 1
    assert out["retrieved_unique_pmids"] == live.PAGE_SIZE
    assert not out["source_retrieval_verified"]
    assert all(size == 0 for _, _, size in source.calls[prior:])


def test_network_error_during_resume_is_incomplete_and_resume_can_recover(tmp_path):
    source = SyntheticNCBI()
    assert _start(tmp_path, source)["pages_committed"] == 1
    source.fail_from_offset = live.PAGE_SIZE
    incomplete = _resume(tmp_path, source)
    assert incomplete["status"] == "incomplete"
    assert not incomplete["identifier_acceptance_passed"]
    assert incomplete["pages_committed"] == 1
    source.fail_from_offset = None
    recovered = _resume(tmp_path, source)
    assert recovered["identifier_acceptance_passed"]
    assert recovered["reported_matches"] == recovered["retrieved_unique_pmids"]
    assert not recovered["source_retrieval_verified"]


def test_bad_provider_field_or_missing_date_coverage_cannot_pass(tmp_path):
    source = SyntheticNCBI()
    source.bad_translation = True
    with pytest.raises(live.ValidationFailure, match="translation"):
        _start(tmp_path, source)
    assert all(size == 0 for _, _, size in source.calls)
    assert not (tmp_path / "live-test" / live.STATE_FILENAME).exists()

    second = SyntheticNCBI()
    second.exclude_one_from_dates = True
    with pytest.raises(Exception):
        _start(tmp_path / "different", second)
    assert not (tmp_path / "different" / "live-test" / live.STATE_FILENAME).exists()


def test_finite_request_budget_fails_before_any_unbounded_paging(tmp_path):
    source = SyntheticNCBI()
    with pytest.raises(Exception):
        live.start_phase(
            tmp_path / "budget", contact="synthetic@example.org", api_key=None,
            transport=source, utc_now=UTC_INSTANT, enforce_off_peak=False,
            request_budget=1,
        )
    assert len(source.calls) == 1
    assert not (tmp_path / "budget" / live.STATE_FILENAME).exists()


def test_offpeak_rule_refuses_weekday_daytime_before_source_requests(tmp_path):
    source = SyntheticNCBI()
    try:
        assert not live.off_peak_utc(UTC_INSTANT)  # Friday 10:51 Eastern
    except ZoneInfoNotFoundError:
        pytest.skip("This Windows image has no IANA zoneinfo database")
    with pytest.raises(live.ValidationFailure, match="off-peak|NCBI"):
        live.start_phase(
            tmp_path / "daytime", contact="synthetic@example.org", api_key=None,
            transport=source, utc_now=UTC_INSTANT, enforce_off_peak=True,
        )
    assert source.calls == []
    assert not (tmp_path / "daytime").exists()
    assert live.off_peak_utc(datetime(2026, 10, 31, 14, 0, tzinfo=timezone.utc))


def test_missing_secret_never_attempts_network(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("RESEARCHY_NCBI_CONTACT_EMAIL", raising=False)
    monkeypatch.delenv("RESEARCHY_NCBI_API_KEY", raising=False)
    code = live.main(["start", "--workspace", str(tmp_path / "unused")])
    assert code == 2
    assert not (tmp_path / "unused").exists()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "private NCBI contact secret" in captured.err
