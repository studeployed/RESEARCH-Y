"""Opt-in live PubMed >10,000-ID and durable interruption/reopen acceptance.

Run only through the manual GitHub Actions workflow after researcher approval.
Stages run as distinct Python processes on one ephemeral, local SQLite project.
This script never calls EFetch or marks a source search completed_verified.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Callable
from urllib.parse import parse_qs
from urllib.request import Request
from zoneinfo import ZoneInfo

from research_y.projects import create_project, open_project, _validated_project_connection
from research_y.pubmed_checkpoint_resume import (
    resume_pubmed_checkpoint, start_checkpointed_pubmed_retrieval,
)
from research_y.pubmed_checkpoint_store import (
    inspect_pubmed_checkpoint, pause_pubmed_checkpoint,
)
from research_y.pubmed_partition import DateWindow
from research_y.pubmed_probe import (
    ESEARCH_URL, PubMedESearchProbeClient, _read_http,
)
from research_y.query_compiler import compile_source
from research_y.storage import (
    ApprovedTerm, StrategyGroup, approve_strategy, create_search_run,
    get_strategy_snapshot, plan_source_query,
)

QUERY = '("ECMO"[All Fields])'
PROJECT_FOLDER = "controlled-ecmo"
STATE_FILENAME = "validation-state.json"
EVIDENCE_FILENAME = "identifier-evidence.json"
MINIMUM_LIVE_MATCHES = 10_001
MAXIMUM_LIVE_MATCHES = 30_000
PAGE_SIZE = 500
MAX_COUNT_PROBES = 64
MAX_REQUESTS_PER_PROCESS = 160
WINDOW_START = date(1900, 1, 1)


class ValidationFailure(ValueError):
    """A verification requirement could not be established; never assume zero hits."""


def off_peak_utc(instant: datetime) -> bool:
    """NCBI recommends large weekday jobs only 21:00–05:00 US Eastern."""
    if instant.tzinfo is None:
        raise ValueError("A timezone-aware clock is required")
    eastern = instant.astimezone(ZoneInfo("America/New_York"))
    return eastern.weekday() >= 5 or eastern.hour >= 21 or eastern.hour < 5


def _write_json(path: Path, value: dict[str, object]) -> None:
    """Replace a newly allocated diagnostic JSON file atomically."""
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8")
    temp.replace(path)


def _read_state(workspace: Path) -> dict[str, object]:
    data = json.loads((workspace / STATE_FILENAME).read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or data.get("query") != QUERY
            or data.get("project_folder") != PROJECT_FOLDER
            or not isinstance(data.get("query_id"), str)
            or not isinstance(data.get("first_page_sha256"), str)):
        raise ValidationFailure("Saved diagnostic identity could not be verified")
    return data


def _first_page(project, query_id: str) -> dict[str, object]:
    with _validated_project_connection(project) as connection:
        row = connection.execute(
            "SELECT page_json, page_sha256 FROM pubmed_checkpoint_pages "
            "WHERE query_id=? ORDER BY partition_index, retstart LIMIT 1",
            (query_id,),
        ).fetchone()
    if row is None:
        raise ValidationFailure("No committed first identifier page")
    page = json.loads(row[0])
    return {
        "query": page["exact_query"],
        "offset": page["retstart"],
        "sha256": row[1],
    }


class GuardedESearchTransport:
    """Finite, fixed-endpoint requests, with optional controlled first-page pause."""

    def __init__(
        self, *, backend: Callable[[Request, float], bytes] = _read_http,
        project=None, query_id: str | None = None,
        pause_on_first_page: bool = False,
        forbidden_page: tuple[str, int] | None = None,
        request_budget: int = MAX_REQUESTS_PER_PROCESS,
    ):
        self.backend = backend
        self.project = project
        self.query_id = query_id
        self.pause_on_first_page = pause_on_first_page
        self.forbidden_page = forbidden_page
        self.request_budget = request_budget
        self.requests = 0
        self.page_requests: list[tuple[str, int]] = []
        self._paused = False
        self.forbidden_attempt = False

    def __call__(self, request: Request, timeout: float) -> bytes:
        if request.full_url != ESEARCH_URL or request.get_method() != "POST":
            raise ValidationFailure("Unexpected diagnostic source endpoint")
        # POST fields include private contact/key values. Never print these.
        fields = parse_qs(request.data.decode("utf-8"))
        if fields.get("db") != ["pubmed"] or fields.get("retmode") != ["json"]:
            raise ValidationFailure("Unexpected diagnostic request parameters")
        query = fields["term"][0]
        offset = int(fields.get("retstart", ["0"])[0])
        size = int(fields["retmax"][0])
        identity = (query, offset)
        if size > 0 and identity == self.forbidden_page:
            self.forbidden_attempt = True
            raise ValidationFailure("Previously committed page would be refetched")
        self.requests += 1
        if self.requests > self.request_budget:
            raise OSError("Live diagnostic request budget reached")
        payload = self.backend(request, timeout)
        if size > 0:
            self.page_requests.append(identity)
            if self.pause_on_first_page and not self._paused:
                if self.project is None or self.query_id is None:
                    raise ValidationFailure("Cannot pause without a durable project")
                # Pause occurs while the first real provider page is in flight;
                # production commits it atomically, then stops the next fetch.
                pause_pubmed_checkpoint(self.project, self.query_id)
                self._paused = True
        return payload


def _configured_client(
    contact: str, key: str | None, transport: GuardedESearchTransport,
) -> PubMedESearchProbeClient:
    return PubMedESearchProbeClient(email=contact, api_key=key, transport=transport)


def _safe_summary(stage: str, snapshot, *, requests: int, error: str | None = None):
    return {
        "stage": stage, "status": snapshot.stored_status,
        "reported_matches": snapshot.root_count,
        "retrieved_unique_pmids": len(snapshot.pmids),
        "pages_committed": snapshot.pages_committed,
        "pages_expected": snapshot.pages_expected,
        "identifiers_reconciled": snapshot.identifiers_reconciled,
        "source_retrieval_verified": False,
        "source_requests": requests,
        "reason": error,
    }


def start_phase(
    workspace: Path, *, contact: str, api_key: str | None,
    transport: Callable[[Request, float], bytes] = _read_http,
    utc_now: datetime | None = None,
    enforce_off_peak: bool = True,
    min_matches: int = MINIMUM_LIVE_MATCHES,
    max_matches: int = MAXIMUM_LIVE_MATCHES,
    request_budget: int = MAX_REQUESTS_PER_PROCESS,
) -> dict[str, object]:
    """Use genuine source pages; stop after first *durably committed* page."""
    now = utc_now or datetime.now(timezone.utc)
    if enforce_off_peak and not off_peak_utc(now):
        raise ValidationFailure(
            "NCBI recommends large live retrievals during weekends or "
            "21:00–05:00 US Eastern; no source requests made"
        )
    workspace.mkdir(parents=True, mode=0o700, exist_ok=False)
    guard = GuardedESearchTransport(backend=transport, request_budget=request_budget)
    client = _configured_client(contact, api_key, guard)
    pilot = client.probe(QUERY)
    if pilot.review_required:
        raise ValidationFailure("Live root accepted translation needs review")
    if not min_matches <= pilot.reported_matches <= max_matches:
        raise ValidationFailure("Source count outside approved large-test bounds")

    project = create_project(workspace, "PubMed live identifier validation",
                             directory_name=PROJECT_FOLDER)
    version = approve_strategy(
        project, theme="Public generic ECMO source acceptance diagnostic",
        approved_by="Explicit manual workflow dispatch",
        approval_confirmed=True,
        groups=(StrategyGroup(
            "g1", "ECMO",
            (ApprovedTerm("ECMO", "researcher", True),),
        ),),
    )
    run = create_search_run(project, version.strategy_version_id)
    compiled = compile_source(get_strategy_snapshot(project, version.strategy_version_id),
                              "pubmed")
    if (len(compiled.groups) != 1 or len(compiled.groups[0].chunks) != 1
            or compiled.groups[0].chunks[0].exact_query != QUERY):
        raise ValidationFailure("Compiled broad-query identity changed")
    pending = plan_source_query(
        project, run_id=run.run_id, group_id="g1",
        source_name="pubmed", exact_query=QUERY,
        parameters={"test_only": True, "source_filters": "none"},
    )
    window = DateWindow(WINDOW_START, now.date() + timedelta(days=1))
    guard.project = project
    guard.query_id = pending.query_id
    guard.pause_on_first_page = True
    result = start_checkpointed_pubmed_retrieval(
        project, pending.query_id, client,
        date_window=window, page_size=PAGE_SIZE,
        max_count_probes=MAX_COUNT_PROBES,
    )
    try:
        snapshot = inspect_pubmed_checkpoint(project, pending.query_id)
    except KeyError:
        _write_json(workspace / EVIDENCE_FILENAME, {
            "stage": "durable_pause", "status": "incomplete",
            "reported_matches": pilot.reported_matches,
            "retrieved_unique_pmids": 0, "pages_committed": 0,
            "source_requests": guard.requests,
            "reason": result.error or "No verified immutable partition plan",
            "source_retrieval_verified": False,
            "metadata_acquired": False,
        })
        raise ValidationFailure("No verified partition plan was established") from None
    summary = _safe_summary("durable_pause", snapshot, requests=guard.requests,
                            error=result.error)
    if (result.status != "paused" or snapshot.stored_status != "paused"
            or snapshot.pages_committed != 1 or snapshot.identifiers_reconciled
            or snapshot.root_count != pilot.reported_matches
            or not guard._paused):
        _write_json(workspace / EVIDENCE_FILENAME, {
            **summary, "metadata_acquired": False,
            "identifiers_reconciled": False,
        })
        raise ValidationFailure("Source plan or one-page pause was not established")

    first = _first_page(project, pending.query_id)
    state = {
        "query": QUERY, "query_id": pending.query_id,
        "project_folder": PROJECT_FOLDER, "first_page_sha256": first["sha256"],
        "first_page_query": first["query"], "first_page_offset": first["offset"],
        "baseline_count": snapshot.root_count,
        "date_start": window.start.isoformat(), "date_end": window.end.isoformat(),
        "created_at_utc": now.isoformat(),
    }
    _write_json(workspace / STATE_FILENAME, state)
    summary.update({
        "date_start": state["date_start"], "date_end": state["date_end"],
        "first_page_response_hash_verified": True,
    })
    return summary


def _evidence_from_db(project, query_id: str, snapshot) -> dict[str, object]:
    with _validated_project_connection(project) as connection:
        row = connection.execute(
            "SELECT plan_json,plan_sha256 FROM pubmed_checkpoint_runs WHERE query_id=?",
            (query_id,),
        ).fetchone()
        pages = connection.execute(
            "SELECT page_json,page_sha256 FROM pubmed_checkpoint_pages "
            "WHERE query_id=? ORDER BY partition_index,retstart", (query_id,),
        ).fetchall()
        source_status = connection.execute(
            "SELECT status FROM source_queries WHERE query_id=?", (query_id,),
        ).fetchone()[0]
    plan = json.loads(row[0])
    part = [{
        "index": p["index"], "parent_index": p["parent_index"],
        "start": p["start"], "end": p["end"],
        "reported_matches": p["reported_matches"],
        "decision": p["decision"], "depth": p["depth"],
    } for p in plan["partitions"]]
    page_audit = []
    for encoded, digest in pages:
        p = json.loads(encoded)
        page_audit.append({
            "partition_index": p["partition_index"], "retstart": p["retstart"],
            "retmax": p["retmax"], "reported_matches": p["reported_matches"],
            "accepted_translation": p["accepted_translation"],
            "response_sha256": p["response_sha256"],
            "checkpoint_sha256": digest,
            "exact_query": p["exact_query"],
            "retrieved_at_utc": p["retrieved_at_utc"],
            # PMIDs in this fixed, public diagnostic are public identifiers,
            # not copyrighted abstracts; retain them to audit the true union.
            "pmids": p["pmids"],
        })
    return {
        "query": QUERY, "reported_matches": snapshot.root_count,
        "retrieved_unique_pmids": len(snapshot.pmids),
        "pmid_union_sha256": sha256(
            "\n".join(sorted(snapshot.pmids)).encode("ascii")
        ).hexdigest(),
        "pages_committed": snapshot.pages_committed,
        "pages_expected": snapshot.pages_expected,
        "partition_plan_sha256": row[1],
        "partitions": part, "pages": page_audit,
        "source_query_status": source_status,
        "identifiers_reconciled": snapshot.identifiers_reconciled,
        "source_retrieval_verified": False,
        "metadata_acquired": False,
    }


def resume_phase(
    workspace: Path, *, contact: str, api_key: str | None,
    transport: Callable[[Request, float], bytes] = _read_http,
    utc_now: datetime | None = None,
    enforce_off_peak: bool = True,
    request_budget: int = MAX_REQUESTS_PER_PROCESS,
) -> dict[str, object]:
    """Reopen SQLite in a separate process; never refetch the committed page."""
    now = utc_now or datetime.now(timezone.utc)
    if enforce_off_peak and not off_peak_utc(now):
        raise ValidationFailure("Live resumption outside the recommended NCBI off-peak window")
    state = _read_state(workspace)
    project = open_project(workspace / PROJECT_FOLDER)
    query_id = state["query_id"]
    before = inspect_pubmed_checkpoint(project, query_id)
    first = _first_page(project, query_id)
    if (before.pages_committed < 1 or
            first["sha256"] != state["first_page_sha256"] or
            first["query"] != state["first_page_query"] or
            first["offset"] != state["first_page_offset"] or
            before.root_count != state["baseline_count"]):
        raise ValidationFailure("The previously committed checkpoint has changed")

    guard = GuardedESearchTransport(
        backend=transport,
        forbidden_page=(state["first_page_query"], state["first_page_offset"]),
        request_budget=request_budget,
    )
    client = _configured_client(contact, api_key, guard)
    result = resume_pubmed_checkpoint(project, query_id, client)
    snapshot = inspect_pubmed_checkpoint(project, query_id)
    first_after = _first_page(project, query_id)
    evidence = _evidence_from_db(project, query_id, snapshot)
    evidence.update({
        "stage": "resumed", "utc_time": now.isoformat(),
        "commit_sha": os.environ.get("GITHUB_SHA"),
        "status": result.status,
        "reason": result.error,
        "source_requests": guard.requests,
        "new_page_requests": len(guard.page_requests),
        "first_page_unchanged": first_after["sha256"] == state["first_page_sha256"],
        "replayed_committed_page": guard.forbidden_attempt,
        "date_start": state["date_start"], "date_end": state["date_end"],
    })
    ok = (
        result.status == "identifiers_reconciled_metadata_pending"
        and snapshot.identifiers_reconciled
        and snapshot.pages_committed == snapshot.pages_expected
        and len(snapshot.pmids) == snapshot.root_count
        and len(set(snapshot.pmids)) == snapshot.root_count
        and snapshot.root_count > 10_000
        and evidence["first_page_unchanged"]
        and not guard.forbidden_attempt
        and evidence["source_query_status"] == "incomplete"
        and not result.source_retrieval_verified
    )
    evidence["identifier_acceptance_passed"] = bool(ok)
    _write_json(workspace / EVIDENCE_FILENAME, evidence)
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("start", "resume"))
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args(argv)
    contact = os.environ.get("RESEARCHY_NCBI_CONTACT_EMAIL")
    if not contact:
        print("Not run: configure the private NCBI contact secret.", file=sys.stderr)
        return 2
    try:
        if args.stage == "start":
            result = start_phase(args.workspace, contact=contact,
                                 api_key=os.environ.get("RESEARCHY_NCBI_API_KEY") or None)
        else:
            result = resume_phase(args.workspace, contact=contact,
                                  api_key=os.environ.get("RESEARCHY_NCBI_API_KEY") or None)
        # Print only aggregate counts/flags; the permitted detailed audit is
        # saved as an independent, credential-free JSON artifact.
        keys = ("stage", "status", "reported_matches", "retrieved_unique_pmids",
                "pages_committed", "pages_expected", "identifiers_reconciled",
                "identifier_acceptance_passed", "source_retrieval_verified",
                "source_query_status", "source_requests", "new_page_requests", "reason")
        print(json.dumps({k: result[k] for k in keys if k in result},
                         sort_keys=True, ensure_ascii=False))
        return 0 if args.stage == "start" or result["identifier_acceptance_passed"] else 3
    except Exception:
        # Never publish provider exceptions, paths, contact addresses or keys.
        print("Live identifier validation incomplete; inspect sanitized evidence and "
              "recheck the provider, date range and checkpoint.", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
