"""Permission-confirmed PDF attachments bound to publication identity and portable source evidence."""
from hashlib import sha256
import os
from pathlib import Path
import tempfile
from uuid import UUID,uuid5

from research_y import publication_identity as identity
from research_y.application_inspection import _read
from research_y.export_files import Directory,MAX_ARTIFACT_BYTES
from research_y.projects import _utc_now,_validated_project_connection
from research_y.society_sources import web_url

EVENT = "publication_pdf_attachment_v1"


def attach_pdf(project,publication_id,path,*,actor,source_url,permission_confirmed):
    identity._identifier(publication_id)
    identity._text(actor,200)
    if permission_confirmed is not True:
        raise ValueError("Confirm permission to retain this PDF in the project")
    if source_url:
        web_url(source_url)
    path=Path(path)
    if path.suffix.lower()!=".pdf":
        raise ValueError("Select a local PDF")
    with Directory(path.parent) as source:
        payload=source.read_selected(path.name,limit=MAX_ARTIFACT_BYTES)
    if not payload.startswith(b"%PDF-"):
        raise ValueError("Selected file does not have a PDF header")
    digest=sha256(payload).hexdigest()
    name=digest+".pdf"
    relative="documents/"+name
    doc_id=str(uuid5(UUID(publication_id),identity._json([digest,source_url or None])))
    with Directory(project.root/"documents") as docs, _validated_project_connection(project) as db:
        db.execute("BEGIN IMMEDIATE")
        if not identity._snapshot(db,publication_id).active:
            raise ValueError("Select an active publication")
        # Content-addressed file survives a lost response or transaction rollback.
        # A retry verifies it before any database link becomes visible.
        if not docs.exists(name):
            with tempfile.NamedTemporaryFile(dir=docs.path,prefix=".attachment-",delete=False) as temp:
                stage=Path(temp.name)
            try:
                with stage.open("wb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                try:
                    os.link(stage,docs.path/name)
                except FileExistsError:
                    pass
                docs.sync()
            finally:
                stage.unlink(missing_ok=True)
        docs.read(name,digest=digest,size=len(payload))
        prior=db.execute("SELECT relative_path,external_url,provenance_json FROM documents WHERE document_id=?",
                         (doc_id,)).fetchone()
        if prior:
            event=identity._event(db,identity._object(prior[2])["event_id"],EVENT)
            if (prior[0],prior[1],event["source_sha256"])!=(relative,source_url or None,digest):
                raise ValueError("Existing attachment provenance differs")
            return event
        event=dict(version=1,at_utc=_utc_now(),document_id=doc_id,publication_id=publication_id,
                   original_filename=path.name,source_sha256=digest,size=len(payload),source_url=source_url or None,
                   relative_path=relative,actor=actor,rights="local_retention_confirmed")
        event_id=identity._audit(db,EVENT,event)
        db.execute("INSERT INTO documents VALUES(?,?,?,?,?,?)",(doc_id,publication_id,None,relative,source_url or None,
                   identity._json({"event_id":event_id})))
        return event


def list_attachments(project,publication_id):
    with _read(project) as db:
        rows=[]
        for doc,path,url,raw in db.execute(
                "SELECT document_id,relative_path,external_url,provenance_json FROM documents WHERE publication_id=? "
                "ORDER BY document_id",(identity._identifier(publication_id),)):
            pointer=identity._object(raw).get("event_id")
            if pointer is None:
                rows.append(dict(document_id=doc,relative_path=path,source_url=url,verified_provenance=False))
                continue
            event=identity._event(db,pointer,EVENT)
            if (event["document_id"],event["publication_id"],event["relative_path"],event["source_url"])!=(doc,publication_id,path,url):
                raise ValueError("Attachment source and audit disagree")
            _check_location(event)
            with Directory(project.root/"documents") as docs:
                docs.read(Path(path).name,digest=event["source_sha256"],size=event["size"])
            rows.append(dict(event,verified_provenance=True))
        return rows


def _check_location(event):
    digest=event["source_sha256"]
    if (not isinstance(digest,str) or len(digest)!=64 or any(ch not in "0123456789abcdef" for ch in digest)
            or event["relative_path"]!="documents/"+digest+".pdf" or type(event["size"]) is not int
            or not 0<event["size"]<=MAX_ARTIFACT_BYTES):
        raise ValueError("Invalid attachment file receipt")


def expected_archived_files(db):
    rows=db.execute("SELECT event_id FROM audit_events WHERE event_type=?",(EVENT,))
    expected={}
    for eid, in rows:
        event=identity._event(db,eid,EVENT)
        _check_location(event)
        doc=db.execute("SELECT publication_id,relative_path,external_url,provenance_json FROM documents WHERE document_id=?",
                       (event["document_id"],)).fetchone()
        if (doc is None or doc[:3]!=(event["publication_id"],event["relative_path"],event["source_url"])
                or identity._object(doc[3]).get("event_id")!=eid):
            raise ValueError("Missing or inconsistent archive attachment evidence")
        expected[event["relative_path"]]=dict(sha256=event["source_sha256"],size=event["size"])
    return expected
