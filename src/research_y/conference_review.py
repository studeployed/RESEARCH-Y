"""Persistent follow-up for source blocks that could not be identified."""
from research_y import publication_identity as identity
from research_y.projects import _utc_now, _validated_project_connection


OPEN = "conference_block_review_requested_v1"
FINISH = "conference_block_review_completed_v1"


def _task(db, event_id):
    row = db.execute("SELECT details_json FROM audit_events WHERE event_id=? AND event_type=?",
                     (event_id, OPEN)).fetchone()
    if row is None:
        raise ValueError("Unknown conference review task")
    return identity._object(row[0])


def _decision(db, event_id):
    row = db.execute("SELECT details_json FROM audit_events WHERE event_type=? "
                     "AND json_extract(details_json,'$.task_id')=?", (FINISH,event_id)).fetchone()
    return identity._object(row[0]) if row else None


def queue_block(project, retrieval_id, inspection, locator, actor):
    """The caller supplies the local extractor's preview, never raw UI evidence."""
    reason = next((r["reason"] for r in inspection["unresolved"] if r["locator"] == locator), None)
    if reason is None:
        raise ValueError("Select an unresolved block from this source")
    identity._text(actor, 200)
    with _validated_project_connection(project) as db:
        db.execute("BEGIN IMMEDIATE")
        source = identity._source(db, identity._identifier(retrieval_id))
        key = identity._hash([retrieval_id,source["source_sha256"],inspection["source_sha256"],locator,reason])
        existing = db.execute("SELECT event_id FROM audit_events WHERE event_type=? "
                              "AND json_extract(details_json,'$.key')=?", (OPEN,key)).fetchone()
        if existing:
            return existing[0]
        return identity._audit(db, OPEN, dict(at_utc=_utc_now(), key=key, actor=actor,
                    retrieval_id=retrieval_id, original_source_sha256=source["source_sha256"],
                    document_sha256=inspection["source_sha256"], locator=locator, reason=reason))


def read_tasks(project, retrieval_id, *, after=0):
    if type(after) is not int or after < 0:
        raise ValueError("Invalid conference review cursor")
    with _validated_project_connection(project) as db:
        db.execute("BEGIN")
        source = identity._source(db, identity._identifier(retrieval_id))
        rows = db.execute("SELECT event_id,details_json FROM audit_events WHERE event_type=? AND event_id>? "
                          "AND json_extract(details_json,'$.retrieval_id')=? ORDER BY event_id LIMIT 21",
                          (OPEN,after,retrieval_id)).fetchall()
        tasks = []
        for event_id, raw in rows[:20]:
            task = identity._object(raw)
            tasks.append(dict(task_id=event_id, **task, original_current=task["original_source_sha256"] ==
                              source["source_sha256"], decision=_decision(db,event_id)))
        return dict(retrieval_id=retrieval_id, tasks=tasks, after=after,
                    next_after=rows[19][0] if len(rows)>20 else None)


def finish_task(project, retrieval_id, *, task_id, actor, disposition, note):
    identity._positive(task_id)
    identity._text(actor, 200)
    identity._text(note, 2000)
    if disposition not in ("not_an_individual_abstract", "reviewed_in_source"):
        raise ValueError("Choose a conference review outcome")
    with _validated_project_connection(project) as db:
        db.execute("BEGIN IMMEDIATE")
        task = _task(db,task_id)
        source = identity._source(db,identity._identifier(retrieval_id))
        if task["retrieval_id"] != retrieval_id or task["original_source_sha256"] != source["source_sha256"]:
            raise ValueError("Review task does not match the current original collection")
        decision = _decision(db,task_id)
        if decision is not None:
            if (decision["actor"],decision["disposition"],decision["note"]) != (actor,disposition,note):
                raise ValueError("Another decision already completed this task")
            return
        identity._audit(db, FINISH, dict(at_utc=_utc_now(), task_id=task_id, actor=actor,
                                        disposition=disposition,note=note))
