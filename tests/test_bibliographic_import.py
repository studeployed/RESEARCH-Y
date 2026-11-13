from contextlib import closing
import pytest

from research_y import bibliographic_import as bib
from research_y.desktop.flow import RealProjectFlow
from research_y.master_results import MasterResults,DEFAULT
from research_y.projects import open_project
from research_y.run_execution_board import read_run_execution_board
from test_reviewed_master import populated,decide


def test_ris_and_manual_are_distinct_sources_and_preserve_primary_counts(tmp_path):
    project,run,_,ids=populated(tmp_path)
    decide(project,ids["111"],ids["WOS:000000001"],"confirmed_match")
    decide(project,ids["111"],ids["222"],"rejected_match")
    before=read_run_execution_board(project,run)
    path=tmp_path/"From library.ris"
    path.write_bytes(b"TY  - CONF\nTI  - Separate report\nAU  - Lee, A\nAB  - One paragraph\n  next line\n"
                     b"DO  - 10.5555/unique\nY1  - 2024/03/15/\nER  - \n\nTY  - CHAP\nTI  - Another report\nER  - \n")
    with closing(RealProjectFlow()) as flow:
        flow.open_native_folder(project.root)
        flow.select_run(run)
        view=flow.open_native_ris(path)["bibliography_preview"]
        assert view["titles"]==["Separate report","Another report"]
        args=dict(label="Fixture library",actor="Reviewer",confirmed=True,indices=[0,1],revision=view["revision"])
        with pytest.raises(ValueError):
            flow.import_bibliography(dict(args,confirmed=False))
        assert flow.import_bibliography(args)["import_receipt"]["count"]==2
        flow.open_native_ris(path)
        flow.import_bibliography(args)
        flow.import_bibliography(dict(label="Manual bibliography",actor="Reviewer",confirmed=True,indices=[0],revision=None,
                                 manual=dict(title="Third citation",year="2024",authors=["Researcher"],abstract="Line 1\nLine 2")))
    reopened=open_project(project.root)
    board=read_run_execution_board(reopened,run)
    assert board["source_count_revision"]==before["source_count_revision"] and board["supplementary_source_records"]=={"manual_bibliographic":3}
    with closing(MasterResults.capture(reopened,run)) as master:
        rows=list(master.records(DEFAULT,"entire"))
        assert len(rows)==5
        item=next(r for r in rows if r["title"]=="Separate report")
        assert item["doi"]=="10.5555/unique" and item["format"]==["conference abstract"] and item["year"]=="2024"
        assert next(r for r in rows if r["title"]=="Another report")["format"]==["book/chapter"]
        assert master.detail(reopened,item["publication_id"])["source_evidence"][0]["abstract"]=="One paragraph\nnext line"


def test_incomplete_or_invalid_ris_never_returns_partial_citations():
    original=bib.parse_ris(b"TY  - JOUR\nTI  - Long\n  original title\nER  - ")[0]
    assert original["TI"]==["Long\noriginal title"] and bib._record(original)["title"]=="Long original title"
    for payload in (b"",b"TY  - JOUR\nTI  - Partial",b"TI  - Without type\nER  - "):
        with pytest.raises(ValueError):
            bib.preview_ris(payload)
