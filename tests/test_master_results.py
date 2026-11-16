from contextlib import closing
import json
import sqlite3

from research_y import master_results
from research_y import master_exports, study_classification
from research_y.desktop.flow import RealProjectFlow
from research_y.projects import open_project
from research_y.run_execution_board import read_run_execution_board
from test_reviewed_master import populated,decide


def test_alternate_abstract_and_canonical_chosen_year():
    from types import SimpleNamespace
    assert master_results._abstract({"abstract_sections":[],"other_abstracts":[
        {"sections":[{"text":"Translated abstract"}]}]}) == "Translated abstract"
    dates=[{"kind":"article_electronic","year":"2025"}]
    source=dict(source_name="pubmed",source_record_id="111",source_sha256="0"*64,retrieval_id="retained",
                original_metadata={"source":"NCBI PubMed EFetch XML","record":{"publication_dates":dates}})
    selected=dict(value=dates,provenance=dict(retrieval_id="retained",path=["record","publication_dates"]))
    snapshot=SimpleNamespace(retrievals=[source],chosen_fields={"year":selected})
    assert master_results._citation(snapshot,[],"year") == "2025"


def test_frozen_master_search_facets_selection_and_saved_views(tmp_path):
    project,run,_,ids = populated(tmp_path)
    before = read_run_execution_board(project,run)
    with closing(master_results.MasterResults.capture(project,run)) as results:
        assert results.total==3
        options = results.options()
        assert set(options["source"])=={"pubmed","wos"}
        spec = master_results.specification(text="WOS:000000001",facets={"source":["wos"],"group":["g-ecmo"]},
                                           columns=["sources","groups","design"],sort="year",descending=True)
        page = results.page(spec)
        assert page["matching"]==1 and page["rows"][0]["sources"]==["wos"]
        results.select(spec,all_matching=True)
        assert len(list(results.records(spec,"selected")))==1
        assert len(list(results.records(spec,"entire")))==3
        assert list(results.records(spec,"selected")) == list(results.records(spec,"filtered"))
        results.select(spec,all_matching=True,remove=True)
        assert list(results.records(spec,"selected"))==[]
        assert results.page(master_results.specification(text="private abstract"))["matching"]==1
        assert master_results.save_view(project,"Evidence",spec) == master_results.save_view(project,"Evidence",spec)
    reopened = open_project(project.root)
    assert master_results.saved_views(reopened)["Evidence"]["spec"]==spec
    assert read_run_execution_board(reopened,run)["source_count_revision"]==before["source_count_revision"]


def test_post_retrieval_exclusions_preserve_ambiguous_selected_export_and_source_counts(tmp_path):
    project, run, _, _ = populated(tmp_path)
    before = read_run_execution_board(project, run)["source_count_revision"]
    with closing(master_results.MasterResults.capture(project, run)) as results:
        papers = [row["publication_id"] for row in results.records(master_results.DEFAULT,"entire")]
    for pid, dimension, label in [(papers[0], "language", "non-English"), (papers[1], "population", "non-human"),
                                  (papers[2], "language", "multilingual"), (papers[2], "population", "unclear")]:
        view = study_classification.read_classification(project,pid)
        study_classification.review_classification(project,pid,dimension=dimension,labels=[label],actor="Reviewer",
            rationale="Reviewed the original source",expected_revision=view["revision"],confirmed=True)
    spec = master_results.specification(hide_non_english=True,hide_non_human_only=True)
    with closing(master_results.MasterResults.capture(project,run)) as results:
        assert results.page(spec)["matching"] == 1
        results.select(spec,all_matching=True)
        assert [r["publication_id"] for r in results.records(spec,"selected")] == [papers[2]]
        assert len(list(results.records(spec,"entire"))) == 3
        receipt = master_exports.export_results(project,results,tmp_path/"Selected.ris",spec,scope="selected")
        assert receipt["rows"] == 1
        assert (tmp_path/"Selected.ris").read_text(encoding="utf-8").count("TY  -") == 1
        master_results.save_view(project,"Post-retrieval exclusions",spec)
    assert master_results.saved_views(open_project(project.root))["Post-retrieval exclusions"]["spec"] == spec
    assert read_run_execution_board(project,run)["source_count_revision"] == before


def test_desktop_merged_publication_has_both_originals_and_full_local_abstract(tmp_path):
    project,run,_,ids = populated(tmp_path)
    decide(project,ids["111"],ids["WOS:000000001"],"confirmed_match")
    with closing(RealProjectFlow()) as flow:
        flow.open_native_folder(project.root)
        flow.select_run(run)
        view = flow.master_action("capture",{})["master_results"]
        assert view["total"]==2
        merged = next(r for r in view["rows"] if len(r["sources"])==2)
        detail = flow.master_action("detail",dict(revision=view["revision"],id=merged["publication_id"]))["master_results"]["detail"]
        assert len(detail["source_evidence"])==2
        assert any(s["abstract"]=="PRIVATE ABSTRACT" for s in detail["source_evidence"])
        assert all(s["sha256"] for s in detail["source_evidence"])


def test_master_wos_abstract_lookup_source_link_and_citation_choice(tmp_path,monkeypatch):
    from research_y import crossref_client, publication_identity
    from test_run_execution_board import _project,_wos
    project,run,queries = _project(tmp_path)
    qid,query = queries["g-ecmo","wos"]
    doi = "10.1234/example"
    _wos(project,qid,query,extra_fields={"identifiers":{"doi":doi,"articleNumber":"e017"},
        "links":{"record":"https://example.test/work","bad":"file:///private"}})
    with closing(sqlite3.connect(project.database_path)) as db:
        rid, = db.execute("SELECT retrieval_id FROM source_retrievals").fetchone()
    paper = publication_identity.materialise_retrieval(project,rid,actor="Reviewer")
    original = crossref_client.enrich_publication
    def simulated(*args,**kwargs):
        response = {"status":"ok","message-type":"work","message":{"DOI":doi,"abstract":"Abstract from Crossref"}}
        return original(*args,**kwargs,transport=lambda req:(200,{},json.dumps(response).encode()))
    monkeypatch.setattr(crossref_client,"enrich_publication",simulated)
    with closing(RealProjectFlow()) as flow:
        flow.open_native_folder(project.root)
        flow.select_run(run)
        page = flow.master_action("capture",{})["master_results"]
        selection = dict(id=paper.publication_id,revision=page["revision"])
        detail = flow.master_action("detail",selection)["master_results"]["detail"]
        selection["publication_revision"] = detail["publication_revision"]
        source, = detail["source_evidence"]
        assert detail["enrichment"]["lookup_status"]=="not_queried" and not source["abstract"]
        assert source["identifiers"]["articleNumber"]=="e017" and "Source bad" not in source["links"]
        assert source["original_record"]["identifiers"]["articleNumber"]=="e017" and source["retrieved_at_utc"]
        assert flow.master_source_url(**selection,retrieval_id=rid,link="Source record")=="https://example.test/work"
        from unittest.mock import MagicMock
        from research_y.desktop.master_panel import render_master
        ui=MagicMock()
        ui.input.return_value.value="My WoS view"
        clicked={}
        def button(label,*,on_click):
            clicked[label]=on_click
            return MagicMock()
        ui.button.side_effect=button
        def act(action,data):
            assert action=="master_results"
            return flow.master_action(data["operation"],data["data"])
        render_master(ui,flow.state(),act,native=True)
        assert "My WoS view" in clicked["Save current view"]()["master_results"]["saved"]
        flow.master_action("detail",selection)
        looked = flow.master_action("lookup",dict(**selection,contact="reviewer@example.test",actor="Reviewer",
            confirmed=True))["master_results"]["detail"]
        assert looked["enrichment"]["current"]["fields"]["abstract"]=="Abstract from Crossref"
        assert not looked["source_evidence"][0]["abstract"]
        flow.master_action("choose_field",dict(**selection,retrieval_id=rid,field="title",actor="Reviewer",reason="Checked source"))
        assert flow.state()["master_results"] is None
    reopened = publication_identity.read_publication(open_project(project.root),paper.publication_id)
    assert reopened.chosen_fields["title"]["provenance"]["retrieval_id"]==rid
