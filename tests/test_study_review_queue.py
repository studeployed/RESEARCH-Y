from research_y import study_classification as service
from research_y.study_review_queue import read_study_page
from test_study_classification import set_record,review
from test_publication_identity import store, protected_rows
from contextlib import closing
from research_y.desktop.flow import RealProjectFlow
from research_y.desktop.actions import perform_action
from test_reviewed_master import populated


def test_filtered_and_review_only_views_report_page_denominators_without_mutations(store):
    project, ids=store
    first=set_record(project,ids[0],types=["Randomized Controlled Trial"],languages=["fra"])
    run=first.retrievals[0]["run_id"]
    second=service.identity.materialise_retrieval(project,ids[1],actor="Fixture")
    saved=protected_rows(project)
    page=read_study_page(project,run,only_review=False,hide_non_english=True)
    assert page["examined"]==2 and page["hidden_by_filter"]==1 and page["displayed"]==1
    assert page["rows"][0]["publication_id"]==second.publication_id
    view=service.read_classification(project,second.publication_id)
    review(project,view,"population","non-human")
    empty=read_study_page(project,run,only_review=False,hide_non_english=True,hide_non_human_only=True)
    assert empty["displayed"]==0 and empty["examined"]==empty["hidden_by_filter"]==2
    unfiltered=read_study_page(project,run,only_review=True,page_size=1)
    another=read_study_page(project,run,after=unfiltered["next_after"],only_review=True,page_size=1)
    assert another["next_after"] is None and unfiltered["examined"]==another["examined"]==1
    assert {v["publication_id"] for v in unfiltered["rows"]+another["rows"]}=={first.publication_id,second.publication_id}
    assert protected_rows(project)==saved


def test_desktop_review_queue_uses_visible_run_and_revision_fenced_decision(tmp_path):
    project,run,_,ids=populated(tmp_path)
    before=protected_rows(project)
    with closing(RealProjectFlow()) as flow:
        flow.open_native_folder(project.root)
        flow.select_run(run)
        opts=dict(only_review=False,hide_non_english=False,hide_non_human_only=True,after=None)
        state=perform_action(flow,"study_queue",opts)
        page=state["study_queue"]
        assert page["examined"]==page["displayed"]==len(ids)
        row=page["rows"][0]
        state=perform_action(flow,"study_queue_open",{"publication_id":row["publication_id"],"revision":row["revision"]})
        assert state["queued_study"]["publication_id"]==row["publication_id"]
        state=perform_action(flow,"study_confirm",dict(dimension="population",labels=["non-human"],actor="Reviewer",
                     rationale="Checked the original study",revision=row["revision"],event_id=None))
        assert state["queued_study"] is None
        page=state["study_queue"]
        assert page["hidden_by_filter"]==1 and page["displayed"]==len(ids)-1
    assert protected_rows(project)==before


def test_review_only_exclusions_contribute_to_page_denominator(store):
    project, ids = store
    paper = set_record(project, ids[0], types=["Randomized Controlled Trial","Journal Article"])
    view = service.read_classification(project,paper.publication_id)
    for dim,labels in view["current"].items():
        view = review(project,view,dim,*labels)
    page = read_study_page(project,paper.retrievals[0]["run_id"],only_review=True)
    assert page["examined"] == page["hidden_by_filter"] == 1
    assert page["displayed"] == 0
