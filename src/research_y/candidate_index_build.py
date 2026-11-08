"""P1-06k2a: bounded, resumable derived candidate-key index construction.

Candidate keys are review HINTS, not publication identity. No source record,
publication link, search query or historical reviewer decision is altered.
Every 128-record step commits its verified progress and an audit receipt in
one original project SQLite transaction. The index contains only project-salted
SHA-256 digests of normalised citation fields, not source titles or abstracts.
"""
from __future__ import annotations

from uuid import uuid4

from research_y.application_inspection import _read
from research_y.projects import Project, _utc_now, _validated_project_connection
from research_y import publication_identity as identity
from research_y.publication_match_evidence import project_source

METHOD = "derived-candidate-key-index/1"
FIELDS = ("doi", "pmid", "accession", "title")
MAX_BATCH = 128
MAX_VALUE_CHARS = 10000
BEGIN_EVENT = "candidate_index_generation_started"
BATCH_EVENT = "candidate_index_batch_committed"


class CandidateIndexError(RuntimeError):
    """Untrusted client sees fixed codes, not original metadata or local paths."""

    def __init__(self, code="candidate_index_unavailable"):
        self.code = code if code in (
            "candidate_index_unavailable", "candidate_index_invalid",
            "candidate_index_stale", "candidate_index_confirmation_required",
            "candidate_index_no_work", "candidate_index_field_over_limit",
        ) else "candidate_index_unavailable"
        super().__init__(self.code)


def _digest(value):
    if (type(value) is not str or len(value) != 64 or
            any(ch not in "0123456789abcdef" for ch in value)):
        raise CandidateIndexError("candidate_index_invalid")


def _state(db):
    row = db.execute(
        "SELECT status,source_epoch,generation_id,baseline_epoch,"
        "cursor_retrieval_id,processed_records,indexed_keys,unsupported_records,"
        "running_sha256,started_at_utc,updated_at_utc "
        "FROM candidate_index_state WHERE singleton_id=1"
    ).fetchone()
    if row is None:
        raise CandidateIndexError()
    (status, epoch, generation, baseline, cursor, processed, keys,
     unsupported, running_hash, started, updated) = row
    if (status not in ("empty","building","ready","stale")
            or type(epoch) is not int or epoch < 0
            or type(processed) is not int or processed < 0
            or type(keys) is not int or keys < 0
            or type(unsupported) is not int or not 0 <= unsupported <= processed
            or ((generation is None) != (baseline is None))
            or (generation is not None and
                (identity._identifier(generation) != generation or
                 type(baseline) is not int or baseline < 0))
            or (cursor is not None and identity._identifier(cursor) != cursor)
            or (running_hash is not None and
                (type(running_hash) is not str or len(running_hash) != 64 or
                 any(ch not in "0123456789abcdef" for ch in running_hash)))):
        raise CandidateIndexError()
    if status == "empty" and (generation is not None or processed or keys or cursor
                               or running_hash is not None or unsupported):
        raise CandidateIndexError()
    if status != "empty" and (generation is None or running_hash is None):
        raise CandidateIndexError()
    if status in ("building", "ready") and baseline != epoch:
        raise CandidateIndexError("candidate_index_stale")
    if status == "stale" and baseline == epoch:
        raise CandidateIndexError()
    if processed and cursor is None:
        raise CandidateIndexError()
    # After a source deletion SQLite cascades ONLY disposable cache rows.
    # A stale generation is explicitly unusable; permit its partial cached
    # counts so it can still be inspected and explicitly rebuilt. For any
    # ACTIVE generation, a missing or extra row is an integrity failure.
    if status != "stale":
        if db.execute("SELECT COUNT(*) FROM candidate_index_records").fetchone()[0] != processed:
            raise CandidateIndexError()
        if db.execute("SELECT COUNT(*) FROM candidate_index_keys").fetchone()[0] != keys:
            raise CandidateIndexError()
        if db.execute("SELECT COUNT(*) FROM candidate_index_records WHERE supported=0").fetchone()[0] != unsupported:
            raise CandidateIndexError()
    if generation is not None and db.execute(
        "SELECT 1 FROM candidate_index_records WHERE generation_id<>? LIMIT 1",
        (generation,),
    ).fetchone() is not None:
        raise CandidateIndexError()
    source_total = db.execute("SELECT COUNT(*) FROM source_retrievals").fetchone()[0]
    if status == "ready" and processed != source_total:
        raise CandidateIndexError()
    return dict(
        status=status, source_epoch=epoch, generation_id=generation,
        baseline_epoch=baseline, cursor_retrieval_id=cursor,
        processed_records=processed, indexed_keys=keys,
        unsupported_records=unsupported, source_records=source_total,
        running_sha256=running_hash, started_at_utc=started,
        updated_at_utc=updated,
    )


def _public(db, project):
    raw = _state(db)
    revision = identity._hash([METHOD, str(project.identifier), raw])
    return dict(
        method=METHOD, project_id=str(project.identifier),
        revision=revision, **raw,
        remaining_records=(
            raw["source_records"]-raw["processed_records"]
            if raw["status"] in ("building", "ready") else None
        ),
        index_ready=raw["status"] == "ready",
        source_query_executed=False, no_network_requests=True,
        cached_keys_are_provisional=True, automatic_match_allowed=False,
        candidate_discovery_complete=False,
        deduplication_complete=False, source_retrieval_verified=False,
        verified_complete=False, global_unique_publications=None,
    )


def preview_candidate_index(project: Project) -> dict:
    """Read one validated project snapshot; index preview never writes."""
    try:
        with _read(project) as db:
            return _public(db, project)
    except CandidateIndexError:
        raise
    except Exception:
        raise CandidateIndexError() from None


def start_candidate_index(project: Project, *, expected_revision: str,
                          actor: str, confirmed: bool) -> dict:
    """Explicitly replace only this rebuildable derivative, not original data.

    The expected preview fences source changes and prior progress. A crash
    before commit leaves the previous index untouched; after commit the
    generation can be resumed with progress from preview_candidate_index.
    """
    if confirmed is not True:
        raise CandidateIndexError("candidate_index_confirmation_required")
    try:
        _digest(expected_revision)
        identity._text(actor, 200)
        with _validated_project_connection(project) as db:
            db.execute("BEGIN IMMEDIATE")
            before = _public(db, project)
            if before["revision"] != expected_revision:
                raise CandidateIndexError("candidate_index_stale")
            gen = str(uuid4())
            now = _utc_now()
            db.execute("DELETE FROM candidate_index_keys")
            db.execute("DELETE FROM candidate_index_records")
            running_hash = identity._hash([
                METHOD, str(project.identifier), gen, before["source_epoch"],
            ])
            db.execute(
                "UPDATE candidate_index_state SET status='building', "
                "generation_id=?, baseline_epoch=source_epoch, "
                "cursor_retrieval_id=NULL, processed_records=0, indexed_keys=0, "
                "unsupported_records=0, running_sha256=?, started_at_utc=?, "
                "updated_at_utc=? WHERE singleton_id=1",
                (gen, running_hash, now, now),
            )
            identity._audit(db, BEGIN_EVENT, dict(
                version=1, at_utc=now, actor=actor, generation_id=gen,
                source_epoch=before["source_epoch"],
                source_records_at_start=before["source_records"],
                method=METHOD, previous_status=before["status"],
            ))
            return _public(db, project)
    except CandidateIndexError:
        raise
    except (ValueError, TypeError):
        raise CandidateIndexError("candidate_index_invalid") from None
    except Exception:
        raise CandidateIndexError() from None


def _source_keys(project: Project, source: dict):
    """Validate provider record identity and project non-exportable key digests."""
    source_name = source["source_name"]
    payload = source["original_metadata"]
    if source_name in ("pubmed", "wos"):
        record = payload.get("record")
        field = "pmid" if source_name == "pubmed" else "uid"
        if (not isinstance(record, dict) or
                record.get(field) != source["source_record_id"]):
            raise CandidateIndexError()
    projection = project_source(source)
    if "unsupported_source_layout" in projection["warnings"]:
        return False, ()
    keys = []
    for field in FIELDS:
        evidence = projection["fields"][field]
        normalised = evidence["normalised"]
        if evidence["status"] != "present":
            continue
        if type(normalised) is not str:
            raise CandidateIndexError()
        if len(normalised) > MAX_VALUE_CHARS:
            raise CandidateIndexError("candidate_index_field_over_limit")
        keys.append((field, identity._hash([
            METHOD, str(project.identifier), field, normalised,
        ])))
    return True, tuple(keys)


def advance_candidate_index(project: Project, *, expected_revision: str,
                            generation_id: str, actor: str, confirmed: bool,
                            max_records: int = MAX_BATCH) -> dict:
    """One atomic bounded step; interruption commits either all or no keys.

    No network access, no automatic matching and no assumption that source
    retrieval is complete. A concurrent source record insert/update/delete
    invalidates the generation through database triggers in the source write.
    """
    if confirmed is not True:
        raise CandidateIndexError("candidate_index_confirmation_required")
    if type(max_records) is not int or not 1 <= max_records <= MAX_BATCH:
        raise CandidateIndexError("candidate_index_invalid")
    try:
        _digest(expected_revision)
        identity._identifier(generation_id)
        identity._text(actor, 200)
        with _validated_project_connection(project) as db:
            db.execute("BEGIN IMMEDIATE")
            before = _public(db, project)
            if (before["revision"] != expected_revision or
                    before["generation_id"] != generation_id):
                raise CandidateIndexError("candidate_index_stale")
            if before["status"] != "building":
                raise CandidateIndexError(
                    "candidate_index_stale" if before["status"] == "stale"
                    else "candidate_index_no_work"
                )
            cursor = before["cursor_retrieval_id"]
            # An explicit non-null range predicate is essential here.
            # A nullable-cursor OR forces a full index SCAN in SQLite when
            # resuming near the end of a large project.
            if cursor is None:
                selected = db.execute(
                    "SELECT retrieval_id FROM source_retrievals "
                    "ORDER BY retrieval_id LIMIT ?", (max_records,),
                ).fetchall()
            else:
                selected = db.execute(
                    "SELECT retrieval_id FROM source_retrievals "
                    "WHERE retrieval_id>? ORDER BY retrieval_id LIMIT ?",
                    (cursor, max_records),
                ).fetchall()
            next_cursor = cursor
            digest = before["running_sha256"]
            total_keys = unsupported = 0
            for (rid,) in selected:
                identity._identifier(rid)
                source = identity._source(db, rid)
                supported, values = _source_keys(project, source)
                db.execute(
                    "INSERT INTO candidate_index_records"
                    "(retrieval_id,generation_id,run_id,source_sha256,supported)"
                    " VALUES(?,?,?,?,?)",
                    (rid, generation_id, source["run_id"],
                     source["source_sha256"], int(supported)),
                )
                for field, key_hash in values:
                    db.execute(
                        "INSERT INTO candidate_index_keys"
                        "(retrieval_id,field,value_sha256) VALUES(?,?,?)",
                        (rid, field, key_hash),
                    )
                total_keys += len(values)
                unsupported += not supported
                digest = identity._hash([
                    digest, rid, source["source_sha256"],
                    source["run_id"], supported, values,
                ])
                next_cursor = rid
            if next_cursor is None:
                more = db.execute(
                    "SELECT 1 FROM source_retrievals LIMIT 1"
                ).fetchone() is not None
            else:
                more = db.execute(
                    "SELECT 1 FROM source_retrievals "
                    "WHERE retrieval_id>? LIMIT 1",
                    (next_cursor,),
                ).fetchone() is not None
            finished = not more
            new_count = before["processed_records"] + len(selected)
            if finished and new_count != before["source_records"]:
                raise CandidateIndexError("candidate_index_stale")
            now = _utc_now()
            db.execute(
                "UPDATE candidate_index_state SET status=?, "
                "cursor_retrieval_id=?, processed_records=?, "
                "indexed_keys=?, unsupported_records=?, running_sha256=?, "
                "updated_at_utc=? WHERE singleton_id=1",
                ("ready" if finished else "building", next_cursor,
                 new_count, before["indexed_keys"] + total_keys,
                 before["unsupported_records"] + unsupported, digest, now),
            )
            identity._audit(db, BATCH_EVENT, dict(
                version=1, at_utc=now, generation_id=generation_id,
                actor=actor, source_epoch=before["source_epoch"],
                before_cursor=cursor, after_cursor=next_cursor,
                batch_records=len(selected), batch_keys=total_keys,
                processed_records=new_count, running_sha256=digest,
                finished=finished, method=METHOD,
            ))
            return dict(
                **_public(db, project),
                committed_records=len(selected), committed_keys=total_keys,
                generation_completed=finished,
            )
    except CandidateIndexError:
        raise
    except (TypeError, ValueError):
        raise CandidateIndexError("candidate_index_invalid") from None
    except Exception:
        raise CandidateIndexError() from None
