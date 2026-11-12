from pathlib import Path
import json

import pytest

from research_y.wos_starter_client import WoSHTTPResponse, WoSStarterClient
from scripts import wos_cross_day_validation as driver
from test_wos_checkpoints import Clock, Provider, KEY


def client(clock, transport):
    return WoSStarterClient(api_key=KEY, transport=transport, request_budget=2,
                            clock=clock.monotonic, sleep=clock.sleep, utc_now=clock.now)


@pytest.mark.parametrize("new_remaining", [5000, 4900])
def test_cross_day_budget_distinguishes_resume_from_header_increase(tmp_path, new_remaining):
    clock = Clock()
    source = Provider(clock, total=300)
    workspace = tmp_path / "sample"
    first = driver.start(workspace, client(clock, source), now=clock.now)
    assert first["pages"] == 2 and len(source.calls) == 2
    with pytest.raises(ValueError, match="later_utc_date_required"):
        driver.resume(workspace, client(clock, source), now=clock.now)
    assert len(source.calls) == 2
    clock.sleep(86400)
    source.remaining = new_remaining
    result = driver.resume(workspace, client(clock, source), now=clock.now)
    assert result["cross_day_resume_verified"] and result["original_pages_unchanged"]
    assert result["quota_increase_observed"] is (new_remaining == 5000)
    assert not result["actual_exhaustion_observed"] and not result["source_retrieval_verified"]
    assert result["records_retained"] == 150 and result["requests"] == 4
    assert len(source.calls) == 4
    with pytest.raises(ValueError, match="first_day_evidence_invalid"):
        driver.resume(workspace, client(clock, source), now=clock.now)
    assert len(source.calls) == 4
    raw = (workspace / driver.EVIDENCE).read_text()
    assert json.loads(raw) == result
    assert all(private not in raw for private in (KEY, "WOS:", "Synthetic title", "response_json"))


def test_cross_day_drift_fails_without_acquiring_next_page(tmp_path):
    clock = Clock()
    source = Provider(clock, total=300)
    workspace = tmp_path / "sample"
    driver.start(workspace, client(clock, source), now=clock.now)
    clock.sleep(86400)
    source.change_count = True
    with pytest.raises(ValueError):
        driver.resume(workspace, client(clock, source), now=clock.now)
    assert len(source.calls) == 3 and not (workspace / driver.EVIDENCE).exists()


@pytest.mark.parametrize("first_allowance", [1, 2])
def test_near_midnight_exhaustion_waits_for_saved_deadline(tmp_path, first_allowance):
    clock = Clock()
    clock.sleep(11 * 3600 + 50 * 60)  # 23:50 UTC
    source = Provider(clock, total=300)
    source.remaining = first_allowance
    workspace = tmp_path / "sample"
    first = driver.start(workspace, client(clock, source), now=clock.now)
    assert first["remaining"] == 0 and first["pages"] == first_allowance
    last_response = clock.now()
    clock.sleep(10 * 60)
    source.remaining = 5000

    def after_hold(request, timeout):
        assert (clock.now() - last_response).total_seconds() >= 3600
        return source(request, timeout)

    result = driver.resume(workspace, client(clock, after_hold), now=clock.now, sleep=clock.sleep)
    assert result["actual_exhaustion_observed"] and result["quota_increase_observed"]
    assert result["resumed_probe_remaining"] == 4999 and result["original_pages_unchanged"]
    assert result["cross_day_resume_verified"] and not result["source_retrieval_verified"]
    assert result["records_retained"] == 50 * (first_allowance + 1)
    assert result["requests"] == len(source.calls) == first_allowance + 2


def test_long_provider_hold_stops_before_sleep_or_second_day_request(tmp_path):
    clock = Clock()
    clock.sleep(11 * 3600 + 50 * 60)
    source = Provider(clock, total=300)

    def long_hold(request, timeout):
        response = source(request, timeout)
        return WoSHTTPResponse(response.status, {**response.headers, "Retry-After": "7200"}, response.body)

    workspace = tmp_path / "sample"
    driver.start(workspace, client(clock, long_hold), now=clock.now)
    clock.sleep(10 * 60)
    with pytest.raises(ValueError, match="provider_hold_exceeds_sample_window"):
        driver.resume(workspace, client(clock, source), now=clock.now,
                      sleep=lambda seconds: pytest.fail("hold exceeds the bounded sample"))
    assert len(source.calls) == 1 and not (workspace / driver.EVIDENCE).exists()


def test_manual_only_no_provider_calls_without_consent_or_key(tmp_path, monkeypatch):
    args = ["start", "--workspace", str(tmp_path / "unused")]
    monkeypatch.delenv("RESEARCHY_WOS_STARTER_API_KEY", raising=False)
    monkeypatch.delenv("RESEARCHY_WOS_RETENTION_AUTHORIZED", raising=False)
    assert driver.main(args) == 2
    monkeypatch.setenv("RESEARCHY_WOS_RETENTION_AUTHORIZED", "true")
    assert driver.main(args) == 2
    assert not (tmp_path / "unused").exists()
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/wos-cross-day.yml").read_text()
    assert "workflow_dispatch:" in workflow and "default: false" in workflow
    assert "if: ${{ inputs.confirm_local_retention }}" in workflow
    assert all(trigger not in workflow for trigger in ("pull_request:", "push:", "schedule:"))
    assert workflow.count("secrets.RESEARCHY_WOS_STARTER_API_KEY") == 2
    assert "/ry-cross-day/cross-day-evidence.json" in workflow and "**/*" not in workflow
