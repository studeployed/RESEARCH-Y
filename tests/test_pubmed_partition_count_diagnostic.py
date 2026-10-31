"""P1-04h count-only source interpretation tests; no network or credentials."""

from __future__ import annotations

from datetime import datetime, timezone
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode
from urllib.request import Request

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "pubmed_partition_count_diagnostic.py"
WORKFLOW = ROOT / ".github" / "workflows" / "pubmed-partition-count-diagnostic.yml"
EXISTING = ROOT / "scripts" / "pubmed_live_identifier_validation.py"


def load_script(path: Path, name: str):
    spec = spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


diagnostic = load_script(SCRIPT, "_researchy_partition_count_diagnostic_test")
UTC = datetime(2026, 10, 31, 13, 52, tzinfo=timezone.utc)
CONTACT = "synthetic@example.org"
KEY = "SYNTHETIC-SECRET-DO-NOT-PUBLISH"
PARTITION = diagnostic.DateWindow(
    diagnostic.WINDOW_START, UTC.date() + diagnostic.timedelta(days=1)
).query_for(diagnostic.QUERY)


def response(translation: str, *, count: int, warnings=(), retmax="0"):
    return json.dumps({
        "esearchresult": {
            "count": str(count), "retstart": "0", "retmax": retmax,
            "idlist": [], "querytranslation": translation,
            "warninglist": {"outputmessages": list(warnings)},
            "errorlist": {"phrasesnotfound": [], "fieldsnotfound": []},
        }
    }).encode("utf-8")


class FakeCountProvider:
    def __init__(self, root_count=19_483, partition_count=19_483,
                 partition_translation=None, partition_warnings=()):
        self.root_count = root_count
        self.partition_count = partition_count
        self.partition_translation = partition_translation
        self.partition_warnings = partition_warnings
        self.seen = []
        self.fail_stage = None
        self.inject_error = False

    def __call__(self, request, timeout):
        assert request.full_url == diagnostic.ESEARCH_URL
        assert request.get_method() == "POST"
        fields = parse_qs(request.data.decode("utf-8"))
        assert fields["db"] == ["pubmed"]
        assert fields["retmode"] == ["json"]
        assert fields["retmax"] == ["0"]
        assert fields.get("retstart") is None
        query = fields["term"][0]
        self.seen.append((query, fields))
        stage = "root" if query == diagnostic.QUERY else "partition"
        assert query in (diagnostic.QUERY, PARTITION)
        if self.fail_stage == stage:
            raise OSError("SECRET-CREDENTIAL-WOULD-LEAK-IN-ERROR")
        if self.inject_error and stage == "partition":
            return b'{"esearchresult":{"ERROR":"SECRET-CREDENTIAL-WOULD-LEAK"}}'
        if stage == "root":
            return response('"ECMO"[All Fields]', count=self.root_count)
        return response(
            self.partition_translation if self.partition_translation is not None else PARTITION,
            count=self.partition_count, warnings=self.partition_warnings,
        )


def run(tmp_path, provider):
    return diagnostic.diagnose(CONTACT, KEY,
                               output_path=tmp_path / "diagnostic.json",
                               now=UTC, transport=provider)


def test_manual_only_workflow_cannot_fetch_ids_or_be_triggered_on_pr():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "on:\n  workflow_dispatch:\n" in workflow
    assert "permissions:\n  contents: read\n" in workflow
    assert all(x not in workflow for x in (
        "\n  push:", "\n  pull_request:", "\n  schedule:",
        "  repository_dispatch:",
    ))
    assert "secrets.RESEARCHY_NCBI_CONTACT_EMAIL" in workflow
    assert "secrets.RESEARCHY_NCBI_API_KEY" in workflow
    assert "scripts/pubmed_partition_count_diagnostic.py" in workflow
    assert "if: always()" in workflow and "actions/upload-artifact@" in workflow
    assert "research-y-pubmed-source-smoke" in workflow
    assert "pubmed_live_identifier_validation.py start" not in workflow
    assert "pubmed_live_identifier_validation.py resume" not in workflow
    assert "researchy.sqlite3" not in workflow


def test_fixed_query_and_date_boundaries_match_existing_live_workflow():
    old = load_script(EXISTING, "_researchy_existing_id_validation_for_diag")
    assert diagnostic.QUERY == old.QUERY
    assert diagnostic.WINDOW_START == old.WINDOW_START
    assert diagnostic.MAX_SOURCE_REQUESTS == 2


def test_equal_counts_with_accepted_fields_still_cannot_claim_retrieval(tmp_path):
    provider = FakeCountProvider()
    result = run(tmp_path, provider)
    assert result["status"] == "count_only_reconciled"
    assert result["reason_code"] == "no_first_partition_count_discrepancy"
    assert result["root"]["accepted_translation"] == '"ECMO"[All Fields]'
    assert result["root"]["reported_matches"] == 19_483
    assert result["partition"]["submitted_query"] == PARTITION
    assert result["partition"]["accepted_translation"] == PARTITION
    assert result["partition"]["reported_matches"] == 19_483
    assert result["counts_reconciled"]
    assert result["source_requests"] == 2 == len(provider.seen)
    assert result["identifier_pages_requested"] == 0
    assert result["retrieved_unique_pmids"] == 0
    assert not result["identifiers_reconciled"]
    assert not result["source_retrieval_verified"]
    assert not result["metadata_acquired"]
    assert (result["date_window"] ==
            {"start": "1900-01-01", "end": "2026-11-01"})
    assert json.loads((tmp_path / "diagnostic.json").read_text()) == result
    artifact = (tmp_path / "diagnostic.json").read_text()
    assert CONTACT not in artifact and KEY not in artifact


def test_changed_partition_translation_and_warnings_are_preserved_for_review(tmp_path):
    translation = '"ECMO"[All Fields] AND 1900/01/01:2026/11/01[Create Date]'
    provider = FakeCountProvider(partition_translation=translation,
                                 partition_warnings=("Unexpected date phrase",))
    result = run(tmp_path, provider)
    assert result["status"] == "query_review_required"
    assert result["reason_code"] == "partition_translation_or_warnings"
    assert result["root"]["reported_matches"] == 19_483
    assert result["partition"]["accepted_translation"] == translation
    assert result["partition"]["warnings"] == ["outputmessages: Unexpected date phrase"]
    assert any("differs" in x for x in result["partition"]["review_reasons"])
    assert result["partition"]["review_required"]
    assert result["counts_reconciled"]
    assert result["identifier_pages_requested"] == 0
    assert len(provider.seen) == 2


def test_date_coverage_mismatch_is_distinct_from_translation_issue(tmp_path):
    result = run(tmp_path, FakeCountProvider(partition_count=19_481))
    assert result["status"] == "incomplete"
    assert result["reason_code"] == "create_date_coverage_count_mismatch"
    assert result["reported_count_difference"] == -2
    assert not result["counts_reconciled"]
    assert result["partition"]["translation_matches_submitted"]
    assert result["partition"]["review_reasons"] == []


def test_both_count_mismatch_and_unsafe_translation_remain_evident(tmp_path):
    result = run(tmp_path, FakeCountProvider(
        partition_count=19_480,
        partition_translation='"ECMO"[Title/Abstract]',
    ))
    assert result["status"] == "query_review_required"
    assert result["reported_count_difference"] == -3
    assert not result["counts_reconciled"]
    assert result["partition"]["review_required"]
    assert result["reason_code"] == "partition_translation_or_warnings"


def test_root_outside_restricted_diagnostic_size_never_calls_partition(tmp_path):
    provider = FakeCountProvider(root_count=5)
    result = run(tmp_path, provider)
    assert result["reason_code"] == "root_count_outside_diagnostic_safety_bounds"
    assert result["partition"] is None
    assert result["source_requests"] == 1
    assert len(provider.seen) == 1


def test_network_error_on_partition_preserves_root_and_never_logs_credentials(tmp_path):
    provider = FakeCountProvider()
    provider.fail_stage = "partition"
    result = run(tmp_path, provider)
    assert result["status"] == "incomplete"
    assert result["reason_code"] == "partition_count_request_failed"
    assert result["root"]["reported_matches"] == 19_483
    assert result["partition"] is None
    assert result["error"] == {"category": "network_error", "retryable": True}
    artifact = (tmp_path / "diagnostic.json").read_text()
    assert "SECRET-CREDENTIAL" not in artifact
    assert KEY not in artifact and CONTACT not in artifact
    assert len(provider.seen) == 2


def test_invalid_provider_payload_is_a_distinct_failure_without_raw_errors(tmp_path):
    provider = FakeCountProvider()
    provider.inject_error = True
    result = run(tmp_path, provider)
    assert result["reason_code"] == "partition_count_request_failed"
    assert result["error"] == {"category": "invalid_source_response", "retryable": False}
    assert "SECRET-CREDENTIAL" not in (tmp_path / "diagnostic.json").read_text()


def test_http_503_is_categorised_without_emitting_provider_response(tmp_path):
    def backend(request, timeout):
        raise HTTPError(request.full_url, 503, "PRIVATE-DO-NOT-ECHO", {}, None)
    result = diagnostic.diagnose(
        CONTACT, KEY, output_path=tmp_path / "failure.json",
        now=UTC, transport=backend,
    )
    assert result["reason_code"] == "root_count_request_failed"
    assert result["error"] == {"category": "http_error",
                                "http_status": 503, "retryable": True}
    assert "PRIVATE-DO-NOT-ECHO" not in (tmp_path / "failure.json").read_text()


def test_provider_echoing_api_key_or_contact_is_redacted(tmp_path):
    provider = FakeCountProvider(
        partition_translation="source mentions " + KEY,
        partition_warnings=("contact=" + CONTACT,),
    )
    result = run(tmp_path, provider)
    artifact = (tmp_path / "diagnostic.json").read_text()
    assert CONTACT not in artifact and KEY not in artifact
    assert "[REDACTED]" in artifact
    assert result["partition"]["provider_text_redacted"] is True
    assert result["status"] == "query_review_required"


def test_count_only_guard_rejects_unapproved_identifier_request():
    guard = diagnostic._CountOnlyTransport((diagnostic.QUERY, PARTITION),
                                           backend=lambda req, timeout: b"{}")
    request = Request(diagnostic.ESEARCH_URL,
                      data=urlencode({"db": "pubmed", "retmode": "json",
                                      "retmax": "1", "term": diagnostic.QUERY}).encode(),
                      method="POST")
    with pytest.raises(diagnostic.DiagnosticError, match="Non-count"):
        guard(request, 20)
    assert guard.calls == []


def test_missing_secret_never_writes_evidence_or_attempts_provider(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("RESEARCHY_NCBI_CONTACT_EMAIL", raising=False)
    monkeypatch.delenv("RESEARCHY_NCBI_API_KEY", raising=False)
    target = tmp_path / "empty" / "result.json"
    assert diagnostic.main(["--output", str(target)]) == 2
    assert not target.exists()
    assert "Contact secret absent" in capsys.readouterr().err
