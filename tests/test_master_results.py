from contextlib import closing

from research_y import master_results
from research_y.desktop.flow import RealProjectFlow
from research_y.projects import open_project
from research_y.run_execution_board import read_run_execution_board
from test_reviewed_master import populated,decide


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
