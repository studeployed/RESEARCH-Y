"""Local request ceilings pause a durable worker; they are not source failures."""
from contextlib import closing
from datetime import datetime
import sqlite3

import pytest

from research_y.projects import open_project
from research_y.wos_checkpoint_runner import run_wos_checkpoint
from research_y.wos_checkpoint_store import (
    inspect_wos_checkpoint, pause_wos_checkpoint, validate_wos_checkpoint,
)
from research_y.wos_starter import WoSStarterError
from research_y.wos_starter_client import WoSHTTPResponse, WoSStarterClient
from test_wos_checkpoints import KEY, QUERY, setup


def client_for(clock, provider, budget=None):
    options = {} if budget is None else {"request_budget": budget}
    return WoSStarterClient(api_key=KEY, transport=provider, clock=clock.monotonic,
                            sleep=clock.sleep, utc_now=clock.now, **options)


def session(project, query, clock, provider, *, budget=None, **options):
    client = client_for(clock, provider, budget)
    result = run_wos_checkpoint(open_project(project.root), query.query_id, client,
                                now=clock.now, **options)
    return result, client


def assert_clean_pause(project, query, result, expected_requests):
    assert result.status == "paused"
    assert result.reason_code == "session_budget_reached"
    assert result.failures == 0
    assert result.requests_reserved == result.requests_confirmed_attempted == expected_requests
    assert result.requests_unknown == 0 and not result.worker_active
    assert not result.enumeration_reconciled and not result.source_retrieval_verified
    with closing(sqlite3.connect(project.database_path)) as db:
        assert db.execute("SELECT COUNT(*) FROM wos_checkpoint_attempts "
                          "WHERE query_id=? AND outcome!='success'", (query.query_id,)).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM audit_events "
                          "WHERE event_type='wos_request_failed'").fetchone()[0] == 0
    reopened = open_project(project.root)
    assert inspect_wos_checkpoint(reopened, query.query_id) == result
    validate_wos_checkpoint(reopened, query.query_id)


@pytest.mark.parametrize("client_budget,worker_budget", [
    (1, 1000), (2, 1000), (3, 1000), (5, 1000), (6, 1000),
    (8, 1), (8, 2), (8, 3), (3, 3), (2, 1),
], ids=["client-one", "client-two", "client-three", "during-verification", "before-final",
        "worker-one", "worker-two", "worker-three", "equal", "worker-smaller"])
def test_smaller_budget_pauses_before_reserving_unsent_request(tmp_path, client_budget, worker_budget):
    project, queries, clock, provider = setup(tmp_path)
    result, client = session(project, queries[0], clock, provider,
                             budget=client_budget, max_requests=worker_budget)
    expected = min(client_budget, worker_budget)
    assert client.requests_made == len(provider.calls) == expected
    assert client.requests_remaining == client_budget - expected
    assert_clean_pause(project, queries[0], result, expected)


def test_actual_default_budgets_pause_without_exhausting_source_failure_budget(tmp_path):
    project, queries, clock, provider = setup(tmp_path)
    query = queries[0]
    # Neither default is overridden: client=3, worker=1000.
    first, client = session(project, query, clock, provider)
    assert client.requests_made == 3 and client.requests_remaining == 0
    assert first.records_committed == 103 and first.pages_committed == 3
    assert_clean_pause(project, query, first, 3)
    # Replaying a verification prefix does not complete the single-session
    # verification sweep, but must never manufacture source failures.
    for _ in range(4):
        clock.sleep(2)
        result, client = session(project, query, clock, provider)
        assert client.requests_made == 3
        assert_clean_pause(project, query, result, len(provider.calls))
        assert result.records_committed == 103
    clock.sleep(2)
    final, _ = session(project, query, clock, provider, budget=10)
    assert final.enumeration_reconciled and final.failures == 0
    assert final.records_committed == final.reported_matches == 103
    assert [call for call in provider.calls if call[0] == "acquire"] == [
        ("acquire", 1, 50), ("acquire", 2, 50), ("acquire", 3, 50),
    ]
    validate_wos_checkpoint(open_project(project.root), query.query_id)


def test_resume_probe_consumes_a_one_request_session_without_refetching_pages(tmp_path):
    project, queries, clock, provider = setup(tmp_path)
    query = queries[0]
    first, _ = session(project, query, clock, provider, budget=2)
    assert first.records_committed == 100
    clock.sleep(2)
    resumed, client = session(project, query, clock, provider, budget=1)
    assert client.requests_made == 1
    assert provider.calls[-1] == ("probe", 1, 1)
    assert resumed.records_committed == 100 and resumed.pages_committed == 2
    assert_clean_pause(project, query, resumed, 3)
    # Preserve pacing rather than inventing a 30-second source-error backoff.
    assert 0 < (datetime.fromisoformat(resumed.not_before_utc) - clock.now()).total_seconds() < 2
    calls = len(provider.calls)
    early, _ = session(project, query, clock, provider, budget=10)
    assert early.status == "paused" and len(provider.calls) == calls
    clock.sleep(2)
    final, _ = session(project, query, clock, provider, budget=10)
    assert final.enumeration_reconciled
    assert provider.calls.count(("acquire", 1, 50)) == 1
    assert provider.calls.count(("acquire", 2, 50)) == 1


def test_local_pause_preserves_preexisting_real_failure_count(tmp_path):
    project, queries, clock, provider = setup(tmp_path)
    query = queries[0]
    provider.fail_page = 2
    first, _ = session(project, query, clock, provider, budget=10)
    assert first.failures == 1 and first.records_committed == 50
    clock.sleep(121)
    provider.fail_page = None
    paused, _ = session(project, query, clock, provider, budget=1)
    assert paused.status == "paused" and paused.reason_code == "session_budget_reached"
    assert paused.failures == 1  # Do not increment OR erase the real failure.
    assert paused.requests_unknown == 0 and not paused.worker_active
    clock.sleep(2)
    final, _ = session(project, query, clock, provider, budget=10)
    assert final.enumeration_reconciled and final.failures == 0


@pytest.mark.parametrize("total,budget", [(0, 3), (1, 3), (50, 3), (103, 7)],
                         ids=["zero", "one", "one-page", "three-pages"])
def test_completion_on_last_allowed_request_is_not_downgraded_to_pause(tmp_path, total, budget):
    project, queries, clock, provider = setup(tmp_path, total=total)
    result, client = session(project, queries[0], clock, provider, budget=budget)
    assert result.enumeration_reconciled and result.status == "completed_with_warnings"
    assert result.records_committed == total and result.failures == 0
    assert client.requests_made == budget and client.requests_remaining == 0
    assert not result.worker_active and result.requests_unknown == 0


@pytest.mark.parametrize("status,code", [
    (401, "authentication_or_entitlement_denied"),
    (429, "quota_or_rate_limited"), (503, "http_error"),
], ids=["authentication", "rate-limit", "service-unavailable"])
def test_real_source_errors_at_budget_boundary_still_increment_failures(tmp_path, status, code):
    project, queries, clock, provider = setup(tmp_path)
    provider.fail_page = 1
    provider.error_status = status
    result, client = session(project, queries[0], clock, provider, budget=1)
    assert result.reason_code == code and result.failures == 1
    assert result.records_committed == 0 and not result.worker_active
    assert result.requests_reserved == result.requests_confirmed_attempted == 1
    assert result.requests_unknown == 0 and client.requests_remaining == 0


def test_real_quota_exhaustion_takes_precedence_over_local_budget_stop(tmp_path):
    project, queries, clock, provider = setup(tmp_path)
    provider.remaining = 1
    result, _ = session(project, queries[0], clock, provider, budget=1)
    assert result.reason_code == "quota_revalidation_required"
    assert result.quota["daily_remaining"] == 0
    assert result.records_committed == 50 and result.failures == 0
    clock.sleep(86400)
    provider.remaining = 5000
    blocked, _ = session(project, queries[0], clock, provider, budget=10)
    assert len(provider.calls) == 1 and not blocked.enumeration_reconciled
    final, _ = session(project, queries[0], clock, provider, budget=10, revalidate_quota=True)
    assert final.enumeration_reconciled


def test_server_delay_is_not_shortened_by_local_budget_boundary(tmp_path):
    project, queries, clock, provider = setup(tmp_path)
    def delayed(request, timeout):
        response = provider(request, timeout)
        return WoSHTTPResponse(response.status, {**response.headers, "Retry-After": "300"}, response.body)
    result, _ = session(project, queries[0], clock, delayed, budget=1)
    assert result.reason_code == "server_retry_after" and result.failures == 0
    assert (datetime.fromisoformat(result.not_before_utc) - clock.now()).total_seconds() >= 300
    clock.sleep(30)
    _, client = session(project, queries[0], clock, provider, budget=10)
    assert client.requests_made == 0 and len(provider.calls) == 1


def test_cancellation_at_budget_boundary_is_not_overwritten(tmp_path):
    project, queries, clock, provider = setup(tmp_path)
    provider.callback = lambda *_: pause_wos_checkpoint(project, queries[0].query_id, cancel=True)
    result, _ = session(project, queries[0], clock, provider, budget=1)
    assert result.status == "cancelled" and result.reason_code == "cancelled_by_user"
    assert result.failures == 0 and not result.worker_active


def test_remaining_client_budget_is_read_only_and_hard_transport_guard_remains(tmp_path):
    _, _, clock, provider = setup(tmp_path)
    client = client_for(clock, provider)
    assert client.requests_remaining == 3
    with pytest.raises(AttributeError):
        client.requests_remaining = 1000
    with pytest.raises(WoSStarterError, match="invalid_page"):
        client.fetch_page(QUERY, page=0)
    assert client.requests_remaining == 3 and provider.calls == []
    for page in range(1, 4):
        client.fetch_page(QUERY, page=page)
        assert client.requests_remaining == 3 - page
    with pytest.raises(WoSStarterError, match="request_budget_exhausted"):
        client.fetch_page(QUERY)
    assert client.requests_made == len(provider.calls) == 3


def test_failed_transport_attempt_consumes_local_allowance(tmp_path):
    _, _, clock, _ = setup(tmp_path)
    def offline_error(*_):
        raise OSError("synthetic offline transport failure")
    client = client_for(clock, offline_error)
    with pytest.raises(WoSStarterError, match="network_error"):
        client.fetch_page(QUERY)
    assert client.requests_made == 1 and client.requests_remaining == 2
