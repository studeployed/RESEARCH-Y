from contextlib import closing
from uuid import uuid4

import pytest

from research_y import preflight_review, query_compiler, result_counts
from research_y.desktop.flow import RealProjectFlow
from research_y.projects import create_project, open_project
from research_y.pubmed_probe import _review_translation
from research_y.run_execution_board import read_run_execution_board
from research_y.storage import ApprovedTerm, StrategyGroup
from research_y.strategy_admission import commit_approved_strategy
from research_y.wos_starter import validate_request, WoSStarterError
from test_gui_strategy_setup import _seed
from test_run_execution_board import _pubmed
from test_pubmed_pilot import _call, _client
from test_wos_starter_pilot import client as wos_client, submit


def test_bounded_executable_chunks_and_overlapping_identifier_union_survive_reopen(tmp_path):
    project=create_project(tmp_path,"Chunked search")
    scope=query_compiler.search_scope(pubmed_bytes=41,wos_bytes=24)
    args=dict(theme="Comparative care",groups=[StrategyGroup("g","Group",tuple(
              ApprovedTerm(t,"researcher",True) for t in ("first term","second term","third term")))],
              approved_by="Reader",request_id=str(uuid4()),approval_confirmed=True,scope=scope)
    plan=commit_approved_strategy(project,**args)
    assert not commit_approved_strategy(project,**args).newly_created
    pre=preflight_review.read_preflight(project,plan.run_id)
    sources={s["source_name"]:s["queries"] for s in pre["sources"]}
    assert len(sources["pubmed"])==len(sources["wos"])==3
    for name,queries in sources.items():
        assert all(len(q["exact_query"].encode())<=scope[name+"_bytes"] for q in queries)
        assert [t for q in queries for t in ("first term","second term","third term") if t in q["exact_query"]]==[
                "first term","second term","third term"]
    for i,q in enumerate(sources["pubmed"]):
        _pubmed(project,q["query_id"],q["exact_query"],pmids=("111",str(222+i)))
    reopened=open_project(project.root)
    group=next(s for s in result_counts.read_run_counts(reopened,plan.run_id).groups[0]["sources"]
               if s["source_name"]=="pubmed")
    assert group["reported_matches"] is None and group["retrieved_source_records"]==4
    assert read_run_execution_board(reopened,plan.run_id)["approved_query_inventory_matches"]


def test_source_and_year_choices_reach_normal_desktop_and_cannot_hide_omissions(tmp_path):
    project=create_project(tmp_path,"Selected source")
    with closing(RealProjectFlow()) as flow:
        flow.open_native_folder(project.root)
        _seed(flow)
        flow.edit_setup("scope",dict(sources=["wos"],publication_year=2020))
        preview=flow.preview_setup()["strategy_draft"]["preview"]
        assert [s["name"] for s in preview["sources"]]==["wos"] and "2020" in preview["limitations"]
        exact=preview["sources"][0]["groups"][0]["chunks"][0]
        validate_request(exact,"WOS",1,50)
        assert exact.endswith(" AND PY=2020")
        with pytest.raises(WoSStarterError):
            validate_request(exact+" OR PY=2021","WOS",1,50)
        rid=flow.approve_setup()["last_strategy_admission"]["run_id"]
        flow.select_run(rid)
        pre=flow.inspect_preflight()["preflight_report"]
        assert pre["sources"][0]["queries"][0]["exact_query"]==exact and "2020" in pre["limitations"]
        assert not read_run_execution_board(project,rid)["primary_source_enumerations_reconciled"]


def test_publication_year_translation_preserves_boolean_scope_and_independent_create_date_window():
    root='(("gas"[All Fields] OR "air"[All Fields]) AND 2020/01/01:2020/12/31[Date - Publication])'
    translated=root.replace("[Date - Publication]","[dp]")
    assert not _review_translation(root,translated,())
    assert _review_translation(root,translated.replace("2020/12/31","2021/12/31"),())
    assert _review_translation(root,translated.replace('("gas"', '"gas"').replace('Fields])','Fields]'),())
    partition=f"({root}) AND (2019/01/01:2022/12/31[crdt])"
    reply=partition.replace("[crdt]","[Date - Create]").replace("[Date - Publication]","[pdat]")
    assert not _review_translation(partition,reply,(),allow_crdt_partition=True)


def test_combined_source_pilots_and_known_item_corrections_are_bound_to_query(tmp_path):
    project=create_project(tmp_path,"Pilot workload")
    with closing(RealProjectFlow()) as flow:
        flow.open_native_folder(project.root)
        _seed(flow)
        flow.preview_setup()
        rid=flow.approve_setup()["last_strategy_admission"]["run_id"]
        flow.select_run(rid)
        pre=flow.inspect_preflight()["preflight_report"]
        sha=pre["plan_sha256"]
        queries={s["source_name"]:s["queries"][0] for s in pre["sources"]}
        pm,wo=queries["pubmed"],queries["wos"]
        _call(project,rid,sha,pm,_client(expected_query=pm["exact_query"],count=201))
        submit(project,rid,sha,wo,wos_client(count=101))
        result=flow.inspect_preflight()["preflight_report"]
        assert result["provider_counts"] is None
        assert result["pilot_observations"][pm["query_id"]]["reported_matches"] == 201
        assert result["pilot_observations"][wo["query_id"]]["reported_matches"] == 101
        assert result["estimated_workload"][pm["query_id"]]==dict(result_pages=2,metadata_batches=11)
        assert result["estimated_workload"][wo["query_id"]]==dict(result_pages=3,metadata_batches=None)
        details=dict(query_id=pm["query_id"],identifier="PMID 12345",outcome="found",
                     checked_on="2025-01-01",actor="Researcher",basis="Compared the exact source query with the PMID.")
        before=flow.record_known_check(sha,**details)["preflight_report"]["known_item_checks"]
        assert len(flow.record_known_check(sha,**details)["preflight_report"]["known_item_checks"])==1
        flow.record_known_check(sha,**dict(details,outcome="inconclusive",basis="Rechecked the identifier."))
    seen=preflight_review.read_preflight(open_project(project.root),rid)["known_item_checks"]
    assert [r["outcome"] for r in seen]==["found","inconclusive"] and seen[-1]["previous_event_id"]==before[0]["event_id"]
    from openpyxl import load_workbook
    from research_y import master_results, master_exports
    with closing(master_results.MasterResults.capture(project,rid)) as master:
        master_exports.export_results(project,master,tmp_path/"Checks.xlsx",master_results.DEFAULT,scope="entire")
    with closing(load_workbook(tmp_path/"Checks.xlsx",read_only=True)) as book:
        assert [r[4] for r in list(book["Known Item Checks"].values)[1:]]==["found","inconclusive"]
