from contextlib import closing
import os
import json
from pathlib import Path
import sqlite3

import pytest

from research_y.local_assistant import LocalAssistant, PACKAGE
from research_y.local_study_review import propose, review
from research_y.projects import open_project
from research_y.publication_identity import materialise_retrieval, StalePublicationError
from research_y.study_classification import read_classification
from test_publication_identity import store, protected_rows


def original(store):
    project, ids = store
    payload = dict(source="NCBI PubMed EFetch XML", record=dict(title="Rehabilitation trial",
              publication_types=["Randomized Controlled Trial","Conference Abstract"], languages=["eng"],
              abstract_status="present", abstract_sections=[{"text":"Adults were randomly allocated to two activity schedules. Results are reported."}]))
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute("UPDATE source_retrievals SET original_metadata_json=? WHERE retrieval_id=?",
                   (json.dumps(payload), ids[0]))
    pub_id = materialise_retrieval(project,ids[0],actor="Reviewer").publication_id
    return project,pub_id,ids[0]


def exercise(project,pub_id,rid,model):
    before = read_classification(project,pub_id)
    source_rows = protected_rows(project)
    suggestion = propose(project,pub_id,rid,assistant=model,expected_revision=before["revision"])
    unchanged = read_classification(open_project(project.root),pub_id)
    assert unchanged == before and unchanged["decisions"] == {}
    final = review(project,pub_id,event_id=suggestion["event_id"],dimension="original_research",labels=["yes"],
                   expected_revision=before["revision"],actor="Reviewer",rationale="Randomised study reports results",
                   confirmed=True)
    decision = final["decisions"]["original_research"]
    assert decision["proposal_event_id"] == suggestion["event_id"]
    assert read_classification(open_project(project.root),pub_id)["current"]["original_research"] == ["yes"]
    assert protected_rows(project) == source_rows
    with pytest.raises(StalePublicationError):
        propose(project,pub_id,rid,assistant=model,expected_revision=before["revision"])


def test_wrong_model_label_can_only_become_a_reviewed_researcher_decision(store):
    class Stub:
        def propose_study(self, text):
            assert "randomly allocated" in text
            return {"model":"synthetic", "proposals":{"original_research":["no"], "design":["RCT"]}}
    exercise(*original(store),Stub())


@pytest.mark.skipif(os.environ.get("RESEARCHY_TEST_INSTALLED_MODEL") != "1",reason="Explicit installed model evaluation")
def test_real_local_study_suggestion_is_provisional_and_reviewable(store):
    model = LocalAssistant(Path(os.environ["LOCALAPPDATA"])/"RESEARCH-Y"/"models"/PACKAGE)
    exercise(*original(store),model)
