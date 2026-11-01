"""Malformed quota observations must stop safely without faking a worker crash."""
from contextlib import closing
from dataclasses import asdict, replace
import json
import sqlite3

import pytest

from research_y.wos_checkpoint_store import (
    WoSCheckpointError, _checked_page, _read_observation,
    inspect_wos_checkpoint, validate_wos_checkpoint,
)
from research_y.wos_starter import parse_document_page
from research_y.wos_starter_client import WoSHTTPResponse


QUERY = 'TS=("ECMO")'
VALID_HEADERS = {
    "X-RateLimit-Limit-Day": "5000",
    "X-RateLimit-Remaining-Day": "4999",
}


def _page(headers):
    body = {"metadata": {"total": 1, "page": 1, "limit": 1},
            "hits": [{"uid": "WOS:000000000000001", "title": "Synthetic"}]}
    return parse_document_page(
        json.dumps(body).encode(), exact_query=QUERY, database="WOS",
        requested_page=1, requested_limit=1,
        retrieved_at_utc="2026-11-01T00:00:00+00:00", headers=headers,
    )


@pytest.mark.parametrize("headers", [
    pytest.param(VALID_HEADERS, id="valid"),
    pytest.param({**VALID_HEADERS, "X-RateLimit-Remaining-Day": "0"}, id="exhausted"),
    pytest.param({}, id="absent"),
    pytest.param({"X-RateLimit-Limit-Day": "5000"}, id="remaining-absent"),
    pytest.param({**VALID_HEADERS, "X-RateLimit-Remaining-Day": "invalid"}, id="malformed"),
    pytest.param({**VALID_HEADERS, "X-RateLimit-Limit-Day": "-1"}, id="negative-limit"),
    pytest.param({**VALID_HEADERS, "X-RateLimit-Limit-Second": "0"}, id="zero-rate"),
    pytest.param({**VALID_HEADERS, "x-ratelimit-limit-day": "50"}, id="conflicting-case"),
])
def test_quota_round_trip_preserves_parser_state(headers):
    original = _page(headers)
    checked = _checked_page(original)
    assert checked == original
    assert checked.quota == original.quota
    assert checked.response_json == original.response_json
    assert checked.response_sha256 == original.response_sha256
    assert checked.quota.can_continue == original.quota.can_continue


@pytest.mark.parametrize("altered", [
    pytest.param({"reported_matches": 2}, id="changed-count"),
    pytest.param({"response_sha256": "0" * 64}, id="changed-digest"),
])
def test_invalid_quota_does_not_bypass_page_integrity_checks(altered):
    original = _page({**VALID_HEADERS, "X-RateLimit-Remaining-Day": "invalid"})
    assert original.quota.valid is False
    with pytest.raises(WoSCheckpointError, match="inconsistent_page_object"):
        _checked_page(replace(original, **altered))


@pytest.mark.parametrize("quota_state", ["malformed", "absent"])
@pytest.mark.parametrize("target,pages_before_stop", [
    pytest.param(("acquire", 1, 50), 0, id="initial-acquisition"),
    pytest.param(("acquire", 2, 50), 1, id="later-acquisition"),
    pytest.param(("probe", 1, 1), 1, id="resume-probe"),
    pytest.param(("verify", 2, 50), 3, id="verification"),
    pytest.param(("final", 1, 1), 3, id="final-probe"),
])
def test_unverified_quota_is_durable_and_recoverable(
    tmp_path, target, pages_before_stop, quota_state,
):
    from test_wos_checkpoints import setup, execute
    from research_y.projects import open_project

    project, queries, clock, source = setup(tmp_path)
    query = queries[0]
    if target[0] == "probe":
        first = execute(project, query, clock, source, max_requests=1)
        assert first.pages_committed == 1
        clock.sleep(2)

    def transport(request, timeout):
        response = source(request, timeout)
        if source.calls[-1] == target:
            headers = ({} if quota_state == "absent" else
                       {**response.headers, "X-RateLimit-Remaining-Day": "invalid"})
            return WoSHTTPResponse(response.status, headers, response.body)
        return response

    stopped = execute(project, query, clock, transport)
    assert stopped.status == "incomplete"
    assert stopped.reason_code == "entitlement_unverified"
    assert stopped.quota["valid"] is (quota_state == "absent")
    assert stopped.pages_committed == pages_before_stop
    assert stopped.records_committed == min(50 * pages_before_stop, 103)
    assert stopped.worker_active is False
    assert stopped.requests_unknown == 0
    assert not stopped.enumeration_reconciled and not stopped.source_retrieval_verified
    reopened = open_project(project.root)
    assert inspect_wos_checkpoint(reopened, query.query_id) == stopped
    validate_wos_checkpoint(reopened, query.query_id)

    with closing(sqlite3.connect(project.database_path)) as db:
        db.row_factory = sqlite3.Row
        last = db.execute(
            "SELECT * FROM wos_checkpoint_attempts WHERE query_id=? "
            "ORDER BY started_at_utc DESC LIMIT 1", (query.query_id,),
        ).fetchone()
        # Transport success is recorded without claiming a usable page/quota.
        assert (last["outcome"], last["sent"], last["http_status"]) == ("success", 1, 200)
        observed = _read_observation(db, last["attempt_id"], query.query_id, target[0])
        assert asdict(observed.quota) == stopped.quota
        assert observed.reported_matches == 103
        assert db.execute(
            "SELECT COUNT(*) FROM wos_checkpoint_attempts WHERE outcome='started'"
        ).fetchone()[0] == 0
        assert db.execute(
            "SELECT status FROM source_queries WHERE query_id=?", (query.query_id,),
        ).fetchone()[0] == "incomplete"

    before_retry = len(source.calls)
    clock.sleep(60)
    still_stopped = execute(reopened, query, clock, source)
    assert still_stopped.reason_code == "entitlement_unverified"
    assert len(source.calls) == before_retry  # No automatic entitlement guess/retry.
    recovered = execute(reopened, query, clock, source, revalidate_quota=True)
    assert recovered.enumeration_reconciled and recovered.records_committed == 103
    assert recovered.requests_unknown == 0 and not recovered.worker_active
    resumed_calls = source.calls[before_retry:]
    assert not any(purpose == "acquire" and page <= pages_before_stop
                   for purpose, page, size in resumed_calls)
