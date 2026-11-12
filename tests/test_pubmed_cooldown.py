"""Offline Retry-After tests on original ESearch and EFetch paths."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import json
import sqlite3
from types import SimpleNamespace
from urllib.error import HTTPError
from uuid import uuid4

import pytest

from research_y.projects import open_project
from research_y.pubmed_checkpoint_resume import resume_pubmed_checkpoint
from research_y.pubmed_cooldown import EVENT
from research_y.pubmed_metadata import PubMedEFetchClient, PubMedMetadataTransportError
from research_y.pubmed_metadata_store import collect_pubmed_metadata
from research_y.pubmed_probe import PubMedESearchProbeClient, PubMedProbeError, PubMedRetryNotDue
from test_pubmed_metadata import project_with_pmids, response, Q


NOW = datetime(2026, 11, 12, 20, 0, tzinfo=timezone.utc)


def client(now, transport=None):
    return PubMedESearchProbeClient(email="fixture@example.invalid", transport=transport,
                                    utcnow=lambda: now[0], clock=lambda: 1000., sleep=lambda _: None)


@pytest.mark.parametrize("header", ["60", format_datetime(NOW + timedelta(minutes=1), usegmt=True)])
def test_reopen_honors_efetch_backoff_across_both_endpoints(tmp_path, header):
    project, query_id = project_with_pmids(tmp_path, ("111",))
    moment = [NOW]
    sends = []
    def limit(req, timeout):
        sends.append("throttled")
        raise HTTPError(req.full_url, 429, "PRIVATE provider detail", {"Retry-After": header}, None)

    probe = client(moment)
    result = collect_pubmed_metadata(project, query_id, PubMedEFetchClient(probe, transport=limit))
    assert result.status == "incomplete" and sends == ["throttled"]
    with closing(sqlite3.connect(project.database_path)) as db:
        raw, = db.execute("SELECT details_json FROM audit_events WHERE event_type=?", (EVENT,)).fetchone()
        assert json.loads(raw) == {"retry_not_before_utc": (NOW + timedelta(minutes=1)).isoformat()}
    reopened = open_project(project.root)
    def search(req, timeout):
        sends.append("early search")
        raise AssertionError("ESearch contacted before its recorded deadline")
    def fetch(req, timeout):
        sends.append("allowed fetch")
        return response("111")

    resume_pubmed_checkpoint(reopened, query_id, client(moment, search))
    new_client = PubMedEFetchClient(client(moment), transport=fetch)
    paused = collect_pubmed_metadata(reopened, query_id, new_client)
    assert paused.status == "paused" and paused.missing_pmids == ("111",)
    assert sends == ["throttled"]
    moment[0] += timedelta(minutes=1)
    resumed = collect_pubmed_metadata(reopened, query_id, new_client)
    assert resumed.committed_metadata_ids == 1 and sends == ["throttled", "allowed fetch"]


def test_esearch_cooldown_also_protects_same_client_efetch():
    moment = [NOW]
    def search(req, timeout):
        raise HTTPError(req.full_url, 503, "private", {"Retry-After": "120"}, None)
    probe = client(moment, search)
    with pytest.raises(PubMedProbeError) as failure:
        probe.probe(Q)
    assert failure.value.http_status == 503
    with pytest.raises(PubMedMetadataTransportError, match="paused until"):
        PubMedEFetchClient(probe, transport=lambda *_: pytest.fail("early EFetch")).fetch(("111",))


@pytest.mark.parametrize("endpoint", ["search", "fetch"])
def test_successful_http_response_also_applies_provider_delay(monkeypatch, endpoint):
    from research_y import pubmed_metadata, pubmed_probe
    now = [NOW]
    probe = client(now)
    class Reply:
        headers = {"Retry-After": "30"}
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, bound):
            return response("111") if endpoint == "fetch" else b"{}"
    monkeypatch.setattr(pubmed_metadata if endpoint == "fetch" else pubmed_probe,
                        "build_opener", lambda *_: SimpleNamespace(open=lambda *args, **kwargs: Reply()))
    if endpoint == "fetch":
        PubMedEFetchClient(probe).fetch(("111",))
    else:
        probe.fetch_esearch_page(Q, retmax=0)
    with pytest.raises(PubMedRetryNotDue):
        probe.fetch_esearch_page(Q, retmax=0)


def test_fresh_pilot_receipt_waits_but_already_recorded_failure_can_be_reinspected(tmp_path):
    from research_y.pubmed_pilot import PubMedPilotError
    from test_pubmed_pilot import _call, _events, _fixture

    project, run_id, plan, query = _fixture(tmp_path)
    moment = [NOW]
    pilot_id = str(uuid4())
    def limit(req, timeout):
        raise HTTPError(req.full_url, 429, "private", {"Retry-After": "300"}, None)
    original = _call(project, run_id, plan, query, client(moment, limit), pilot_id=pilot_id)
    assert original["error_code"] == "provider_rate_limited"
    reopened = open_project(project.root)
    blocked = client(moment, lambda *_: pytest.fail("unexpected source call"))
    assert _call(reopened, run_id, plan, query, blocked, pilot_id=pilot_id) == original
    another_id = str(uuid4())
    with pytest.raises(PubMedPilotError, match="provider_cooldown"):
        _call(reopened, run_id, plan, query, blocked, pilot_id=another_id)
    assert _events(reopened, another_id) == []
