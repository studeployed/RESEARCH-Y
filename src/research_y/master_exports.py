"""Publish researcher-selected XLSX or RIS snapshots without overwriting an existing file."""
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import quote

from research_y import publication_identity as identity
from research_y import strategy_report, strategy_workbook
from research_y.application_inspection import _read
from research_y.export_files import Directory, filename
from research_y.master_results import evidence_head, specification
from research_y import publication_candidates
from research_y import preflight_review


def _value(value):
    if isinstance(value,(dict,list,tuple)):
        return json.dumps(value,sort_keys=True,ensure_ascii=False)
    return value


def _one_line(value):
    return " ".join(str(value).split())


def _press(db,run):
    version,raw=db.execute("SELECT v.strategy_version_id,v.snapshot_json FROM search_runs r JOIN strategy_versions v "
                           "ON v.strategy_version_id=r.strategy_version_id WHERE r.run_id=?",(run,)).fetchone()
    try:
        _,_,_,plan=preflight_review._matched_query_plan(db,run,version,raw,allow_started=True)
    except preflight_review.PreflightError:
        return "awaiting verification",None
    review,_=preflight_review._previous(db,run,plan)
    return "verified",review


def _method_rows(data,context):
    return [
        ("Workbook","RESEARCH-Y publication workbook v1"),("Software",data["software_version"]),
        ("Project and run",context.get("run",data["run"]["run_id"])),("Scope",context.get("scope","entire")),
        ("Original query counts","Whole-run counts remain separate from the number of rows exported."),
        ("Publication ID","A retained identity can link multiple source records and query memberships."),
        ("Source evidence","Each retrieval retains its own source identifier, SHA-256 and original fields."),
        ("Comparison decision","Researcher decision for a particular pair, with timestamp, rationale and warnings."),
        ("Abstract rights","Text inclusion follows the export's explicit permission choice."),
        ("Continued Text","Concatenate parts in numeric order for the listed worksheet, logical row and column."),
        ("Methods scope","Reporting evidence is limited to the selected run and the stored search activities."),
    ]


def _ris(out, rows, context, include_abstracts):
    count = 0
    for row in rows:
        tags = [("TY","CONF" if "conference abstract" in row["format"] else
                       "RPRT" if "society web document" in row["format"] else "JOUR" if row["journal"] else "GEN"),
                ("ID",row["publication_id"]),("TI",row["title"]),("PY",row["year"]),("JO",row["journal"]),("DO",row["doi"])]
        author_sets = []
        for source in row["source_evidence"]:
            metadata = source["fields"]
            names = []
            for author in metadata.get("authors") or source.get("specialist",{}).get("authors",[]):
                if isinstance(author,dict):
                    name = author.get("displayName") or author.get("collective_name") or ", ".join(
                        x for x in (author.get("last_name"),author.get("fore_name") or author.get("initials")) if x)
                else:
                    name = author
                if isinstance(name,str) and name.strip():
                    names.append(name)
            if names and names not in author_sets:
                author_sets.append(names)
            tags.append(("AN",source["source_record_id"]))
        if len(author_sets)==1:
            tags.extend(("AU",author) for author in author_sets[0])
        texts = {s["abstract_text"] for s in row["source_evidence"] if s["abstract_text"]}
        if include_abstracts and len(texts)==1:
            tags.append(("AB",next(iter(texts))))
        tags += [("KW",v) for v in row["design"] if v!="unclear"]
        tags.append(("N1",context))
        if len(author_sets)>1 or len(texts)>1:
            tags.append(("N1","Conflicting source versions are available in the project."))
        for tag,val in tags:
            if val:
                out.write(f"{tag}  - {_one_line(val)}\r\n")
        out.write("ER  - \r\n\r\n")
        count += 1
    return count


class _Sheets:
    def __init__(self, book, name, headers, row_limit):
        self.book,self.name,self.headers,self.limit = book,name,headers,row_limit
        self.part = self.written = 0
        self.ws = None
        self.new()

    def new(self):
        from openpyxl.styles import Font,PatternFill
        from openpyxl.utils import get_column_letter
        from openpyxl.cell import WriteOnlyCell
        if self.ws is not None:
            self.finish()
        self.part += 1
        self.ws = self.book.create_sheet(self.name if self.part==1 else f"{self.name} {self.part}")
        self.ws.freeze_panes = "B2"
        cells = []
        for index,label in enumerate(self.headers,1):
            self.ws.column_dimensions[get_column_letter(index)].width = min(55,max(19,len(label)+5))
            cell = WriteOnlyCell(self.ws,value=label)
            cell.font = Font(bold=True,color="FFFFFF")
            cell.fill = PatternFill("solid",fgColor="234359")
            cells.append(cell)
        self.ws.append(cells)
        self.written = 1

    def finish(self):
        from openpyxl.utils import get_column_letter
        self.ws.auto_filter.ref = f"A1:{get_column_letter(len(self.headers))}{self.written}"

    def append(self,values):
        from openpyxl.cell import WriteOnlyCell
        if self.written >= self.limit:
            self.new()
        cells = []
        for value in values:
            cell = WriteOnlyCell(self.ws)
            strategy_workbook._literal(cell,value)
            if isinstance(value,str) and value.startswith("https://doi.org/") and len(value)<=2048:
                cell.hyperlink = value
                cell.style = "Hyperlink"
            cells.append(cell)
        self.ws.append(cells)
        self.written += 1


def _workbook(path, results, rows, report, context, include_abstracts, row_limit, comparisons=(),press=("awaiting verification",None)):
    from openpyxl import Workbook
    book = Workbook(write_only=True)
    sheets = []
    def sheet(title,headers):
        tab = _Sheets(book,title,headers,row_limit)
        sheets.append(tab)
        return tab
    continued = sheet("Continued Text",("Worksheet","Logical row","Column","Part","Parts","Value"))
    def append(tab,values):
        clean = []
        for index,value in enumerate(values):
            value = _value(value)
            if isinstance(value,str):
                parts = strategy_workbook.text_parts(value)
                if len(parts)>1:
                    logical = (tab.part-1)*(row_limit-1)+tab.written
                    for part,chunk in enumerate(parts,1):
                        continued.append((tab.name,logical,tab.headers[index],part,len(parts),chunk))
                    value = f"See Continued Text / {tab.name} / {logical} / {tab.headers[index]}"
            clean.append(value)
        tab.append(clean)
    scope = sheet("Export Scope",("Field","Value"))
    for key,value in context.items():
        append(scope,(key,value))
    data = report.as_dict()
    for name,headers,values in strategy_workbook._tables(data,report):
        if name=="Report Snapshot":
            continue
        if name=="Methods":
            values=_method_rows(data,context)
        if name=="Warnings":
            values=[r for r in values if r[1] not in {"licensed_record_text_not_exported","methodology_review_not_established"}]
        tab=sheet(name,headers)
        for value in values:
            append(tab,value)
    checklist=sheet("Reporting Checklist",("Framework","Item","Evidence status","Observation"))
    append(checklist,("PRISMA-S","Information sources","recorded",sorted({q["source_name"] for q in data["queries"]})))
    for q in data["queries"]:
        append(checklist,("PRISMA-S","Query "+q["query_id"],"recorded" if q["executed_at_utc"] else "awaiting verification",
                          dict(source=q["source_name"],strategy=q["exact_query"],timestamp=q["executed_at_utc"],
                               status=q["status"],execution_evidence=q["execution_evidence"])))
    append(checklist,("PRISMA-S","Deduplication method","recorded","Current source associations and applicable comparison receipts in Deduplication Audit."))
    append(checklist,("PRISMA-S","Citation chasing","not undertaken in this workflow","No citation-chasing stage is recorded."))
    append(checklist,("PRISMA-S","Registry search","not applicable to these source connectors","Coverage is described for the selected databases."))
    status,review=press
    append(checklist,("PRESS","Programmatic plan validation",status,"Match to the approved stored source query inventory."))
    if review:
        for key,value in review["press_items"].items():
            append(checklist,("PRESS",key,value,dict(reviewer=review["reviewer_name"],role=review["reviewer_role"],
                                                    recorded_utc=review["occurred_at_utc"],notes=review["review_note"])))
        peer="reported by researcher" if review["reviewer_role"]=="independent_peer_reported" else "not undertaken"
    else:
        peer="awaiting verification"
    append(checklist,("PRESS","Independent peer review",peer,"The project records the researcher's account of peer review."))
    master = sheet("Master Results",("Publication ID","Title","Year","Journal","DOI","DOI link","Sources","Groups",
                      "Original research","Design","Format","Language","Population","Review status","Warnings"))
    sources = sheet("Source Records",("Publication ID","Retrieval ID","Provider","Source record","Citation fields",
                                      "Original SHA-256","Groups","Abstract text"))
    conf = sheet("Conference Abstracts",("Publication ID","Retrieval ID","Locator","Printed page","PDF page",
                                         "PDF page link","Individual fields","Containing supplement"))
    society = sheet("Society Guidelines",("Publication ID","Retrieval ID","Official landing URL","Society roles","Guidance fields"))
    audit = sheet("Deduplication Audit",("Evidence type","Publication ID","First retrieval","Second retrieval","Audit event",
                                         "Status","Researcher","Rationale","UTC","Acknowledged warnings"))
    included_sources = set()
    log = sheet("Search Log",("Query","Source","Recorded status","Time","Execution evidence","Warnings"))
    warnings = {r["query_id"]:r["warnings"] for r in data["counts"]["queries"]}
    for q in data["queries"]:
        append(log,(q["query_id"],q["source_name"],q["status"],q["executed_at_utc"],q["execution_evidence"],warnings[q["query_id"]]))
    count = 0
    for row in rows:
        pid,doi = row["publication_id"],row["doi"]
        append(master,(pid,row["title"],row["year"],row["journal"],doi,
            "https://doi.org/"+quote(doi,safe="/") if isinstance(doi,str) else None,row["sources"],row["groups"],
            row["original_research"],row["design"],row["format"],row["language"],row["population"],row["review_status"],row["warnings"]))
        for s in row["source_evidence"]:
            rid = s["retrieval_id"]
            append(sources,(pid,rid,s["source"],s["source_record_id"],s["fields"],s["sha256"],s["groups"],
                           s["abstract_text"] if include_abstracts else "Omitted by export choice"))
            included_sources.add(rid)
            append(audit,("Source association",pid,rid,None,s["decision_event"],s["decision_status"],None,None,None,None))
            special = s.get("specialist",{})
            if s["source"] in ("conference_pdf","conference_jats"):
                append(conf,(pid,rid,special.get("locator"),special.get("printed_first_page"),special.get("pdf_page"),
                             special.get("pdf_page_url"),special,s.get("container")))
            if s["source"]=="society":
                append(society,(pid,rid,special.get("landing_url"),s["society_roles"],special))
        count+=1
    for event in comparisons:
        if included_sources.intersection(event["pair"]):
            append(audit,("Comparison decision",None,*event["pair"],event["event_id"],event["status"],event["actor"],
                          event["evidence"],event["at_utc"],event["warnings_acknowledged"]))
    append(scope,("Exported publication rows",count))
    for tab in sheets:
        tab.finish()
    book.save(path)
    return count


def export_results(project, results, destination, spec, *, scope, include_abstracts=False, row_limit=1_048_576):
    path = Path(destination)
    filename(path.name)
    if (path.suffix.lower() not in {".ris",".xlsx"} or type(include_abstracts) is not bool
            or type(row_limit) is not int or not 3<=row_limit<=1_048_576 or str(project.identifier)!=results.project_id):
        raise ValueError("Invalid master export settings")
    spec = specification(**spec)
    with _read(project) as db:
        if evidence_head(db)!=results.audit_head:
            raise ValueError("Project changed. Refresh master results before exporting.")
        report = strategy_report._capture(db,project,results.run,results.captured_at)
        comparisons = publication_candidates._receipts(db,None) if path.suffix.lower()==".xlsx" else ()
        press = _press(db,results.run) if path.suffix.lower()==".xlsx" else None
    context = dict(project=results.project_id,run=results.run,strategy=results.strategy_id,
                   status="Incomplete",stored_run_status=results.run_status,scope=scope,
                   snapshot_time=results.captured_at,snapshot_revision=results.revision,
                   entire_publication_identities=results.total,view=spec if scope=="filtered" else None,
                   include_abstracts=include_abstracts)
    with Directory(path.parent) as target, tempfile.TemporaryDirectory(dir=path.parent,prefix=".researchy-report-") as temp:
        if path.exists():
            raise FileExistsError(path)
        stage = Path(temp)/path.name
        rows = results.records(spec,scope)
        if path.suffix.lower()==".ris":
            with stage.open("x",encoding="utf-8",newline="") as out:
                count = _ris(out,rows,identity._json(context),include_abstracts)
        else:
            count = _workbook(stage,results,rows,report,context,include_abstracts,row_limit,comparisons,press)
        digest = sha256()
        with stage.open("r+b") as out:
            for chunk in iter(lambda:out.read(1024*1024),b""):
                digest.update(chunk)
            os.fsync(out.fileno())
        os.link(stage,path)
        target.sync()
    return dict(filename=path.name,sha256=digest.hexdigest(),rows=count,scope=scope,revision=results.revision)
