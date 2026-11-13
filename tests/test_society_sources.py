from contextlib import closing
import json
import sqlite3
from uuid import uuid4

import pytest

from research_y.projects import open_project
from research_y.publication_identity import read_publication, StalePublicationError
from research_y.society_sources import (save_society, list_societies, record_society_visit,
                                        list_society_visits, import_guidance)
from scripts.society_review import main
from test_publication_identity import store, db_rows


def register(project, name="Example Society"):
    args = dict(society_id=str(uuid4()), name=name, official_url="https://society.example",
                actor="Researcher", confirmed=True)
    one = save_society(project, **args)
    assert save_society(project, **args) == one
    return one


def visit_args(org):
    return dict(request_id=str(uuid4()), society_id=org["society_id"], revision=org["revision"], actor="Reviewer",
                method="manual_browse", terms=["rehabilitation"],
                pages=[dict(url="https://society.example/guidance", examined_on="2026-11-13")],
                outcome="guidance_found", limitations="Checked the official directory only", confirmed=True)


def test_guideline_without_doi_or_journal_has_distinct_roles_evidence_and_unchanged_primary_counts(store):
    project, _ = store
    issuer, collaborator = register(project), register(project, "Collaborator")
    request = visit_args(issuer)
    visit = record_society_visit(project, **request)
    assert record_society_visit(project, **request) == visit
    assert visit["details"]["exhaustive"] is False
    queries = db_rows(project, "source_queries")
    memberships = db_rows(project, "query_retrievals")
    run = db_rows(project, "search_runs")[0][0]
    args = dict(request_id=str(uuid4()), run_id=run, visit_event_id=visit["event_id"],
                record=dict(title="Rehabilitation practice guidance", document_types=["clinical practice guideline"],
                            edition="2025", landing_url="https://society.example/guidance",
                            document_url="https://society.example/guidance/2025.pdf"),
                roles={"issuing": [issuer["society_id"]], "collaborating": [collaborator["society_id"]]},
                actor="Reviewer", confirmed=True)
    receipt = import_guidance(project, **args)
    reopened = open_project(project.root)
    assert import_guidance(reopened, **args) == receipt
    pub = read_publication(reopened, receipt["publication_id"])
    source, = pub.retrievals
    assert source["source_name"] == "society" and source["memberships"] == []
    original = source["original_metadata"]
    assert original["record"] == args["record"] and "doi" not in original["record"]
    assert original["society_roles"] == {"issuing": [issuer], "collaborating": [collaborator]}
    assert set((p[1],p[2]) for p in db_rows(project,"publication_organisations")) == {
        (issuer["society_id"], "issuing"), (collaborator["society_id"], "collaborating")}
    assert db_rows(project,"source_queries") == queries and db_rows(project,"query_retrievals") == memberships
    assert list_society_visits(reopened, issuer["society_id"]) == [visit]
    revised = import_guidance(project, **{**args,"request_id": str(uuid4()),
                                         "record": {**args["record"], "edition": "2026"}})
    assert revised["publication_id"] != receipt["publication_id"]
    with pytest.raises(ValueError, match="conflicts"):
        import_guidance(project, **{**args, "record": {**args["record"], "edition": "2026"}})


def test_site_evidence_stale_edit_and_confirmed_cli(store, tmp_path, capsys):
    project, _ = store
    org = register(project)
    args = visit_args(org)
    with pytest.raises(ValueError, match="hostname"):
        record_society_visit(project, **{**args,"pages":[dict(url="https://elsewhere.example",examined_on="2026-11-13")]})
    save_society(project, society_id=org["society_id"], name="Revised", official_url="https://new.example",
                actor="Editor", expected_revision=org["revision"], confirmed=True)
    with pytest.raises(StalePublicationError):
        record_society_visit(project, **args)
    main([str(project.root), "directory"])
    assert json.loads(capsys.readouterr().out) == list_societies(project)
    current, = list_societies(project)
    payload = {**args, "revision":current["revision"], "pages":[], "outcome":"unavailable",
               "limitations":"Official index was unavailable"}
    del payload["confirmed"]
    path = tmp_path / "visit.json"
    path.write_text(json.dumps(payload))
    main([str(project.root), "record-visit", str(path), "--confirm"])
    assert json.loads(capsys.readouterr().out)["details"]["outcome"] == "unavailable"


def test_failed_guidance_audit_rolls_back_original_publication_and_roles(store):
    project, _ = store
    org = register(project)
    visit = record_society_visit(project, **visit_args(org))
    tables = ["source_retrievals", "publications", "publication_retrievals", "publication_organisations", "audit_events"]
    before = [db_rows(project, table) for table in tables]
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute("CREATE TRIGGER fail_import BEFORE INSERT ON audit_events WHEN new.event_type='society_guidance_import_v1' "
                   "BEGIN SELECT RAISE(ABORT, 'fixture'); END")
    with pytest.raises(sqlite3.IntegrityError):
        import_guidance(project, request_id=str(uuid4()), run_id=db_rows(project,"search_runs")[0][0],
                        visit_event_id=visit["event_id"], record=dict(title="Example",document_types=["position statement"],
                        landing_url="https://society.example/guidance"), roles={"issuing":[org["society_id"]]},
                        actor="Reviewer", confirmed=True)
    assert [db_rows(project, table) for table in tables] == before
