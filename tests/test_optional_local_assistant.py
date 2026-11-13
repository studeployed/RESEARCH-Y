from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from research_y import local_assistant as local
from research_y.desktop.actions import perform_action
from research_y.desktop.flow import RealProjectFlow, ProjectFlowError
from research_y.projects import create_project, open_project
from research_y.storage import get_strategy_snapshot, list_run_queries


class FixtureAssistant:
    installed = True

    def __init__(self):
        self.calls = []

    def propose_terms(self, seed):
        self.calls.append(seed)
        return dict(terms=["ICU","critical care ward"], model=local.MODEL_NAME,
                    revision=local.MODEL_REVISION, engine=local.ENGINE_BUILD, template=local.PROMPT_VERSION,
                    parameters=list(local.PARAMETERS), input_sha256=local._hash_text(seed),
                    prompt_sha256="a"*64, response_sha256="b"*64, generated_at_utc="2026-11-13T00:00:00+00:00")


def test_desktop_model_output_excluded_until_individually_reviewed_and_frozen(tmp_path):
    project = create_project(tmp_path, "Synthetic ICU project")
    model = FixtureAssistant()
    with closing(RealProjectFlow(selected_root=project.root, selected_parent=tmp_path, local_assistant=model)) as flow:
        flow.open_selected()
        flow.edit_setup("heading", {"theme":"Critical care", "approved_by":"Reviewer"})
        gid = flow.edit_setup("add_group", {"label":"Unit"})["strategy_draft"]["groups"][0]["group_id"]
        state = flow.edit_setup("add_term", {"group_id":gid, "text":"intensive care unit"})
        tid = state["strategy_draft"]["groups"][0]["terms"][0]["term_id"]
        perform_action(flow, "local_mode", False)
        with pytest.raises(ProjectFlowError, match="unavailable"):
            perform_action(flow, "local_suggest", {"group_id":gid, "term_id":tid})
        assert model.calls == []
        perform_action(flow, "local_mode", True)
        state = perform_action(flow, "local_suggest", {"group_id":gid, "term_id":tid})
        draft = state["strategy_draft"]
        assert model.calls == ["intensive care unit"] and len(draft["groups"][0]["terms"]) == 1
        first, second = draft["suggestions"]
        assert first["origin"] == second["origin"] == "ai"
        flow.edit_setup("review_variant", {"suggestion_id":second["suggestion_id"], "decision":"reject"})
        flow.edit_setup("review_variant", {"suggestion_id":first["suggestion_id"], "decision":"accept","text":"ICU"})
        flow.preview_setup()
        receipt = flow.approve_setup()["last_strategy_admission"]
    reopened = open_project(project.root)
    terms = get_strategy_snapshot(reopened,receipt["strategy_version_id"])["groups"][0]["terms"]
    assert [t["text"] for t in terms] == ["intensive care unit","ICU"]
    assert terms[1]["origin"] == "ai" and str(first["event_id"]) in terms[1]["rationale"]
    for q in list_run_queries(reopened,receipt["run_id"]):
        assert "ICU" in q.exact_query and "critical care ward" not in q.exact_query
        assert q.status == "pending" and q.reported_matches is None
    with closing(sqlite3.connect(reopened.database_path)) as db:
        events = [json.loads(raw) for (raw,) in db.execute(
            "SELECT details_json FROM audit_events WHERE event_type LIKE 'local_term_%' ORDER BY event_id")]
    assert events[0]["input_sha256"] == local._hash_text("intensive care unit")
    assert [ev["decision"] for ev in events[1:]] == ["reject","accept"]


def test_no_model_offline_and_no_expansion_when_validation_fails(tmp_path):
    model = local.LocalAssistant(tmp_path/"missing")
    assert not model.installed
    with pytest.raises(local.LocalAssistantError):
        model.propose_terms("synthetic seed")
    with pytest.raises(local.LocalAssistantError, match="invalid_text"):
        model.propose_terms("seed <|im_start|> extra")


def test_inference_validates_executable_mode_and_bounds_untrusted_suggestions(tmp_path, monkeypatch):
    monkeypatch.setattr(local,"_validate",lambda path: None)
    def fake(args, **kw):
        assert "--offline" in args and kw["stdin"] == local.subprocess.DEVNULL
        assert kw["timeout"] == 90
        assert "GH_TOKEN" not in kw["env"] and "LLAMA_ARG_MODEL" not in kw["env"]
        assert "synthetic seed" in Path(args[args.index("-f")+1]).read_text()
        return SimpleNamespace(stdout=b'{"terms":["Synthetic seed","One","one","Two"]} [end of text]\r\n')
    monkeypatch.setenv("GH_TOKEN","fixture")
    monkeypatch.setenv("LLAMA_ARG_MODEL","other")
    monkeypatch.setattr(local.subprocess,"run",fake)
    report = local.LocalAssistant(tmp_path).propose_terms("synthetic seed")
    assert report["terms"] == ["One","Two"] and report["model_sha256"] == local.MODEL_SHA256
    assert len(report["prompt_sha256"]) == len(report["response_sha256"]) == 64


@pytest.mark.skipif(os.environ.get("RESEARCHY_TEST_INSTALLED_MODEL") != "1",
                    reason="Explicit installed Windows local model acceptance")
def test_installed_model_ordinary_desktop_review_and_reopen(tmp_path):
    project = create_project(tmp_path, "Installed model acceptance")
    model = local.LocalAssistant(Path(os.environ["LOCALAPPDATA"])/"RESEARCH-Y"/"models"/local.PACKAGE)
    assert model.installed
    with closing(RealProjectFlow(selected_root=project.root, selected_parent=tmp_path, local_assistant=model)) as flow:
        flow.open_selected()
        flow.edit_setup("heading", {"theme":"Synthetic critical care search", "approved_by":"Fixture reviewer"})
        gid = flow.edit_setup("add_group", {"label":"Unit"})["strategy_draft"]["groups"][0]["group_id"]
        state = flow.edit_setup("add_term", {"group_id":gid, "text":"intensive care unit"})
        tid = state["strategy_draft"]["groups"][0]["terms"][0]["term_id"]
        draft = perform_action(flow,"local_suggest",{"group_id":gid,"term_id":tid})["strategy_draft"]
        assert len(draft["groups"][0]["terms"]) == 1
        accepted = next(s for s in draft["suggestions"] if s["text"].casefold() == "icu")
        rejected = next(s for s in draft["suggestions"] if s is not accepted)
        flow.edit_setup("review_variant", dict(suggestion_id=rejected["suggestion_id"], decision="reject"))
        flow.edit_setup("review_variant", dict(suggestion_id=accepted["suggestion_id"], decision="accept", text="ICU"))
        flow.preview_setup()
        receipt = flow.approve_setup()["last_strategy_admission"]
    reopened = open_project(project.root)
    terms = get_strategy_snapshot(reopened,receipt["strategy_version_id"])["groups"][0]["terms"]
    assert [t["text"] for t in terms] == ["intensive care unit", "ICU"] and terms[1]["origin"] == "ai"
    queries = list_run_queries(reopened,receipt["run_id"])
    assert len(queries) == 2 and all(q.status == "pending" and q.reported_matches is None for q in queries)
