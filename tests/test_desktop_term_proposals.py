from contextlib import closing

import pytest

from research_y.desktop.strategy_setup import StrategyDraft, DraftError
from research_y.storage import get_strategy_snapshot, list_run_queries
from research_y.terminology import lexical_variants
from test_gui_strategy_setup import _flow


def test_operational_approval_excludes_pending_and_rejected_variants(tmp_path):
    project, flow = _flow(tmp_path)
    with closing(flow):
        flow.edit_setup("heading", {"theme":"ECMO", "approved_by":"Reviewer"})
        gid = flow.edit_setup("add_group", {"label":"Support"})["strategy_draft"]["groups"][0]["group_id"]
        seed = flow.edit_setup("add_term", {"group_id":gid, "text":"venovenous ECMO"})
        tid = seed["strategy_draft"]["groups"][0]["terms"][0]["term_id"]
        data = {"group_id":gid, "term_id":tid}
        draft = flow.edit_setup("suggest_variants", data)["strategy_draft"]
        offers = {s["text"]:s for s in draft["suggestions"]}
        assert "veno-venous extracorporeal membrane oxygenation" in offers
        assert [t["text"] for t in draft["groups"][0]["terms"]] == ["venovenous ECMO"]
        flow.edit_setup("review_variant", {"suggestion_id":offers["veno-venous ECMO"]["suggestion_id"],
                                           "decision":"accept", "text":"veno-venous ECMO"})
        flow.edit_setup("review_variant", {"suggestion_id":offers["veno venous ECMO"]["suggestion_id"],
                                           "decision":"reject"})
        receipt = flow.preview_setup()
        assert receipt["strategy_draft"]["preview"]["active_term_count"] == 2
        admitted = flow.approve_setup()["last_strategy_admission"]
        saved = get_strategy_snapshot(project, admitted["strategy_version_id"])
        terms = saved["groups"][0]["terms"]
        assert [t["text"] for t in terms] == ["venovenous ECMO","veno-venous ECMO"]
        assert terms[1]["origin"] == "deterministic" and "clinical-lexical-variants/1" in terms[1]["rationale"]
        for query in list_run_queries(project, admitted["run_id"]):
            assert "veno-venous ECMO" in query.exact_query and "veno venous ECMO" not in query.exact_query
            assert query.reported_matches is None


def test_repeated_requests_reuse_offers_and_changed_seed_invalidates_them():
    draft = StrategyDraft()
    group = draft.add_group("Variants")
    tid = draft.add_term(group, "hemoglobin")
    draft.suggest_variants(group, tid)
    first, = draft.state()["suggestions"]
    draft.suggest_variants(group, tid)
    assert draft.state()["suggestions"] == [first]
    draft.edit_term(group, tid, "different seed", "researcher", "", True)
    with pytest.raises(DraftError):
        draft.review_variant(first["suggestion_id"], "accept")
    assert not draft.state()["suggestions"]
    assert not lexical_variants("pseudohemoglobin")
