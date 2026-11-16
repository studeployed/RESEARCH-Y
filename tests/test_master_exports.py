from contextlib import closing
from hashlib import sha256
import sqlite3
import json
from uuid import uuid4

from openpyxl import load_workbook
import pytest

from research_y import master_exports, master_results
from research_y.conference_project import admit_extraction, preview_extraction
from research_y.society_sources import import_guidance, record_society_visit
from test_conference_jats import XML
from test_reviewed_master import populated, decide
from test_society_sources import register,visit_args


@pytest.mark.parametrize("decision", ["confirmed_match", "rejected_match"])
def test_export_preserves_prior_confidence_evidence_separately_from_final_decision(tmp_path, decision):
    from research_y import publication_identity
    from research_y.publication_match_evidence import REPEAT_CONFIRMATION_RULE
    from test_publication_candidates import metadata, seed
    from test_run_execution_board import _project

    project, run, queries = _project(tmp_path)
    providers = ("pubmed", "wos")
    earlier = [seed(project, metadata(provider), provider) for provider in providers]
    prior = decide(project, *earlier, "confirmed_match").prior_decisions[-1]["event_id"]
    current = []
    with closing(sqlite3.connect(project.database_path)) as db, db:
        for provider, earlier_id in zip(providers, earlier):
            rid = str(uuid4())
            db.execute("INSERT INTO source_retrievals SELECT ?,?,source_name,source_record_id,"
                       "retrieved_at_utc,original_metadata_json FROM source_retrievals WHERE retrieval_id=?",
                       (rid, run, earlier_id))
            db.execute("INSERT INTO query_retrievals VALUES(?,?,?,?)",
                       (queries["g-ecmo", provider][0], rid, run, provider))
            current.append(rid)
    for rid in current:
        publication_identity.materialise_retrieval(project, rid, actor="Fixture")
    reviewed = decide(project, *current, decision)
    receipt = reviewed.prior_decisions[-1]["event_id"]
    with closing(master_results.MasterResults.capture(project, run)) as master:
        path = tmp_path / "Repeat.xlsx"
        master_exports.export_results(project, master, path, master_results.DEFAULT, scope="entire")
    with closing(load_workbook(path, read_only=True)) as book:
        values = iter(book["Deduplication Audit"].values)
        header = next(values)
        decisions = [dict(zip(header, row)) for row in values if row[0] == "Comparison decision"]
        assert len(decisions) == 1
        assert decisions[0]["Audit event"] == receipt
        assert decisions[0]["Status"] == decision
        assert decisions[0]["Confidence rule"] == REPEAT_CONFIRMATION_RULE
        assert decisions[0]["Prior confirmation event"] == prior


def test_real_workbook_preserves_sources_scope_raw_counts_and_abstract_permissions(tmp_path):
    project,run,_,ids=populated(tmp_path)
    decide(project,ids["111"],ids["WOS:000000001"],"confirmed_match")
    decide(project,ids["111"],ids["222"],"rejected_match")
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
        master_results.save_view(project,"Societies",spec)
        file=tmp_path/"Combined.xlsx"
        receipt=master_exports.export_results(project,results,file,spec,scope="entire")
        assert receipt["rows"]==5 and sha256(file.read_bytes()).hexdigest()==receipt["sha256"]
        with closing(load_workbook(file)) as workbook:
            assert {"Search Summary","Master Results","Methods","Source Records","Society Guidelines",
                    "Conference Abstracts","Deduplication Audit","Search Log","Search Terms","Executed Queries",
                    "Reporting Checklist"} <= set(workbook.sheetnames)
            evidence={row[1]:row[2] for row in list(workbook["Reporting Checklist"].values)[1:]}
            assert evidence["Independent peer review"]=="awaiting verification"
            source_item=next(r for r in workbook["Reporting Checklist"].values if r[1]=="Information sources")
            assert "society" in source_item[3] and "conference_jats" in source_item[3]
            assert "strategy/count report only" not in str(list(workbook["Methods"].values))
            assert workbook["Master Results"].max_row==6 and workbook["Master Results"].freeze_panes=="B2"
            assert workbook["Master Results"].auto_filter.ref=="A1:V6"
            chosen=next(c for c in workbook["Master Results"]["B"] if c.value=="=Example guidance")
            assert chosen.data_type=="s"
            assert workbook["Society Guidelines"]["D2"].value and workbook["Conference Abstracts"].max_row==3
            assert workbook["Society Guidelines"]["C2"].hyperlink.target=="https://society.example/guidance"
            assert any(c.hyperlink and c.hyperlink.target.endswith("#page=8") for c in workbook["Conference Abstracts"]["F"])
            summary=list(workbook["All-source Summary"].values)
            assert any(r[0]=="Run" and r[3:]==("global_unique_publications","Unverified") for r in summary)
            assert any(r[0]=="Run" and r[3:]==("extracted_individual_abstracts",2) for r in summary)
            assert any(r[2:]==("society","visits_linked_to_this_run",1) for r in summary)
            decisions=[r for r in list(workbook["Deduplication Audit"].values) if r[0]=="Comparison decision"]
            assert {r[5] for r in decisions}=={"confirmed_match","rejected_match"} and all(r[6] and r[7] for r in decisions)
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
        for extension in ("xlsx","ris"):
            restricted=tmp_path/("restricted."+extension)
            master_exports.export_results(project,results,restricted,spec,scope="entire",include_abstracts=True,
                                          abstract_sources=["pubmed"])
            if extension=="xlsx":
                with closing(load_workbook(restricted,read_only=True)) as workbook:
                    contents=str([row for ws in workbook for row in ws.values])
            else:
                contents=restricted.read_text(encoding="utf-8")
            assert "PRIVATE ABSTRACT" in contents and "https://example.test/abstract/P12" in contents
            assert "Right ventricle assessment." not in contents and "ECMO activity." not in contents


def test_empty_ris_has_scope_and_status_without_fabricating_a_publication(tmp_path,monkeypatch):
    project,run,_,_=populated(tmp_path)
    empty=master_results.specification(text="no-publication-here")
    path=tmp_path/"Empty.ris"
    receipt=tmp_path/"Empty.ris.json"
    with closing(master_results.MasterResults.capture(project,run)) as master:
        def export():
            return master_exports.export_results(project,master,path,empty,scope="filtered")
        receipt.write_text("Other researcher's file")
        with pytest.raises(FileExistsError):
            export()
        assert not path.exists() and receipt.read_text()=="Other researcher's file"
        receipt.unlink()
        real_link=master_exports.os.link
        def interrupt(src,dst):
            if dst==path:
                raise OSError("interrupted")
            real_link(src,dst)
        with monkeypatch.context() as patch:
            patch.setattr(master_exports.os,"link",interrupt)
            with pytest.raises(OSError,match="interrupted"):
                export()
    with closing(master_results.MasterResults.capture(project,run)) as reopened:
        result=master_exports.export_results(project,reopened,path,empty,scope="filtered")
        assert result["scope_filename"]==receipt.name and path.read_bytes()==b""
        saved=json.loads(receipt.read_bytes())
        assert saved["rows"]==0 and saved["sha256"]==sha256(b"").hexdigest()
        assert saved["context"]["status"]=="Incomplete" and saved["context"]["view"]==empty
        assert saved["context"]["run"]==run
        assert saved["context"]["snapshot_time"]!=reopened.captured_at


def test_reopened_nonempty_ris_recovers_original_bytes_and_rejects_changed_selection(tmp_path):
    project,run,_,_=populated(tmp_path)
    path=tmp_path/"Recovered.ris"
    with closing(master_results.MasterResults.capture(project,run)) as master:
        spec=master_results.specification(text="PRIVATE")
        master.select(spec,all_matching=True)
        original=master_exports.export_results(project,master,path,spec,scope="selected")
        body=path.read_bytes()
    path.unlink()
    with closing(master_results.MasterResults.capture(project,run)) as master:
        with pytest.raises(FileExistsError):
            master_exports.export_results(project,master,path,spec,scope="selected")
        assert not path.exists()
        master.select(spec,all_matching=True)
        assert master_exports.export_results(project,master,path,spec,scope="selected")==original
    assert path.read_bytes()==body


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
        text="=A"*45_000
        rows[0]["source_evidence"][0]["abstract_text"]=text
        book=tmp_path/"Long.xlsx"
        master_exports._workbook(book,results,rows,report,{},True,3)
        with closing(load_workbook(book)) as workbook:
            assert "Continued Text 2" in workbook.sheetnames
            parts=[r for sheet in workbook if sheet.title.startswith("Continued Text")
                   for r in list(sheet.values)[1:] if r[2]=="Abstract text"]
            assert len(parts)>1 and "".join(r[-1] for r in sorted(parts,key=lambda r:r[3]))==text
