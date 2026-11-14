from contextlib import closing
import json
import sqlite3
from uuid import uuid4
from research_y.projects import create_project
from research_y.release_evidence import audit_page,export_diagnostic


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
