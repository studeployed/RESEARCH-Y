from contextlib import closing
from hashlib import sha256
from uuid import uuid4

from openpyxl import load_workbook
import pytest

from research_y import master_exports, master_results
from research_y.conference_project import admit_extraction, preview_extraction
from research_y.society_sources import import_guidance, record_society_visit
from test_conference_jats import XML
from test_reviewed_master import populated, decide
from test_society_sources import register,visit_args


def test_real_workbook_preserves_sources_scope_raw_counts_and_abstract_permissions(tmp_path):
    project,run,_,ids=populated(tmp_path)
    decide(project,ids["111"],ids["WOS:000000001"],"confirmed_match")
    original=ids["111"]
    preview=preview_extraction(project,original,XML,pdf_url="https://example.test/supp.pdf",pdf_pages={"a":8})
    admit_extraction(project,original,XML,locators=[r["locator"] for r in preview["extraction"]["abstracts"]],
                     expected_revision=preview["revision"],actor="Reviewer",confirmed=True,retention_authorized=True,
                     pdf_url="https://example.test/supp.pdf",pdf_pages={"a":8})
    org=register(project)
    visit=record_society_visit(project,**visit_args(org))
    import_guidance(project,run_id=run,request_id=str(uuid4()),visit_event_id=visit["event_id"],
                    record={"title":"=Example guidance","document_types":["clinical practice guideline"],
                            "landing_url":"https://society.example/guidance"},
                    roles={"issuing":[org["society_id"]]},actor="Reviewer",confirmed=True)
    spec=master_results.specification(facets={"source":["society"]})
    with closing(master_results.MasterResults.capture(project,run)) as results:
        file=tmp_path/"Combined.xlsx"
        receipt=master_exports.export_results(project,results,file,spec,scope="entire")
        assert receipt["rows"]==5 and sha256(file.read_bytes()).hexdigest()==receipt["sha256"]
        with closing(load_workbook(file)) as workbook:
            assert {"Search Summary","Master Results","Methods","Source Records","Society Guidelines",
                    "Conference Abstracts","Deduplication Audit","Search Log","Search Terms","Executed Queries"} <= set(workbook.sheetnames)
            assert workbook["Master Results"].max_row==6 and workbook["Master Results"].freeze_panes=="B2"
            assert workbook["Master Results"].auto_filter.ref=="A1:O6"
            chosen=next(c for c in workbook["Master Results"]["B"] if c.value=="=Example guidance")
            assert chosen.data_type=="s"
            assert workbook["Society Guidelines"]["D2"].value and workbook["Conference Abstracts"].max_row==3
            assert set(r[-1] for r in list(workbook["Source Records"].values)[1:])=={"Omitted by export choice"}
        ris=tmp_path/"filtered.ris"
        assert master_exports.export_results(project,results,ris,spec,scope="filtered")["rows"]==1
        body=ris.read_text(encoding="utf-8")
        assert body.count("TY  - ")==1 and "TI  - =Example guidance" in body and '"scope":"filtered"' in body
        with pytest.raises(FileExistsError):
            master_exports.export_results(project,results,ris,spec,scope="filtered")
        results.select(master_results.specification(text="private abstract"),all_matching=True)
        selected=tmp_path/"selected.ris"
        assert master_exports.export_results(project,results,selected,spec,scope="selected",include_abstracts=True)["rows"]==1
        assert "AB  - PRIVATE ABSTRACT" in selected.read_text(encoding="utf-8")


def test_sheet_overflow(tmp_path):
    from openpyxl import Workbook
    book=Workbook(write_only=True)
    sheets=master_exports._Sheets(book,"Test",["Title"],3)
    for label in ["One","Two","Three","Four","Five"]:
        sheets.append((label,))
    sheets.finish()
    out=tmp_path/"split.xlsx"
    book.save(out)
    with closing(load_workbook(out)) as actual:
        assert [s.title for s in actual] == ["Test","Test 2","Test 3"]
        assert [r[0] for s in actual for r in list(s.values)[1:]]==["One","Two","Three","Four","Five"]


def test_long_abstract_is_recoverable_from_continuation_cells(tmp_path):
    from research_y.strategy_report import capture_strategy_report
    project,run,_,_=populated(tmp_path)
    report=capture_strategy_report(project,run)
    with closing(master_results.MasterResults.capture(project,run)) as results:
        rows=list(results.records(master_results.DEFAULT,"entire"))
        text="=A"*20_000
        rows[0]["source_evidence"][0]["abstract_text"]=text
        book=tmp_path/"Long.xlsx"
        master_exports._workbook(book,results,rows,report,{},True,1_048_576)
        with closing(load_workbook(book)) as workbook:
            parts=[r for r in list(workbook["Continued Text"].values)[1:] if r[2]=="Abstract text"]
            assert len(parts)>1 and "".join(r[-1] for r in sorted(parts,key=lambda r:r[3]))==text
