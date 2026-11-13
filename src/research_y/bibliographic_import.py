"""Explicitly reviewed manual citations and RIS source records, separate from primary database hits."""
from hashlib import sha256
import re
from uuid import UUID,uuid5

from research_y import publication_identity as identity
from research_y.projects import _utc_now,_validated_project_connection
from research_y.society_sources import web_url


MAX_BYTES = 8*1024**2
EVENT = "manual_bibliographic_import_v1"
TYPES={"JOUR":"journal article","CONF":"conference abstract","CPAPER":"conference paper",
       "RPRT":"report","BOOK":"book","CHAP":"chapter","GEN":"other"}


def parse_ris(payload):
    if not isinstance(payload,bytes) or not 0<len(payload)<=MAX_BYTES:
        raise ValueError("Choose a RIS file up to 8 MiB")
    rows=[]
    fields=None
    tag=None
    for line in payload.decode("utf-8-sig").splitlines():
        if not line.strip():
            continue
        match=re.fullmatch(r"([A-Z0-9]{2})  -(?: (.*))?",line)
        if match is None:
            if fields is None or tag is None or not line[:1].isspace():
                raise ValueError("Invalid RIS field or continuation")
            fields[tag][-1]+="\n"+line.strip()
            continue
        tag,value=match[1],match[2] or ""
        if tag=="TY":
            if fields is not None or not value:
                raise ValueError("Incomplete previous RIS record")
            fields={"TY":[value]}
        elif fields is None:
            raise ValueError("Expected RIS type field")
        elif tag=="ER":
            if value or len(rows)>=10000:
                raise ValueError("Invalid RIS record end or file exceeds 10000 records")
            rows.append(fields)
            fields=tag=None
        else:
            fields.setdefault(tag,[]).append(value)
    if fields is not None or not rows:
        raise ValueError("Incomplete or empty RIS file")
    return rows


def _record(fields):
    def first(*keys):
        return next((v for k in keys for v in fields.get(k,[]) if v),None)
    date=first("PY","Y1")
    year=re.match(r"^([0-9]{4})(?:$|[/ -])",date.strip()) if date else None
    def single(*keys):
        value=first(*keys)
        return " ".join(value.split()) if value else None
    return dict(title=single("TI","T1","CT"),authors=[" ".join(a.split()) for a in fields.get("AU",fields.get("A1",[]))],
                year=year[1] if year else None,journal=single("JO","JF","T2"),doi=single("DO"),
                text=first("AB","N2"),url=first("UR"),types=[TYPES.get(first("TY"),"other")],
                pages=first("SP"),last_page=first("EP"),language=first("LA"))


def preview_ris(payload):
    rows=parse_ris(payload)
    return dict(sha256=sha256(payload).hexdigest(),records=rows,total=len(rows))


def admit_records(project,run,label,*,payload=None,manual=None,indices,revision,actor,confirmed):
    identity._identifier(run)
    identity._text(label,300)
    identity._text(actor,200)
    if confirmed is not True or (payload is None)==(manual is None):
        raise ValueError("Confirm the source and permission to retain the records")
    if manual is None:
        preview=preview_ris(payload)
    else:
        if not isinstance(manual,dict):
            raise ValueError("Expected one manual citation")
        title=identity._text(manual["title"],2000)
        if set(manual)-{"title","doi","url","year","type","authors","abstract"}:
            raise ValueError("Unsupported citation field")
        fields={"TY":[manual.get("type") or "GEN"],"TI":[title]}
        for name,tag in (("doi","DO"),("url","UR"),("year","PY"),("abstract","AB")):
            if manual.get(name):
                if name=="url":
                    web_url(manual[name])
                if name=="abstract":
                    text=manual[name]
                    if not isinstance(text,str) or len(text)>40_000 or any(ord(c)<32 and c not in "\n\r\t" for c in text):
                        raise ValueError("Invalid abstract text")
                    fields[tag]=[text]
                else:
                    fields[tag]=[identity._text(manual[name],4000)]
        if manual.get("authors"):
            if not isinstance(manual["authors"],list) or len(manual["authors"])>300:
                raise ValueError("Invalid author list")
            fields["AU"]=[identity._text(a,500) for a in manual["authors"]]
        preview=dict(sha256=identity._hash(fields),records=[fields],total=1)
    if (payload is not None and revision!=preview["sha256"] or not isinstance(indices,list) or not indices
            or any(type(i) is not int or not 0<=i<preview["total"] for i in indices) or len(set(indices))!=len(indices)):
        raise ValueError("Select distinct records in the current preview")
    kind="ris" if payload is not None else "manual"
    with _validated_project_connection(project) as db:
        db.execute("BEGIN IMMEDIATE")
        if not db.execute("SELECT 1 FROM search_runs WHERE run_id=?",(run,)).fetchone():
            raise ValueError("Select an existing run")
        admitted=[]
        for index in indices:
            fields=preview["records"][index]
            key=identity._hash([kind,label,preview["sha256"],index])
            rid=str(uuid5(UUID(run),key))
            original=dict(provider="manual_bibliographic",source_method=kind,supplied_by=label,
                          document_sha256=preview["sha256"],record_index=index+1,original_fields=fields,
                          record=_record(fields),rights_status="local_retention_confirmed")
            existing=db.execute("SELECT original_metadata_json FROM source_retrievals WHERE retrieval_id=?",(rid,)).fetchone()
            if existing is None:
                stamp=_utc_now()
                db.execute("INSERT INTO source_retrievals VALUES(?,?,?,?,?,?)",
                           (rid,run,"manual_bibliographic",key,stamp,identity._json(original)))
                pid=str(uuid5(UUID(rid),"publication"))
                db.execute("INSERT INTO publications(publication_id,created_at_utc) VALUES(?,?)",(pid,stamp))
                source=identity._source(db,rid)
                identity._record_link(db,source,before=None,after=pid,previous_event_id=None,status="review_required",
                        action="materialise",actor=actor,evidence="Reviewed manual bibliographic admission")
                identity._audit(db,EVENT,dict(version=1,at_utc=stamp,actor=actor,run_id=run,retrieval_id=rid,
                                publication_id=pid,source_sha256=source["source_sha256"],source_method=kind))
            elif identity._object(existing[0])!=original:
                raise ValueError("Stored import differs from selected evidence")
            link=identity._link(db,rid)
            if link is None:
                raise ValueError("Missing retained publication association")
            admitted.append(dict(retrieval_id=rid,publication_id=link[0],index=index+1))
        return dict(run_id=run,source=label,method=kind,admitted=admitted,document_sha256=preview["sha256"])
