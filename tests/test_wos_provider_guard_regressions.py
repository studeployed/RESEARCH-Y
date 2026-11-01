"""Provider restrictions survive query switches, user pauses and recovery."""
from datetime import datetime

import pytest

from research_y.projects import open_project
from research_y.wos_checkpoint_store import (
    inspect_wos_checkpoint, pause_wos_checkpoint, recover_wos_worker,
    validate_wos_checkpoint,
)
from research_y.wos_starter_client import WoSHTTPResponse
from test_wos_checkpoints import KEY, setup, execute


def assert_no_new_request(project, query, clock, provider, calls, **options):
    result = execute(open_project(project.root), query, clock, provider, **options)
    assert len(provider.calls) == calls
    assert not result.worker_active and result.requests_unknown == 0
    assert not result.enumeration_reconciled
    return result


@pytest.mark.parametrize("mode", ["success", "http-error", "invalid-body", "credential-echo"])
def test_retry_after_is_shared_across_queries_and_fresh_clients(tmp_path, mode):
    p, qs, c, s = setup(tmp_path, second_group=True)
    def restricted(req, timeout):
        reply = s(req, timeout)
        status, body = reply.status, reply.body
        if mode == "http-error":
            status, body = 503, b"private provider error"
        elif mode == "invalid-body":
            body = b"not JSON"
        elif mode == "credential-echo":
            import json
            value = json.loads(body)
            value["hits"][0]["unexpected"] = KEY
            body = json.dumps(value).encode()
        return WoSHTTPResponse(status, {**reply.headers, "Retry-After": "300"}, body)
    first = execute(p, qs[0], c, restricted, max_requests=1)
    assert first.not_before_utc is not None and len(s.calls) == 1
    second = assert_no_new_request(p, qs[1], c, s, 1, revalidate_quota=True)
    assert second.status == "paused" and second.reason_code == "provider_cooldown"
    assert second.requests_reserved == 0 and second.failures == 0
    assert second.not_before_utc == first.not_before_utc
    c.sleep(299)
    assert_no_new_request(p, qs[1], c, s, 1, revalidate_quota=True)
    c.sleep(2)
    assert execute(p, qs[1], c, s).enumeration_reconciled
    validate_wos_checkpoint(open_project(p.root), qs[1].query_id)


@pytest.mark.parametrize("origin", ["cancelled", "completed"])
def test_cancelled_and_completed_queries_keep_provider_cooldown(tmp_path, origin):
    p, qs, c, s = setup(tmp_path, total=1, second_group=True)
    def restricted(req, timeout):
        reply = s(req, timeout)
        delay = origin == "cancelled" or s.calls[-1][0] == "final"
        return WoSHTTPResponse(reply.status, {**reply.headers, **({"Retry-After": "300"} if delay else {})}, reply.body)
    first = execute(p, qs[0], c, restricted)
    if origin == "cancelled":
        pause_wos_checkpoint(p, qs[0].query_id, cancel=True)
    else:
        assert first.enumeration_reconciled
    calls = len(s.calls)
    blocked = assert_no_new_request(p, qs[1], c, s, calls, revalidate_quota=True)
    assert blocked.reason_code == "provider_cooldown"
    c.sleep(301)
    assert execute(p, qs[1], c, s).enumeration_reconciled


def test_cross_query_pacing_is_not_reset_by_new_client(tmp_path):
    p, qs, c, s = setup(tmp_path, second_group=True)
    first = execute(p, qs[0], c, s, max_requests=1)
    blocked = assert_no_new_request(p, qs[1], c, s, 1)
    assert blocked.reason_code == "provider_cooldown"
    assert blocked.not_before_utc == first.not_before_utc
    c.sleep(2)
    assert execute(p, qs[1], c, s).enumeration_reconciled


@pytest.mark.parametrize("delay", [0, 5, 7200], ids=["no-header", "short-delay", "long-delay"])
@pytest.mark.parametrize("cancel", [False, True], ids=["normal", "inflight-cancel"])
def test_exhausted_quota_uses_longest_delay_and_requires_shared_revalidation(tmp_path, delay, cancel):
    p, qs, c, s = setup(tmp_path, second_group=True)
    s.remaining = 1
    if cancel:
        s.callback = lambda *_: pause_wos_checkpoint(p, qs[0].query_id, cancel=True)
    def exhausted(req, timeout):
        reply = s(req, timeout)
        headers = {**reply.headers, **({"Retry-After": str(delay)} if delay else {})}
        return WoSHTTPResponse(reply.status, headers, reply.body)
    first = execute(p, qs[0], c, exhausted)
    expected = max(3600, delay)
    assert (datetime.fromisoformat(first.not_before_utc) - c.now()).total_seconds() == expected
    assert first.records_committed == 50 and first.quota["daily_remaining"] == 0
    assert first.status == ("cancelled" if cancel else "paused")
    if not cancel:
        assert first.reason_code == "quota_revalidation_required"
    assert_no_new_request(p, qs[1], c, s, 1, revalidate_quota=True)
    c.sleep(6)
    assert_no_new_request(p, qs[1], c, s, 1, revalidate_quota=True)
    c.sleep(expected - 5)
    s.callback = None
    s.remaining = 5000
    blocked = assert_no_new_request(p, qs[1], c, s, 1)
    assert blocked.reason_code == "provider_quota_revalidation_required"
    assert execute(p, qs[1], c, s, revalidate_quota=True).enumeration_reconciled


@pytest.mark.parametrize("delay", [0, 5, 7200], ids=["no-header", "short-delay", "long-delay"])
def test_final_success_can_finish_but_preserves_exhausted_quota_for_other_queries(tmp_path, delay):
    p, qs, c, s = setup(tmp_path, total=1, second_group=True)
    def exhaust_final(req, timeout):
        reply = s(req, timeout)
        if s.calls[-1][0] == "final":
            headers = {**reply.headers, "X-RateLimit-Remaining-Day": "0"}
            if delay:
                headers["Retry-After"] = str(delay)
            return WoSHTTPResponse(200, headers, reply.body)
        return reply
    done = execute(p, qs[0], c, exhaust_final)
    assert done.enumeration_reconciled
    assert (datetime.fromisoformat(done.not_before_utc) - c.now()).total_seconds() == max(3600, delay)
    calls = len(s.calls)
    assert_no_new_request(p, qs[1], c, s, calls, revalidate_quota=True)
    c.sleep(max(3600, delay) + 1)
    assert_no_new_request(p, qs[1], c, s, calls)
    assert execute(p, qs[1], c, s, revalidate_quota=True).enumeration_reconciled


def test_failed_revalidation_does_not_clear_shared_exhausted_quota(tmp_path):
    p, qs, c, s = setup(tmp_path, second_group=True)
    s.remaining = 1
    assert execute(p, qs[0], c, s).quota["daily_remaining"] == 0
    c.sleep(3601)
    s.remaining = 5000
    def unavailable(req, timeout):
        s(req, timeout)
        raise OSError("synthetic network interruption")
    failed = execute(p, qs[1], c, unavailable, revalidate_quota=True)
    assert failed.failures == 1 and len(s.calls) == 2
    c.sleep(31)
    assert_no_new_request(p, qs[1], c, s, 2)
    assert execute(p, qs[1], c, s, revalidate_quota=True).enumeration_reconciled


def test_fresh_positive_quota_observation_releases_shared_exhaustion(tmp_path):
    p, qs, c, s = setup(tmp_path, second_group=True)
    s.remaining = 1
    execute(p, qs[0], c, s)
    c.sleep(3601)
    s.remaining = 5000
    revalidated = execute(p, qs[0], c, s, max_requests=1, revalidate_quota=True)
    assert revalidated.quota["daily_remaining"] > 0
    c.sleep(2)
    assert execute(p, qs[1], c, s).enumeration_reconciled


def make_consistency_failure(p, qs, c, s, kind):
    if kind == "source_count_changed":
        execute(p, qs[0], c, s, max_requests=1)
        c.sleep(2)
        s.change_count = True
    elif kind == "source_identity_changed":
        def swap(state):
            if state.stage == "verify":
                s.swap_uid = True
        return qs[0], execute(p, qs[0], c, s, on_progress=swap)
    elif kind == "cross_page_duplicate":
        def duplicate(body):
            if body["metadata"]["page"] == 2:
                body["hits"][0]["uid"] = "WOS:000000000000001"
        s.response_mutator = duplicate
    else:
        assert kind == "source_record_conflict"
        execute(p, qs[0], c, s)
        c.sleep(2)
        s.title = "Conflicting source observation"
        return qs[1], execute(p, qs[1], c, s)
    return qs[0], execute(p, qs[0], c, s)


@pytest.mark.parametrize("kind", ["source_count_changed", "source_identity_changed", "cross_page_duplicate", "source_record_conflict"])
@pytest.mark.parametrize("operation", ["pause", "recover", "cancel"])
def test_source_consistency_failure_cannot_be_cleared_by_user_control(tmp_path, kind, operation):
    p, qs, c, s = setup(tmp_path, second_group=True)
    query, failed = make_consistency_failure(p, qs, c, s, kind)
    assert failed.status == "incomplete" and failed.reason_code == kind
    calls = len(s.calls)
    s.change_count, s.swap_uid, s.response_mutator, s.title = False, False, None, "Synthetic title"
    if operation == "recover":
        recover_wos_worker(p, query.query_id, previous_worker_stopped=True)
    else:
        pause_wos_checkpoint(p, query.query_id, cancel=(operation == "cancel"))
    saved = inspect_wos_checkpoint(open_project(p.root), query.query_id)
    assert saved.reason_code == kind
    assert saved.status == ("cancelled" if operation == "cancel" else "incomplete")
    assert saved.records_committed == failed.records_committed
    c.sleep(86400)
    result = assert_no_new_request(p, query, c, s, calls, revalidate_quota=True)
    assert result.reason_code == kind
    validate_wos_checkpoint(open_project(p.root), query.query_id)


def test_repeated_pause_preserves_failure_observed_while_already_paused(tmp_path):
    p, qs, c, s = setup(tmp_path)
    def stop_and_change(purpose, page, limit):
        if purpose == "acquire" and page == 2:
            pause_wos_checkpoint(p, qs[0].query_id)
            s.change_count = True
    s.callback = stop_and_change
    failed = execute(p, qs[0], c, s)
    assert failed.status == "paused" and failed.reason_code == "source_count_changed"
    pause_wos_checkpoint(p, qs[0].query_id)
    recover_wos_worker(p, qs[0].query_id, previous_worker_stopped=True)
    s.callback, s.change_count = None, False
    c.sleep(86400)
    assert_no_new_request(p, qs[0], c, s, 2, revalidate_quota=True)
    assert inspect_wos_checkpoint(p, qs[0].query_id).reason_code == "source_count_changed"


def test_pausing_unverified_entitlement_does_not_grant_ordinary_resume(tmp_path):
    p, qs, c, s = setup(tmp_path)
    def missing_headers(req, timeout):
        reply = s(req, timeout)
        return WoSHTTPResponse(200, {}, reply.body)
    failed = execute(p, qs[0], c, missing_headers)
    assert failed.reason_code == "entitlement_unverified"
    pause_wos_checkpoint(p, qs[0].query_id)
    recover_wos_worker(p, qs[0].query_id, previous_worker_stopped=True)
    c.sleep(3601)
    result = assert_no_new_request(p, qs[0], c, s, 1)
    assert result.status == "incomplete" and result.reason_code == "entitlement_unverified"
    assert execute(p, qs[0], c, s, revalidate_quota=True).enumeration_reconciled
