"""Bounded, auditable exact-key *pair-hint* checkpoints (P1-06k3a).

This builds a disposable source-pair hint index from PR74's verified v5
source-key cache. It never merges publications or claims that every possible
bibliographic duplicate has been identified. A separate future increment must
append the previously reviewed receipt-only pairs and adopt paging in the GUI.

One explicit transaction processes at most 64 source/field keys and 128
source-key matches, including when one dense key spans many transactions.
No provider request, licensed abstract or source-record modification occurs.
"""
from __future__ import annotations

from research_y import candidate_index_build as source_keys
from research_y import publication_identity as identity
from research_y.projects import Project, _utc_now, _validated_project_connection
from research_y.application_inspection import _read

METHOD = "candidate-pair-hint-checkpoints/1"
MAX_KEYS_PER_BATCH = 64
MAX_HINTS_PER_BATCH = 128
MAX_UNIQUE_PAIRS = 100_000
FIELDS_MASK = {"doi": 1, "pmid": 2, "accession": 4, "title": 8}
START_EVENT = "candidate_pair_generation_started_v1"
BATCH_EVENT = "candidate_pair_batch_committed_v1"

# Direct primary-key / secondary-key seeks, not nullable-cursor OR scans or
# historical-only Cartesian products.
NEXT_KEY_SQL = (
    "SELECT k.retrieval_id,k.field,k.value_sha256 "
    "FROM candidate_index_records r INDEXED BY candidate_index_records_by_run "
    "JOIN candidate_index_keys k ON k.retrieval_id=r.retrieval_id "
    "JOIN publication_retrievals l ON l.retrieval_id=k.retrieval_id "
    "WHERE r.run_id=? AND r.supported=1 AND r.retrieval_id>=? "
    "AND (r.retrieval_id>? OR k.field>?) "
    "ORDER BY r.retrieval_id,k.field LIMIT 1"
)
RESUME_KEY_SQL = (
    "SELECT k.retrieval_id,k.field,k.value_sha256 "
    "FROM candidate_index_records r "
    "JOIN candidate_index_keys k ON k.retrieval_id=r.retrieval_id "
    "JOIN publication_retrievals l ON l.retrieval_id=r.retrieval_id "
    "WHERE r.run_id=? AND r.supported=1 "
    "AND k.retrieval_id=? AND k.field=?"
)
PEERS_SQL = (
    "SELECT k.retrieval_id "
    "FROM candidate_index_keys k INDEXED BY candidate_index_keys_by_field "
    "JOIN candidate_index_records r ON r.retrieval_id=k.retrieval_id "
    "JOIN publication_retrievals l ON l.retrieval_id=k.retrieval_id "
    "WHERE k.field=? AND k.value_sha256=? AND k.retrieval_id>? "
    "AND k.retrieval_id<>? AND r.supported=1 "
    "AND (r.run_id<>? OR k.retrieval_id>?) "
    "ORDER BY k.retrieval_id LIMIT ?"
)


class CandidatePairError(RuntimeError):
    """Do not include source text, private paths or query data in errors."""

    def __init__(self, code="candidate_pair_unavailable"):
        self.code = code if code in (
            "candidate_pair_unavailable", "candidate_pair_invalid",
            "candidate_pair_stale", "candidate_pair_index_not_ready",
            "candidate_pair_confirmation_required", "candidate_pair_no_work",
            "candidate_pair_over_limit",
        ) else "candidate_pair_unavailable"
        super().__init__(self.code)


def _digest(value):
    if (type(value) is not str or len(value) != 64 or
            any(ch not in "0123456789abcdef" for ch in value)):
        raise CandidatePairError("candidate_pair_invalid")


def _run(db, run_id):
    identity._identifier(run_id)
    if db.execute("SELECT 1 FROM search_runs WHERE run_id=?",
                  (run_id,)).fetchone() is None:
        raise CandidatePairError("candidate_pair_invalid")


def _raw(db, project, run_id, *, full=False):
    _run(db, run_id)
    source = source_keys._state(db, full_cache_check=full)
    row = db.execute(
        "SELECT generation_id,source_index_generation,source_index_epoch,"
        "status,cursor_retrieval_id,cursor_field,cursor_other_id,"
        "processed_source_keys,emitted_hints,unique_pairs,running_sha256,"
        "started_at_utc,updated_at_utc "
        "FROM candidate_pair_builds WHERE run_id=?", (run_id,),
    ).fetchone()
    if row is None:
        return dict(
            status="not_started", generation_id=None, source_index_generation=None,
            source_index_epoch=None, cursor_retrieval_id=None,
            cursor_field=None, cursor_other_id=None,
            processed_source_keys=0, emitted_hints=0, unique_pairs=0,
            running_sha256=None, started_at_utc=None, updated_at_utc=None,
            index_ready=source["status"]=="ready",
            current_source_index_generation=source["generation_id"],
            current_source_index_epoch=source["source_epoch"],
        )
    (gen, index_gen, epoch, status, rid, field, other,
     keys, hints, unique, checksum, started, updated) = row
    try:
        identity._identifier(gen); identity._identifier(index_gen)
        if rid is not None:
            identity._identifier(rid)
        if other is not None:
            identity._identifier(other)
        _digest(checksum)
        if (status not in ("building","ready_keys_only","stale")
                or type(epoch) is not int or epoch < 0
                or (rid is None) != (field is None)
                or (field is not None and field not in FIELDS_MASK)
                or (other is not None and rid is None)
                or any(type(n) is not int or n<0 for n in (keys,hints,unique))
                or unique>hints or unique>MAX_UNIQUE_PAIRS
                or (keys and rid is None)
                or (status=="ready_keys_only" and other is not None)):
            raise CandidatePairError()
        # Table contents may change through original source deletion, which
        # is already explicitly marked stale by an original SQLite trigger.
        if status != "stale":
            if full:
                recorded = db.execute(
                    "SELECT COUNT(*) FROM candidate_pair_hints WHERE run_id=?",
                    (run_id,),
                ).fetchone()[0]
                if recorded!=unique:
                    raise CandidatePairError()
                if db.execute(
                    "SELECT 1 FROM candidate_pair_hints "
                    "WHERE run_id=? AND generation_id<>? LIMIT 1",
                    (run_id,gen),
                ).fetchone() is not None:
                    raise CandidatePairError()
            elif unique:
                # Ordinary write-path validation is O(log n), not O(n).
                if db.execute(
                    "SELECT 1 FROM candidate_pair_hints WHERE run_id=? LIMIT 1",
                    (run_id,),
                ).fetchone() is None:
                    raise CandidatePairError()
    except CandidatePairError:
        raise
    except Exception:
        raise CandidatePairError() from None
    if (source["status"]!="ready" or
            source["generation_id"] != index_gen or
            source["source_epoch"] != epoch):
        status = "stale"
    return dict(
        status=status, generation_id=gen,
        source_index_generation=index_gen, source_index_epoch=epoch,
        cursor_retrieval_id=rid, cursor_field=field, cursor_other_id=other,
        processed_source_keys=keys, emitted_hints=hints, unique_pairs=unique,
        running_sha256=checksum, started_at_utc=started, updated_at_utc=updated,
        index_ready=source["status"]=="ready",
        current_source_index_generation=source["generation_id"],
        current_source_index_epoch=source["source_epoch"],
    )


def _public(db, project, run_id, *, full=False):
    data = _raw(db, project, run_id, full=full)
    revision = identity._hash([METHOD,str(project.identifier),run_id,data])
    return dict(
        method=METHOD, project_id=str(project.identifier), run_id=run_id,
        revision=revision, **data,
        max_source_keys_per_batch=MAX_KEYS_PER_BATCH,
        max_hints_per_batch=MAX_HINTS_PER_BATCH,
        # Only exact-key hint generation is available at this stage.
        indexed_source_key_hints_complete=data["status"]=="ready_keys_only",
        historical_receipt_only_pairs_included=False,
        candidate_discovery_complete=False, deduplication_complete=False,
        source_retrieval_verified=False, verified_complete=False,
        global_unique_publications=None, no_network_requests=True,
        automatic_merge_allowed=False,
    )


def preview_pair_checkpoint(project: Project, run_id: str):
    """Read-only current generation and source-index compatibility."""
    try:
        with _read(project) as db:
            return _public(db, project, run_id, full=True)
    except CandidatePairError:
        raise
    except Exception:
        raise CandidatePairError() from None


def start_pair_checkpoint(project: Project, run_id: str, *,
                          expected_revision: str, actor: str,
                          confirmed: bool):
    if confirmed is not True:
        raise CandidatePairError("candidate_pair_confirmation_required")
    try:
        _digest(expected_revision)
        identity._text(actor, 200)
        with _validated_project_connection(project) as db:
            db.execute("BEGIN IMMEDIATE")
            old = _public(db, project, run_id, full=True)
            if old["revision"] != expected_revision:
                raise CandidatePairError("candidate_pair_stale")
            if not old["index_ready"]:
                raise CandidatePairError("candidate_pair_index_not_ready")
            generation = str(__import__("uuid").uuid4())
            now = _utc_now()
            index_gen = old["current_source_index_generation"]
            epoch = old["current_source_index_epoch"]
            db.execute("DELETE FROM candidate_pair_hints WHERE run_id=?", (run_id,))
            db.execute("DELETE FROM candidate_pair_builds WHERE run_id=?", (run_id,))
            digest = identity._hash([
                METHOD,str(project.identifier),run_id,generation,index_gen,epoch
            ])
            db.execute(
                "INSERT INTO candidate_pair_builds "
                "(run_id,generation_id,source_index_generation,source_index_epoch,"
                "status,processed_source_keys,emitted_hints,unique_pairs,"
                "running_sha256,started_at_utc,updated_at_utc) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (run_id,generation,index_gen,epoch,"building",0,0,0,digest,now,now),
            )
            identity._audit(db, START_EVENT, dict(
                version=1,at_utc=now,run_id=run_id,generation_id=generation,
                source_index_generation=index_gen,source_index_epoch=epoch,
                actor=actor,method=METHOD,
            ))
            return _public(db, project, run_id)
    except CandidatePairError:
        raise
    except (TypeError, ValueError):
        raise CandidatePairError("candidate_pair_invalid") from None
    except Exception:
        raise CandidatePairError() from None


def _next_key(db, run_id, cursor_id, cursor_field):
    return db.execute(
        NEXT_KEY_SQL,
        (run_id,cursor_id or "",cursor_id or "",cursor_field or ""),
    ).fetchone()


def _pending_key(db, run_id, cursor_id, cursor_field):
    result = db.execute(
        RESUME_KEY_SQL,(run_id,cursor_id,cursor_field)
    ).fetchone()
    if result is None:
        raise CandidatePairError("candidate_pair_stale")
    return result


def advance_pair_checkpoint(project: Project, run_id: str, *,
                            generation_id: str, expected_revision: str,
                            actor: str, confirmed: bool):
    """One atomic bounded transaction, including recovery within a dense key."""
    if confirmed is not True:
        raise CandidatePairError("candidate_pair_confirmation_required")
    try:
        identity._identifier(generation_id); _digest(expected_revision)
        identity._text(actor, 200)
        with _validated_project_connection(project) as db:
            db.execute("BEGIN IMMEDIATE")
            old=_public(db, project, run_id)
            if (old["revision"] != expected_revision or
                    old["generation_id"] != generation_id):
                raise CandidatePairError("candidate_pair_stale")
            if old["status"]!="building":
                raise CandidatePairError(
                    "candidate_pair_stale" if old["status"]=="stale"
                    else "candidate_pair_no_work"
                )
            remaining_hints=MAX_HINTS_PER_BATCH
            remaining_keys=MAX_KEYS_PER_BATCH
            rid,field,other=(
                old["cursor_retrieval_id"],old["cursor_field"],
                old["cursor_other_id"],
            )
            processed=emitted=new_pairs=0
            digest=old["running_sha256"]
            while remaining_hints and remaining_keys:
                if other is not None:
                    key=_pending_key(db,run_id,rid,field)
                else:
                    key=_next_key(db,run_id,rid,field)
                if key is None:
                    break
                key_rid,key_field,key_value=key
                peers=db.execute(
                    PEERS_SQL,
                    (key_field,key_value,other or "",key_rid,run_id,
                     key_rid,remaining_hints+1),
                ).fetchall()
                full_key=len(peers)<=remaining_hints
                taken=peers[:remaining_hints]
                for (other_rid,) in taken:
                    pair=tuple(sorted((key_rid,other_rid)))
                    mask=FIELDS_MASK[key_field]
                    inserted=db.execute(
                        "INSERT OR IGNORE INTO candidate_pair_hints "
                        "(run_id,generation_id,left_retrieval_id,"
                        "right_retrieval_id,fields_mask) VALUES(?,?,?,?,?)",
                        (run_id,generation_id,pair[0],pair[1],mask),
                    ).rowcount
                    db.execute(
                        "UPDATE candidate_pair_hints SET fields_mask=fields_mask|? "
                        "WHERE run_id=? AND left_retrieval_id=? "
                        "AND right_retrieval_id=?",
                        (mask,run_id,pair[0],pair[1]),
                    )
                    new_pairs+=inserted
                    if old["unique_pairs"]+new_pairs>MAX_UNIQUE_PAIRS:
                        raise CandidatePairError("candidate_pair_over_limit")
                    emitted+=1
                    digest=identity._hash([
                        digest,key_rid,key_field,other_rid,mask,
                    ])
                remaining_hints-=len(taken)
                if full_key:
                    processed+=1
                    remaining_keys-=1
                    digest=identity._hash([digest,"source_key_finished",
                                           key_rid,key_field])
                    rid,field,other=key_rid,key_field,None
                else:
                    # Next call resumes *inside this exact source/key bucket*.
                    # No pair is repeated; cursor change is committed atomically.
                    rid,field,other=key_rid,key_field,taken[-1][0]
                    break
            finished = other is None and _next_key(db,run_id,rid,field) is None
            now=_utc_now()
            db.execute(
                "UPDATE candidate_pair_builds SET status=?,"
                "cursor_retrieval_id=?,cursor_field=?,cursor_other_id=?,"
                "processed_source_keys=?,emitted_hints=?,unique_pairs=?,"
                "running_sha256=?,updated_at_utc=? WHERE run_id=?",
                ("ready_keys_only" if finished else "building",
                 rid,field,other,
                 old["processed_source_keys"]+processed,
                 old["emitted_hints"]+emitted,
                 old["unique_pairs"]+new_pairs,digest,now,run_id),
            )
            identity._audit(db,BATCH_EVENT,dict(
                version=1,at_utc=now,run_id=run_id,generation_id=generation_id,
                actor=actor,method=METHOD,source_index_epoch=old["source_index_epoch"],
                source_keys_processed=processed,hints_emitted=emitted,
                new_distinct_pairs=new_pairs,
                cursor_after=[rid,field,other],
                cumulative_hint_count=old["emitted_hints"]+emitted,
                cumulative_pair_count=old["unique_pairs"]+new_pairs,
                running_sha256=digest,
                status="ready_keys_only" if finished else "building",
            ))
            return dict(
                **_public(db,project,run_id),
                committed_source_keys=processed,
                committed_hints=emitted,
                committed_new_pairs=new_pairs,
            )
    except CandidatePairError:
        raise
    except (TypeError, ValueError):
        raise CandidatePairError("candidate_pair_invalid") from None
    except Exception:
        raise CandidatePairError() from None


def read_pair_hint_page(project: Project, run_id: str, *,
                        after_pair: tuple[str,str] | None=None,
                        expected_revision: str | None=None):
    """Keyset read of *exact-key hints only*. Not the complete review queue.

    Source identity, decision/review receipts and scientific confirmation
    remain the existing original services' responsibility. GUI adoption is
    deferred until recorded receipt-only pairs are incorporated.
    """
    try:
        if after_pair is not None:
            if (type(after_pair) is not tuple or len(after_pair)!=2 or
                    any(type(x) is not str for x in after_pair)):
                raise CandidatePairError("candidate_pair_invalid")
            a,b=after_pair
            identity._identifier(a);identity._identifier(b)
            if a>=b or expected_revision is None:
                raise CandidatePairError("candidate_pair_invalid")
        if expected_revision is not None:
            _digest(expected_revision)
        with _read(project) as db:
            state=_public(db,project,run_id,full=True)
            if expected_revision is not None and state["revision"]!=expected_revision:
                raise CandidatePairError("candidate_pair_stale")
            if state["status"]!="ready_keys_only":
                raise CandidatePairError(
                    "candidate_pair_stale" if state["status"]=="stale"
                    else "candidate_pair_no_work"
                )
            if after_pair is not None and db.execute(
                "SELECT 1 FROM candidate_pair_hints "
                "WHERE run_id=? AND left_retrieval_id=? AND right_retrieval_id=?",
                (run_id,*after_pair),
            ).fetchone() is None:
                raise CandidatePairError("candidate_pair_stale")
            if after_pair is None:
                rows=db.execute(
                    "SELECT left_retrieval_id,right_retrieval_id,fields_mask "
                    "FROM candidate_pair_hints WHERE run_id=? "
                    "ORDER BY left_retrieval_id,right_retrieval_id LIMIT 21",
                    (run_id,),
                ).fetchall()
            else:
                rows=db.execute(
                    "SELECT left_retrieval_id,right_retrieval_id,fields_mask "
                    "FROM candidate_pair_hints WHERE run_id=? "
                    "AND (left_retrieval_id,right_retrieval_id)>(?,?) "
                    "ORDER BY left_retrieval_id,right_retrieval_id LIMIT 21",
                    (run_id,*after_pair),
                ).fetchall()
            shown=rows[:20]
            return dict(
                method=METHOD,project_id=str(project.identifier),
                run_id=run_id,revision=state["revision"],
                generation_id=state["generation_id"],
                pair_hint_total=state["unique_pairs"],
                rows=[dict(
                    retrieval_ids=[a,b],
                    matched_exact_fields=[
                        field for field,mask in FIELDS_MASK.items() if flags & mask
                    ],
                    no_automatic_match=True,
                ) for a,b,flags in shown],
                next_after_pair=(
                    list(shown[-1][:2]) if len(rows)>20 else None
                ),
                historical_receipt_only_pairs_included=False,
                candidate_discovery_complete=False,
                deduplication_complete=False,
                global_unique_publications=None,
                source_retrieval_verified=False,verified_complete=False,
                no_network_requests=True,
            )
    except CandidatePairError:
        raise
    except Exception:
        raise CandidatePairError() from None
