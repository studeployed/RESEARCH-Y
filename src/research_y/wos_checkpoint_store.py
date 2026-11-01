"""Durable Starter pages, source metadata, request journal and integrity checks.

All data commits include their audit event. Credentials never enter this API.
The caller must authorise local retention under its applicable source licence.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import sqlite3
from uuid import uuid4

from research_y.projects import Project, _validated_project_connection
from research_y.query_compiler import compile_source
from research_y.storage import _audit
from research_y.wos_starter import WoSPage, WoSQuota, WoSStarterError, parse_document_page, validate_request


class WoSCheckpointError(ValueError):
    """Static error category; no provider payload or secret is interpolated."""


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


def _hash(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def _stamp(instant: datetime | None = None) -> str:
    instant = instant or datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise WoSCheckpointError("timezone_required")
    return instant.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _uids(page: WoSPage) -> str:
    return _hash(_json([record.uid for record in page.records]))


def _metadata(record, database: str) -> str:
    return _json({"provider": "wos_starter", "database": database,
                  "record": record.as_dict(), "abstract_status": record.abstract_status,
                  "rights_status": record.rights_status})


@contextmanager
def _db(project: Project, *, write: bool = False):
    with _validated_project_connection(project) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        yield db


def _job(db, project: Project, query_id: str) -> dict:
    row = db.execute("SELECT * FROM wos_checkpoint_jobs WHERE query_id=?", (query_id,)).fetchone()
    if row is None:
        raise WoSCheckpointError("unknown_checkpoint")
    result = dict(row)
    try:
        plan = json.loads(row["plan_json"])
        source = db.execute(
            "SELECT run_id,strategy_version_id,group_id,source_name,exact_query,parameters_json "
            "FROM source_queries WHERE query_id=?", (query_id,),
        ).fetchone()
        if (_hash(row["plan_json"]) != row["plan_sha256"]
                or plan["project_id"] != str(project.identifier)
                or plan["query_id"] != query_id or source is None
                or tuple(source) != tuple(plan[k] for k in (
                    "run_id", "strategy_version_id", "group_id", "source_name",
                    "exact_query", "parameters_json"))):
            raise WoSCheckpointError("checkpoint_identity_mismatch")
        frozen = db.execute("SELECT snapshot_json FROM strategy_versions WHERE strategy_version_id=?",
                            (plan["strategy_version_id"],)).fetchone()
        if frozen is None or _hash(_json(json.loads(frozen[0]))) != plan["strategy_sha256"]:
            raise WoSCheckpointError("strategy_identity_mismatch")
        validate_request(plan["exact_query"], plan["database"], 1, plan["page_size"])
        if plan["sort_field"] != "LD+A" or plan["retention_authorized"] is not True:
            raise WoSCheckpointError("invalid_checkpoint_plan")
        if row["not_before_utc"] is not None:
            if _stamp(datetime.fromisoformat(row["not_before_utc"])) != row["not_before_utc"]:
                raise WoSCheckpointError("invalid_checkpoint_clock")
        result["plan"] = plan
    except (KeyError, TypeError, json.JSONDecodeError):
        raise WoSCheckpointError("invalid_checkpoint_plan") from None
    return result


def _audit_job(db, job: dict, kind: str, stamp: str, **details) -> None:
    _audit(db, kind="wos_" + kind, timestamp=stamp,
           details={"query_id": job["query_id"], **details})


def _state(db, job: dict, status: str, reason: str, stamp: str) -> None:
    db.execute("UPDATE wos_checkpoint_jobs SET status=?,reason_code=?,updated_at_utc=? WHERE query_id=?",
               (status, reason, stamp, job["query_id"]))
    db.execute("UPDATE source_queries SET status=? WHERE query_id=?", (status, job["query_id"]))
    _audit_job(db, job, "state", stamp, status=status, reason_code=reason)


def create_wos_checkpoint(project: Project, query_id: str, *, retention_authorized: bool) -> None:
    """Bind one pending compiler-produced chunk to immutable local storage rules.

    Query parameters may specify database/page_size/max_query_bytes only. A
    chunk is never mistaken for the whole group or multi-source run.
    """
    if retention_authorized is not True:
        raise WoSCheckpointError("local_retention_not_authorized")
    stamp = _stamp()
    with _db(project, write=True) as db:
        row = db.execute("SELECT * FROM source_queries WHERE query_id=?", (query_id,)).fetchone()
        if row is None or row["source_name"] != "wos" or row["status"] != "pending":
            raise WoSCheckpointError("pending_wos_query_required")
        parameters = json.loads(row["parameters_json"])
        if (not isinstance(parameters, dict)
                or set(parameters) - {"database", "page_size", "max_query_bytes"}):
            raise WoSCheckpointError("unsupported_query_parameters")
        database, size = parameters.get("database", "WOS"), parameters.get("page_size", 50)
        validate_request(row["exact_query"], database, 1, size)
        snapshot = json.loads(db.execute(
            "SELECT snapshot_json FROM strategy_versions WHERE strategy_version_id=?",
            (row["strategy_version_id"],)).fetchone()[0])
        compiled = compile_source(snapshot, "wos", max_query_bytes=parameters.get("max_query_bytes"))
        approved = [chunk.exact_query for group in compiled.groups
                    if group.group_id == row["group_id"] for chunk in group.chunks]
        if row["exact_query"] not in approved:
            raise WoSCheckpointError("query_not_in_approved_compilation")
        plan = {k: row[k] for k in ("query_id", "run_id", "strategy_version_id", "group_id",
                                    "source_name", "exact_query", "parameters_json")}
        plan.update(project_id=str(project.identifier), database=database, page_size=size,
                    sort_field="LD+A", strategy_sha256=compiled.snapshot_sha256,
                    retention_authorized=True, format_version=1)
        encoded = _json(plan)
        db.execute("INSERT INTO wos_checkpoint_jobs "
                   "(query_id,plan_json,plan_sha256,created_at_utc,updated_at_utc) VALUES (?,?,?,?,?)",
                   (query_id, encoded, _hash(encoded), stamp, stamp))
        _audit_job(db, {"query_id": query_id}, "checkpoint_created", stamp, plan_sha256=_hash(encoded))


@dataclass(frozen=True, slots=True)
class WoSCheckpoint:
    query_id: str
    status: str
    stage: str
    reason_code: str
    reported_matches: int | None
    pages_committed: int
    pages_expected: int | None
    records_committed: int
    verification_pages: int
    requests_reserved: int
    requests_confirmed_attempted: int
    requests_unknown: int
    failures: int
    quota: dict = field(repr=False)
    not_before_utc: str | None
    worker_active: bool
    enumeration_reconciled: bool
    # Scope is enumeration of supplied source metadata, not full bibliography.
    source_retrieval_verified: bool = False
    provider_snapshot_guaranteed: bool = False
    abstract_enrichment_complete: bool = False


def inspect_wos_checkpoint(project: Project, query_id: str) -> WoSCheckpoint:
    with _db(project) as db:
        job = _job(db, project, query_id)
        pages = db.execute("SELECT COUNT(*) FROM wos_checkpoint_pages WHERE query_id=?", (query_id,)).fetchone()[0]
        records = db.execute("SELECT COUNT(*) FROM wos_checkpoint_ids WHERE query_id=?", (query_id,)).fetchone()[0]
        verified = db.execute("SELECT COUNT(*) FROM wos_checkpoint_verifications WHERE query_id=? AND epoch=?",
                              (query_id, job["verify_epoch"])).fetchone()[0]
        attempts = db.execute("SELECT COUNT(*),COALESCE(SUM(sent=1),0),COALESCE(SUM(sent IS NULL),0) "
                              "FROM wos_checkpoint_attempts WHERE query_id=?", (query_id,)).fetchone()
        count = job["baseline_count"]
        expected = None if count is None else max(1, (count + job["plan"]["page_size"] - 1)//job["plan"]["page_size"])
        reconciled = (job["status"] == "completed_with_warnings" and job["stage"] == "done"
                      and count is not None and records == count and pages == verified == expected)
        if job["stage"] == "done" and not reconciled:
            raise WoSCheckpointError("invalid_reconciled_checkpoint")
        return WoSCheckpoint(query_id, job["status"], job["stage"], job["reason_code"], count,
                             pages, expected, records, verified, *tuple(attempts), job["failures"],
                             json.loads(job["quota_json"]), job["not_before_utc"],
                             job["owner_token"] is not None, reconciled)


def _quota_headers(quota: WoSQuota) -> dict[str, str]:
    # These headers are local parser inputs, never stored as provider evidence.
    # A malformed response canonicalises to WoSQuota(valid=False), distinct
    # from missing headers. Preserve that state through reparse and reopening.
    if quota.valid is False:
        return {"X-RateLimit-Limit-Day": "invalid"}
    return {header: str(value) for header, value in (
        ("X-RateLimit-Limit-Day", quota.daily_limit),
        ("X-RateLimit-Remaining-Day", quota.daily_remaining),
        ("X-RateLimit-Limit-Second", quota.per_second_limit)) if value is not None}


def _checked_page(page: WoSPage) -> WoSPage:
    parsed = parse_document_page(page.response_json.encode("utf-8"), exact_query=page.exact_query,
                                 database=page.database, requested_page=page.page,
                                 requested_limit=page.limit, retrieved_at_utc=page.retrieved_at_utc,
                                 headers=_quota_headers(page.quota))
    if parsed != page:
        raise WoSCheckpointError("inconsistent_page_object")
    return parsed


def _observe(db, attempt_id: str, page: WoSPage) -> None:
    descriptor = _json({"exact_query": page.exact_query, "database": page.database,
                        "requested_page": page.page, "requested_limit": page.limit,
                        "retrieved_at_utc": page.retrieved_at_utc, "quota": asdict(page.quota)})
    db.execute("INSERT INTO wos_checkpoint_observations VALUES (?,?,?,?,?)",
               (attempt_id, page.response_json, page.response_sha256, descriptor, _hash(descriptor)))


def _read_observation(db, attempt_id: str, query_id: str, purpose: str) -> WoSPage:
    row = db.execute("SELECT * FROM wos_checkpoint_observations WHERE attempt_id=?", (attempt_id,)).fetchone()
    if (row is None or _hash(row["response_json"]) != row["response_sha256"]
            or _hash(row["descriptor_json"]) != row["descriptor_sha256"]):
        raise WoSCheckpointError("observation_checksum_mismatch")
    try:
        data = json.loads(row["descriptor_json"])
        quota = WoSQuota(**data.pop("quota"))
        page = parse_document_page(row["response_json"].encode("utf-8"), headers=_quota_headers(quota), **data)
        attempt = db.execute("SELECT * FROM wos_checkpoint_attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
        if (attempt is None or attempt["query_id"] != query_id or attempt["purpose"] != purpose
                or attempt["outcome"] != "success" or attempt["sent"] != 1 or attempt["http_status"] != 200
                or attempt["page_number"] != page.page or attempt["page_size"] != page.limit
                or json.loads(attempt["quota_json"]) != asdict(page.quota)):
            raise WoSCheckpointError("observation_attempt_mismatch")
        return page
    except (KeyError, TypeError, ValueError, WoSStarterError):
        raise WoSCheckpointError("invalid_stored_observation") from None


def validate_wos_checkpoint(project: Project, query_id: str) -> None:
    """Reparse retained pages and reconcile indexes/source links, one page at a time."""
    with _db(project) as db:
        job = _job(db, project, query_id)
        plan, count = job["plan"], job["baseline_count"]
        number, total = 0, 0
        for row in db.execute("SELECT * FROM wos_checkpoint_pages WHERE query_id=? ORDER BY page_number", (query_id,)):
            number += 1
            page = _read_observation(db, row["attempt_id"], query_id, "acquire")
            if (row["page_number"] != number or page.page != number or page.reported_matches != count
                    or page.exact_query != plan["exact_query"] or page.database != plan["database"]
                    or page.limit != plan["page_size"] or row["uid_sha256"] != _uids(page)):
                raise WoSCheckpointError("stored_page_identity_mismatch")
            index = db.execute(
                "SELECT i.uid,i.ordinal,i.record_sha256,r.source_record_id,r.original_metadata_json,"
                "r.run_id,r.source_name,q.query_id FROM wos_checkpoint_ids i "
                "JOIN source_retrievals r ON r.retrieval_id=i.retrieval_id "
                "LEFT JOIN query_retrievals q ON q.retrieval_id=i.retrieval_id AND q.query_id=i.query_id "
                "WHERE i.query_id=? AND i.page_number=? ORDER BY i.ordinal", (query_id, number),
            ).fetchall()
            expected = [(rec.uid, ix, _hash(rec.raw_json), rec.uid, _metadata(rec, plan["database"]),
                         plan["run_id"], "wos", query_id) for ix, rec in enumerate(page.records)]
            if [tuple(item) for item in index] != expected:
                raise WoSCheckpointError("stored_record_or_membership_mismatch")
            total += len(page.records)
        indexed = db.execute("SELECT COUNT(*) FROM wos_checkpoint_ids WHERE query_id=?", (query_id,)).fetchone()[0]
        if job["next_page"] != number + 1 or indexed != total:
            raise WoSCheckpointError("checkpoint_progress_mismatch")
        if count is None and number:
            raise WoSCheckpointError("missing_baseline_count")
        expected_pages = None if count is None else max(1, (count+plan["page_size"]-1)//plan["page_size"])
        if (job["stage"] != "acquire"
                and (count is None or total != count or number != expected_pages)):
            raise WoSCheckpointError("incomplete_acquisition")
        verified = 0
        for row in db.execute("SELECT * FROM wos_checkpoint_verifications "
                              "WHERE query_id=? AND epoch=? ORDER BY page_number", (query_id, job["verify_epoch"])):
            verified += 1
            current = _read_observation(db, row["attempt_id"], query_id, "verify")
            original = db.execute("SELECT uid_sha256 FROM wos_checkpoint_pages WHERE query_id=? AND page_number=?",
                                  (query_id, row["page_number"])).fetchone()
            if (row["page_number"] != verified or current.page != verified or original is None
                    or _uids(current) != original[0] or current.reported_matches != count
                    or current.exact_query != plan["exact_query"] or current.database != plan["database"]
                    or current.limit != plan["page_size"]):
                raise WoSCheckpointError("verification_receipt_mismatch")
        if job["verify_page"] != verified + 1:
            raise WoSCheckpointError("verification_progress_mismatch")
        if job["stage"] in ("final", "done") and verified != expected_pages:
            raise WoSCheckpointError("incomplete_verification")
        if job["stage"] == "done":
            finals = db.execute("SELECT attempt_id,owner_token FROM wos_checkpoint_attempts "
                                "WHERE query_id=? AND purpose='final' AND outcome='success' "
                                "ORDER BY started_at_utc DESC LIMIT 1", (query_id,)).fetchone()
            if finals is None:
                raise WoSCheckpointError("missing_final_count_receipt")
            final = _read_observation(db, finals["attempt_id"], query_id, "final")
            first = db.execute("SELECT uid FROM wos_checkpoint_ids WHERE query_id=? AND page_number=1 "
                               "ORDER BY ordinal LIMIT 1", (query_id,)).fetchone()
            if (final.reported_matches != count or final.exact_query != plan["exact_query"]
                    or final.database != plan["database"] or final.page != 1 or final.limit != 1
                    or [r.uid for r in final.records] != ([] if first is None else [first[0]])):
                raise WoSCheckpointError("invalid_final_count_receipt")
            owners = {r[0] for r in db.execute(
                "SELECT a.owner_token FROM wos_checkpoint_verifications v "
                "JOIN wos_checkpoint_attempts a ON a.attempt_id=v.attempt_id "
                "WHERE v.query_id=? AND v.epoch=?", (query_id,job["verify_epoch"]))}
            if owners != {finals["owner_token"]}:
                raise WoSCheckpointError("verification_not_one_session")


def pause_wos_checkpoint(project: Project, query_id: str, *, cancel: bool = False) -> None:
    with _db(project, write=True) as db:
        job = _job(db, project, query_id)
        if job["stage"] == "done" or job["status"] == "cancelled":
            return
        _state(db, job, "cancelled" if cancel else "paused",
               "cancelled_by_user" if cancel else "paused_by_user", _stamp())


def recover_wos_worker(project: Project, query_id: str, *, previous_worker_stopped: bool) -> None:
    """Explicit crash recovery; never steal a live worker or assume an HTTP outcome.

    The caller must establish the old process stopped. A fresh ownership token
    fences stale commits even if an old callback subsequently returns.
    """
    if previous_worker_stopped is not True:
        raise WoSCheckpointError("stopped_worker_confirmation_required")
    stamp = _stamp()
    with _db(project, write=True) as db:
        job = _job(db, project, query_id)
        db.execute("UPDATE wos_checkpoint_attempts SET outcome='abandoned',finished_at_utc=?,"
                   "reason_code='interrupted_outcome_unknown' WHERE query_id=? AND outcome='started'",
                   (stamp, query_id))
        db.execute("UPDATE wos_checkpoint_jobs SET owner_token=NULL WHERE query_id=?", (query_id,))
        if job["status"] not in ("cancelled", "completed_with_warnings"):
            _state(db, job, "incomplete", "interrupted_outcome_unknown", stamp)
        _audit_job(db, job, "worker_recovered", stamp)


def _claim(project: Project, query_id: str, stamp: str, *, revalidate_quota: bool) -> str | None:
    with _db(project, write=True) as db:
        job = _job(db, project, query_id)
        if job["owner_token"] is not None:
            raise WoSCheckpointError("worker_busy_or_interrupted")
        if job["status"] in ("cancelled", "completed_with_warnings"):
            return None
        if job["failures"] >= 3 or job["reason_code"] in (
                "source_count_changed", "source_identity_changed", "cross_page_duplicate",
                "source_record_conflict", "checkpoint_write_failed"):
            return None
        if (job["status"] == "incomplete" and job["reason_code"] not in
                ("interrupted_outcome_unknown", "not_started") and not revalidate_quota):
            return None
        if job["not_before_utc"] and stamp < job["not_before_utc"]:
            return None
        observed_quota = json.loads(job["quota_json"])
        if (job["reason_code"] in ("quota_revalidation_required", "entitlement_unverified")
                or observed_quota.get("daily_remaining") == 0) and not revalidate_quota:
            return None
        token = str(uuid4())
        try:
            db.execute("UPDATE wos_checkpoint_jobs SET owner_token=? WHERE query_id=?", (token, query_id))
        except sqlite3.IntegrityError:
            raise WoSCheckpointError("another_wos_worker_active") from None
        # Old verification receipts remain auditable but cannot prove current
        # consistency after a restart. Acquisition pages are NEVER discarded.
        if job["stage"] in ("verify", "final"):
            db.execute("UPDATE wos_checkpoint_jobs SET verify_epoch=verify_epoch+1,verify_page=1,stage='verify' WHERE query_id=?",
                       (query_id,))
        _state(db, job, "running", "in_progress", stamp)
        db.execute("UPDATE search_runs SET status='incomplete' WHERE run_id=?", (job["plan"]["run_id"],))
        return token


def _owned(db, project: Project, query_id: str, token: str) -> dict:
    job = _job(db, project, query_id)
    if job["owner_token"] != token:
        raise WoSCheckpointError("stale_worker")
    return job


def _reserve(project: Project, query_id: str, token: str, purpose: str, number: int, size: int, stamp: str) -> str:
    with _db(project, write=True) as db:
        job = _owned(db, project, query_id, token)
        if job["status"] != "running":
            raise WoSCheckpointError("worker_paused")
        attempt_id = str(uuid4())
        db.execute("INSERT INTO wos_checkpoint_attempts "
                   "(attempt_id,query_id,owner_token,purpose,page_number,page_size,started_at_utc) VALUES (?,?,?,?,?,?,?)",
                   (attempt_id, query_id, token, purpose, number, size, stamp))
        _audit_job(db, job, "request_reserved", stamp, attempt_id=attempt_id, purpose=purpose, page=number, limit=size)
        return attempt_id


def _accept(project: Project, query_id: str, token: str, attempt_id: str,
            page: WoSPage, stamp: str, next_allowed: str | None) -> None:
    page = _checked_page(page)
    with _db(project, write=True) as db:
        job = _owned(db, project, query_id, token)
        plan = job["plan"]
        attempt = db.execute("SELECT * FROM wos_checkpoint_attempts WHERE attempt_id=? AND query_id=?",
                             (attempt_id, query_id)).fetchone()
        if (attempt is None or attempt["owner_token"] != token or attempt["outcome"] != "started"
                or page.page != attempt["page_number"] or page.limit != attempt["page_size"]
                or page.exact_query != plan["exact_query"] or page.database != plan["database"]):
            raise WoSCheckpointError("attempt_response_mismatch")
        _observe(db, attempt_id, page)
        quota_json = _json(asdict(page.quota))
        db.execute("UPDATE wos_checkpoint_attempts SET finished_at_utc=?,outcome='success',sent=1,"
                   "http_status=200,quota_json=? WHERE attempt_id=?", (stamp, quota_json, attempt_id))
        db.execute("UPDATE wos_checkpoint_jobs SET quota_json=?,not_before_utc=?,updated_at_utc=? WHERE query_id=?",
                   (quota_json, next_allowed, stamp, query_id))
        reason = None
        purpose = attempt["purpose"]
        if job["baseline_count"] is not None and page.reported_matches != job["baseline_count"]:
            reason = "source_count_changed"
        elif page.quota.entitlement_status != "institutional_allowance_observed" or page.quota.daily_remaining is None:
            reason = "entitlement_unverified"
        elif purpose in ("probe", "final"):
            original = db.execute("SELECT uid FROM wos_checkpoint_ids WHERE query_id=? AND page_number=1 ORDER BY ordinal LIMIT 1",
                                  (query_id,)).fetchone()
            if ([r.uid for r in page.records] != ([] if original is None else [original[0]])):
                reason = "source_identity_changed"
        elif purpose == "acquire":
            if page.page != job["next_page"] or page.limit != plan["page_size"]:
                raise WoSCheckpointError("unexpected_acquisition_page")
            for record in page.records:
                if db.execute("SELECT 1 FROM wos_checkpoint_ids WHERE query_id=? AND uid=?", (query_id, record.uid)).fetchone():
                    reason = "cross_page_duplicate"
                    break
                prior = db.execute("SELECT original_metadata_json FROM source_retrievals "
                                   "WHERE run_id=? AND source_name='wos' AND source_record_id=?",
                                   (plan["run_id"], record.uid)).fetchone()
                if prior and prior[0] != _metadata(record, plan["database"]):
                    reason = "source_record_conflict"
                    break
        elif purpose == "verify":
            original = db.execute("SELECT uid_sha256 FROM wos_checkpoint_pages WHERE query_id=? AND page_number=?",
                                  (query_id, page.page)).fetchone()
            if (page.page != job["verify_page"] or page.limit != plan["page_size"]
                    or original is None or original[0] != _uids(page)):
                reason = "source_identity_changed"
        if reason is not None:
            status = job["status"] if job["status"] in ("paused", "cancelled") else "incomplete"
            _state(db, job, status, reason, stamp)
            return  # Preserve the observation, never link an inconsistent page.
        if purpose == "acquire":
            if job["baseline_count"] is None:
                db.execute("UPDATE wos_checkpoint_jobs SET baseline_count=? WHERE query_id=?", (page.reported_matches, query_id))
                db.execute("UPDATE source_queries SET reported_matches=?,executed_at_utc=? WHERE query_id=?",
                           (page.reported_matches, stamp, query_id))
            db.execute("INSERT INTO wos_checkpoint_pages VALUES (?,?,?,?)", (query_id, page.page, attempt_id, _uids(page)))
            for ordinal, record in enumerate(page.records):
                row = db.execute("SELECT retrieval_id FROM source_retrievals WHERE run_id=? AND source_name='wos' AND source_record_id=?",
                                 (plan["run_id"], record.uid)).fetchone()
                rid = row[0] if row else str(uuid4())
                if row is None:
                    db.execute("INSERT INTO source_retrievals VALUES (?,?,?,?,?,?)",
                               (rid, plan["run_id"], "wos", record.uid, page.retrieved_at_utc, _metadata(record, plan["database"])))
                db.execute("INSERT INTO query_retrievals VALUES (?,?,?,?)", (query_id, rid, plan["run_id"], "wos"))
                db.execute("INSERT INTO wos_checkpoint_ids VALUES (?,?,?,?,?,?)",
                           (query_id, record.uid, page.page, ordinal, rid, _hash(record.raw_json)))
            db.execute("UPDATE wos_checkpoint_jobs SET next_page=next_page+1,failures=0 WHERE query_id=?", (query_id,))
            if page.page == max(1, page.estimated_total_pages):
                db.execute("UPDATE wos_checkpoint_jobs SET stage='verify',verify_epoch=verify_epoch+1,verify_page=1 WHERE query_id=?",
                           (query_id,))
            _audit_job(db, job, "page_committed", stamp, page=page.page, records=len(page.records), response_sha256=page.response_sha256)
        elif purpose == "verify":
            # Replayed prefixes in a new epoch are not new forward progress.
            # Derive the durable high-water mark from immutable prior receipts,
            # so repeated failures at the same later page or final probe exhaust
            # the retry budget even across fresh clients and verification epochs.
            prior_high_water = db.execute(
                "SELECT COALESCE(MAX(page_number),0) FROM wos_checkpoint_verifications WHERE query_id=?",
                (query_id,),
            ).fetchone()[0]
            db.execute("INSERT INTO wos_checkpoint_verifications VALUES (?,?,?,?)", (query_id, job["verify_epoch"], page.page, attempt_id))
            db.execute("UPDATE wos_checkpoint_jobs SET verify_page=verify_page+1,"
                       "failures=CASE WHEN ?>? THEN 0 ELSE failures END WHERE query_id=?",
                       (page.page, prior_high_water, query_id))
            if page.page == max(1, page.estimated_total_pages):
                db.execute("UPDATE wos_checkpoint_jobs SET stage='final' WHERE query_id=?", (query_id,))
            _audit_job(db, job, "identity_verified", stamp, page=page.page, epoch=job["verify_epoch"], response_sha256=page.response_sha256)
        elif purpose == "final" and job["status"] == "running":
            if job["stage"] != "final":
                raise WoSCheckpointError("premature_finalization")
            # All source records and a separate current ordered-identity pass
            # reconcile. No database snapshot/abstract/full-run claim is made.
            db.execute("UPDATE wos_checkpoint_jobs SET stage='done',failures=0 WHERE query_id=?", (query_id,))
            _state(db, job, "completed_with_warnings", "enumeration_reconciled_snapshot_unavailable", stamp)
        else:
            _audit_job(db, job, "count_revalidated", stamp, reported_matches=page.reported_matches, response_sha256=page.response_sha256)


def _release(project: Project, query_id: str, token: str) -> None:
    with _db(project, write=True) as db:
        job = _owned(db, project, query_id, token)
        active = db.execute("SELECT 1 FROM wos_checkpoint_attempts WHERE query_id=? AND outcome='started'", (query_id,)).fetchone()
        if active is None:
            db.execute("UPDATE wos_checkpoint_jobs SET owner_token=NULL WHERE query_id=?", (query_id,))
