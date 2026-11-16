from contextlib import closing
import json
import sqlite3
from uuid import uuid4
from research_y.projects import create_project
from research_y.release_evidence import audit_page,export_diagnostic
from research_y import publication_identity as identity, study_classification


def test_diagnostic_and_human_audit_exclude_private_free_text(tmp_path):
    project=create_project(tmp_path,"Private project name")
    rid=str(uuid4())
    with closing(sqlite3.connect(project.database_path)) as db,db:
        for i in range(30):
            db.execute("INSERT INTO audit_events(occurred_at_utc,event_type,details_json) VALUES(?,?,?)",
                       (project.created_at_utc,"private event name",json.dumps(dict(
                        run_id=rid,actor="private person",private_key="fixture-credential",status="invalid private status"))))
    first=audit_page(project)
    assert len(first["rows"])==25 and first["next_after"]
    assert audit_page(project,first["next_after"])["rows"]
    out=tmp_path/"Diagnostic.json"
    counts=export_diagnostic(project,out)
    data=json.loads(out.read_text())
    assert len(data["audit"])==counts["audit_events"] and data["audit"][-1]["fields"]=={"run_id":rid}
    raw=out.read_text()
    assert all(v not in raw for v in ("private event name","private person","fixture-credential","Private project name","invalid private status"))


def test_reversal_and_classification_corrections_are_recognisable_in_both_views(tmp_path):
    from test_publication_candidates import setup, read_candidate, decide, args

    project, a, b = setup(tmp_path)
    pair = read_candidate(project, a, b)
    origin = pair.publication_ids[pair.retrieval_ids.index(a)]
    match = decide(project, a, b, **args(pair, decision="confirmed_match", moving=a))
    target = match.publication_ids[0]
    association = match.prior_decisions[-1]["association_event_id"]
    identity.reverse_association(project,a,association,
        expected_current_revision=identity.read_publication(project,target).revision,
        expected_restored_revision=identity.read_publication(project,origin).revision,
        actor="Private researcher",evidence="Private reason")
    view = study_classification.read_classification(project, origin)
    study_classification.review_classification(project,origin,dimension="design",labels=["case series"],
        actor="Private researcher",rationale="Private reason",expected_revision=view["revision"],confirmed=True)
    out = tmp_path / "Audit.json"
    export_diagnostic(project,out)
    exported = json.loads(out.read_text())["audit"]
    visible = audit_page(project)["rows"]
    for rows in (visible, exported):
        reversal = next(r["fields"] for r in rows if r["fields"].get("action")=="reverse")
        assert reversal["before"]==target and reversal["after"]==origin and reversal["reverses_event_id"]==association
        correction = next(r for r in rows if r["event_type"]==study_classification.EVENT)
        assert correction["fields"]["publication_id"] == origin
        assert correction["fields"]["labels"] == ["case series"] and correction["fields"]["status"]=="user-corrected"
    assert "Private researcher" not in out.read_text() and "Private reason" not in out.read_text()
