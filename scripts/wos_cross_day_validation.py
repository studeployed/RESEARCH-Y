"""Manual two-process Starter recovery sample spanning actual UTC dates."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from uuid import UUID

from research_y.projects import open_project, _validated_project_connection
from research_y.wos_checkpoint_runner import run_wos_checkpoint
from research_y.wos_checkpoint_store import inspect_wos_checkpoint, validate_wos_checkpoint
from research_y.wos_starter_client import WoSStarterClient
from scripts.wos_checkpoint_validation import PROJECT, _save, create_diagnostic_checkpoint

STATE = "cross-day-state.json"
EVIDENCE = "cross-day-evidence.json"


def _utcnow():
    return datetime.now(timezone.utc)


def _evidence(project, query_id):
    validate_wos_checkpoint(project, query_id)
    state = inspect_wos_checkpoint(project, query_id)
    with _validated_project_connection(project) as db:
        pages = db.execute(
            "SELECT page_number,attempt_id,uid_sha256 FROM wos_checkpoint_pages "
            "WHERE query_id=? ORDER BY page_number", (query_id,)).fetchall()
        rows = db.execute(
            "SELECT a.purpose,a.page_number,a.page_size,a.started_at_utc,a.outcome,a.sent,"
            "o.descriptor_json FROM wos_checkpoint_attempts a LEFT JOIN wos_checkpoint_observations o "
            "ON o.attempt_id=a.attempt_id WHERE a.query_id=? ORDER BY a.started_at_utc,a.attempt_id",
            (query_id,)).fetchall()
    attempts = []
    for purpose, number, size, stamp, outcome, sent, descriptor in rows:
        if outcome != "success" or sent != 1 or descriptor is None:
            raise ValueError("incomplete_request_evidence")
        observation = json.loads(descriptor)
        quota = observation["quota"]
        limit = quota["daily_limit"]
        remaining = quota["daily_remaining"]
        if (quota["valid"] is not True or type(limit) is not int or limit < 5000 or
                type(remaining) is not int or not 0 <= remaining <= limit):
            raise ValueError("institutional_quota_unverified")
        day = datetime.fromisoformat(stamp).astimezone(timezone.utc).date().isoformat()
        observed_day = datetime.fromisoformat(observation["retrieved_at_utc"]).astimezone(timezone.utc).date().isoformat()
        if observed_day != day:
            raise ValueError("request_straddled_utc_date")
        attempts.append((purpose, number, size, day, remaining, limit))
    return state, pages, attempts


def _first_day(state, pages, attempts):
    if not 1 <= len(pages) <= 2 or len(attempts) != len(pages):
        raise ValueError("first_day_evidence_invalid")
    if (state.status != "paused" or state.reported_matches is None or
            state.reported_matches <= 50 * len(pages) or state.records_committed != 50 * len(pages) or
            len({row[3] for row in attempts}) != 1 or
            [row[:3] for row in attempts] != [("acquire", number, 50) for number in range(1, len(pages)+1)]):
        raise ValueError("first_day_evidence_invalid")


def start(workspace, client, *, now=_utcnow):
    project, query = create_diagnostic_checkpoint(workspace)
    run_wos_checkpoint(project, query.query_id, client, max_requests=2, now=now)
    state, pages, attempts = _evidence(project, query.query_id)
    _first_day(state, pages, attempts)
    _save(workspace / STATE, {"project": str(project.identifier), "query": query.query_id})
    return {"stage": "paused", "pages": len(pages), "remaining": attempts[-1][4]}


def resume(workspace, client, *, now=_utcnow):
    saved = json.loads((workspace / STATE).read_text(encoding="utf-8"))
    project = open_project(workspace / PROJECT)
    query_id = str(UUID(saved["query"]))
    if str(project.identifier) != saved["project"]:
        raise ValueError("wrong_project")
    before, pages, attempts = _evidence(project, query_id)
    _first_day(before, pages, attempts)
    first_date, first_remaining, first_limit = attempts[-1][3:]
    if now().astimezone(timezone.utc).date().isoformat() <= first_date:
        raise ValueError("later_utc_date_required")
    run_wos_checkpoint(project, query_id, client, max_requests=2, revalidate_quota=True, now=now)
    after, final_pages, all_attempts = _evidence(project, query_id)
    next_attempts = all_attempts[len(attempts):]
    if (all_attempts[:len(attempts)] != attempts or
            [row[:3] for row in next_attempts] != [("probe", 1, 1), ("acquire", len(pages)+1, 50)] or
            any(row[3] <= first_date for row in next_attempts) or
            any(row[5] != first_limit for row in all_attempts) or
            len({row[3] for row in next_attempts}) != 1 or
            final_pages[:-1] != pages or len(final_pages) != len(pages)+1 or
            after.reported_matches != before.reported_matches or after.records_committed <= before.records_committed):
        raise ValueError("cross_day_resume_unverified")
    result = dict(first_utc_date=first_date, resumed_utc_date=next_attempts[0][3],
                  first_day_remaining=first_remaining, resumed_probe_remaining=next_attempts[0][4],
                  daily_limit=first_limit, quota_increase_observed=next_attempts[0][4] > first_remaining,
                  actual_exhaustion_observed=first_remaining == 0, requests=len(all_attempts),
                  pages_before=len(pages), pages_after=len(final_pages), original_pages_unchanged=True,
                  records_retained=after.records_committed, cross_day_resume_verified=True,
                  source_retrieval_verified=False)
    for field, variable, pattern in (("commit_sha", "GITHUB_SHA", r"[a-f0-9]{40}"),
                                     ("github_run_id", "GITHUB_RUN_ID", r"[0-9]{1,20}")):
        value = os.environ.get(variable, "")
        result[field] = value if re.fullmatch(pattern, value) else None
    _save(workspace / EVIDENCE, result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("start", "resume"))
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args(argv)
    key = os.environ.get("RESEARCHY_WOS_STARTER_API_KEY")
    if os.environ.get("RESEARCHY_WOS_RETENTION_AUTHORIZED") != "true" or not key:
        print("Manual retention consent and private Starter configuration are required.", file=sys.stderr)
        return 2
    try:
        client = WoSStarterClient(api_key=key, request_budget=2)
        result = (start if args.stage == "start" else resume)(args.workspace, client)
    except Exception:
        print("Cross-day sample incomplete. No source acceptance recorded.", file=sys.stderr)
        return 3
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
