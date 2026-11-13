from contextlib import closing
from functools import partial
import json
import sqlite3

import pytest

from research_y.cloud_terms import CloudTerms, LocalAssistantError
from research_y.desktop.actions import perform_action
from research_y.desktop.flow import RealProjectFlow, ProjectFlowError
from research_y.projects import create_project


def test_default_off_and_specific_transfer_authorization_in_desktop(tmp_path):
    project = create_project(tmp_path,"Private unrelated project name")
    configured = CloudTerms("fixture-model","test-only-key")
    calls = []
    def send(req):
        calls.append(req)
        assert req.full_url == "https://api.anthropic.com/v1/messages"
        assert req.get_header("X-api-key") == "test-only-key"
        return json.dumps({"type":"message","role":"assistant","model":"fixture-model","stop_reason":"end_turn",
                           "content":[{"type":"text","text":'{"terms":["ICU"]}'}]}).encode()
    class Fixture:
        preview = staticmethod(configured.preview)
        generate = staticmethod(partial(configured.generate, transport=send))
    with closing(RealProjectFlow(selected_root=project.root, selected_parent=tmp_path, cloud_assistant=Fixture())) as flow:
        flow.open_selected()
        flow.edit_setup("heading",{"theme":"unrelated private theme","approved_by":"Reviewer"})
        gid=flow.edit_setup("add_group",{"label":"Group"})["strategy_draft"]["groups"][0]["group_id"]
        st=flow.edit_setup("add_term",{"group_id":gid,"text":"intensive care unit"})
        tid=st["strategy_draft"]["groups"][0]["terms"][0]["term_id"]
        payload={"group_id":gid,"term_id":tid}
        with pytest.raises(ProjectFlowError):
            perform_action(flow,"cloud_offer",payload)
        assert not st["cloud_enabled"] and not calls
        perform_action(flow,"cloud_mode")
        offer = perform_action(flow,"cloud_offer",payload)["cloud_offer"]
        assert "unrelated" not in offer["payload"] and "test-only-key" not in str(offer)
        assert offer["model"] == "fixture-model" and "charge" in offer["cost_notice"] and calls == []
        with pytest.raises(ProjectFlowError,match="changed"):
            perform_action(flow,"cloud_confirm","stale")
        assert flow.state()["cloud_offer"] is None and not calls
        perform_action(flow,"cloud_offer",payload)
        draft=perform_action(flow,"cloud_confirm",offer["revision"])["strategy_draft"]
        assert len(calls)==1 and calls[0].data == offer["payload"].encode()
        assert [t["text"] for t in draft["groups"][0]["terms"]]==["intensive care unit"]
        assert draft["suggestions"][0]["text"]=="ICU"
        with pytest.raises(ProjectFlowError):
            perform_action(flow,"cloud_confirm",offer["revision"])
        assert len(calls)==1
    with closing(sqlite3.connect(project.database_path)) as db:
        rows=db.execute("SELECT event_type,details_json FROM audit_events WHERE event_type LIKE 'cloud_%' ORDER BY event_id").fetchall()
    assert [v[0] for v in rows]==["cloud_terms_authorized_v1","cloud_term_proposal_v1"]
    assert "test-only-key" not in str(rows)


def test_cloud_client_refuses_implicit_consent_and_incomplete_output():
    c=CloudTerms("fixture","key")
    rev=c.preview("seed")["revision"]
    with pytest.raises(LocalAssistantError,match="confirmation"):
        c.generate("seed",expected_revision=rev,confirmed=False,transport=lambda r:pytest.fail("Network"))
    with pytest.raises(LocalAssistantError,match="unavailable"):
        c.generate("seed",expected_revision=rev,confirmed=True,
                   transport=lambda r:b'{"type":"message","role":"assistant","stop_reason":"max_tokens"}')
    assert "secret-test-token" not in repr(CloudTerms("fixture","secret-test-token"))
