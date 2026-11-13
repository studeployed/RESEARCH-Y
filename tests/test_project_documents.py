from contextlib import closing

import pytest

from research_y import project_documents as docs
from research_y import project_archive
from research_y.desktop.flow import RealProjectFlow
from test_reviewed_master import populated


def test_selected_pdf_is_attributed_and_verified_after_archive_and_relocation(tmp_path):
    project,run,_,_=populated(tmp_path)
    pdf=tmp_path/"Proceedings.pdf"
    pdf.write_bytes(b"%PDF-1.4\nSynthetic fixture for attachment storage")
    with closing(RealProjectFlow()) as flow:
        flow.open_native_folder(project.root)
        flow.select_run(run)
        page=flow.master_action("capture",{})["master_results"]
        pid=page["rows"][0]["publication_id"]
        flow.master_action("detail",dict(id=pid,revision=page["revision"]))
        options=dict(publication_id=pid,source_url="https://example.test/report.pdf",actor="Researcher")
        with pytest.raises(ValueError):
            flow.attach_master_pdf(pdf,**options,permission_confirmed=False)
        for _ in range(2):
            detail=flow.attach_master_pdf(pdf,**options,permission_confirmed=True)["master_results"]["detail"]
            assert len(detail["attachments"])==1
    file=detail["attachments"][0]
    archive=tmp_path/"Transfer.researchy"
    project_archive.export_archive(project,archive,supporting_files=[file["relative_path"]],transfer_confirmed=True)
    restored=project_archive.import_archive(archive,tmp_path,directory_name="MovedProject")
    assert docs.list_attachments(restored,pid)==[file]
    assert (restored.root/file["relative_path"]).read_bytes()==pdf.read_bytes()
