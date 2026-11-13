from contextlib import closing
from io import BytesIO

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from research_y import conference_pdf, publication_identity
from research_y.desktop.flow import RealProjectFlow, ProjectFlowError
from research_y.projects import open_project
from research_y.result_counts import read_run_counts
from research_y.run_execution_board import read_run_execution_board
from research_y.study_classification import read_classification
from test_reviewed_master import populated, decide


def fixture_pdf():
    writer = PdfWriter()
    writer.add_blank_page(width=450,height=600)
    page = writer.add_blank_page(width=450,height=600)
    font = DictionaryObject({NameObject("/Type"):NameObject("/Font"),NameObject("/Subtype"):NameObject("/Type1"),
                             NameObject("/BaseFont"):NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"):
                                       DictionaryObject({NameObject("/F1"):writer._add_object(font)})})
    contents = DecodedStreamObject()
    contents.set_data(b"BT /F1 12 Tf 20 400 Td (S3) Tj 0 -20 Td (A01 Oxygen Study. Lee. First findings.) Tj "
                      b"0 -20 Td (A02 Mobility Study. Roy. Separate findings.) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(contents)
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


def test_single_page_verification_and_missing_text():
    payload = fixture_pdf()
    assert conference_pdf.read_page(payload,1)["status"] == "no_extractable_text"
    with pytest.raises(ValueError):
        conference_pdf.read_page(payload,3)
    view = conference_pdf.read_page(payload,2)
    assert view["status"] == "text_available"
    with pytest.raises(ValueError):
        conference_pdf.select_block(view,title="A01",excerpt="A01 Mobility")
    with pytest.raises(ValueError):
        conference_pdf.select_block(view,title="findings.",excerpt="findings.")


def test_native_pdf_two_blocks_reopen_with_distinct_printed_and_file_pages(tmp_path):
    project,run,_,ids = populated(tmp_path)
    decide(project,ids["111"],ids["WOS:000000001"],"confirmed_match")
    decide(project,ids["111"],ids["222"],"rejected_match")
    before = read_run_execution_board(project,run)
    source = ids["111"]
    local = tmp_path/"abstracts [été].pdf"
    local.write_bytes(fixture_pdf())
    admitted = []
    with closing(RealProjectFlow()) as flow:
        flow.open_native_folder(project.root)
        flow.select_run(run)
        page = flow.inspect_publications()["publication_page"]
        for row in page["rows"]:
            detail = flow.inspect_publication_detail(publication_id=row["publication_id"],revision=page["revision"])
            if any(r["retrieval_id"]==source for r in detail["publication_detail"]["source_retrievals"]):
                break
        state = flow.open_native_pdf(local,source_id=source,page=2)["specialist"]
        assert state["pdf_page"]["page"] == 2
        for title,author,body in (("Oxygen Study","Lee","First findings."),("Mobility Study","Roy","Separate findings.")):
            chosen = flow.specialist_action("pdf_select",dict(retrieval_id=source,title=title,
                      page_revision=state["pdf_page"]["revision"],
                      excerpt=f"{title}. {author}. {body}",authors=[author],printed_page="S3",
                      pdf_url="https://example.test/proceedings.pdf"))["specialist"]["pdf_block"]
            args = dict(retrieval_id=source,actor="Reviewer",revision=chosen["revision"])
            with pytest.raises(ProjectFlowError):
                flow.specialist_action("pdf_admit",dict(**args,retention_authorized=False))
            receipt = flow.specialist_action("pdf_admit",dict(**args,retention_authorized=True))["specialist"]["pdf_receipt"]
            admitted.append(receipt["admitted"][0]["publication_id"])
    project = open_project(project.root)
    assert len(set(admitted)) == 2
    for pub_id in admitted:
        original = publication_identity.read_publication(project,pub_id).retrievals[0]["original_metadata"]
        assert original["original_retrieval_id"] == source and original["provider"] == "conference_pdf"
        assert original["record"]["printed_first_page"] == "S3"
        assert original["record"]["pdf_page"] == 2 and original["record"]["pdf_page_url"].endswith("#page=2")
        assert read_classification(project,pub_id)["current"]["format"] == ["conference abstract"]
    after = read_run_execution_board(project,run)
    assert after["source_count_revision"] == before["source_count_revision"]
    assert after["supplementary_source_records"] == {"conference_pdf":2}
    assert read_run_counts(project,run).totals["extracted_individual_abstracts"] == 2
