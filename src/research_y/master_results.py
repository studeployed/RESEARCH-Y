"""Frozen, searchable run-specific publication rows backed by a private SQLite file."""
from hashlib import sha256
import json
import sqlite3

from research_y import publication_identity as identity
from research_y import study_classification
from research_y.application_inspection import _read
from research_y.publication_match_evidence import project_source
from research_y.publication_results import _citation_chosen_source
from research_y.projects import _utc_now, _validated_project_connection


COLUMNS = ("title","year","journal","doi","sources","groups",*study_classification.LABELS,"review_status")
SORTS = {"title":"title", "year":"year", "publication_id":"id"}
FACETS = {"source","group",*study_classification.LABELS,"review_status"}
DEFAULT = dict(text="",facets={},sort="title",descending=False,columns=["title","year","sources","design"])
SAVED = "master_results_view_saved_v1"


def specification(text="", facets=None, sort="title", descending=False, columns=None):
    if facets is None:
        facets = {}
    if columns is None:
        columns = DEFAULT["columns"]
    if (not isinstance(text,str) or len(text)>512 or not isinstance(facets,dict) or facets.keys()-FACETS
            or sort not in SORTS or type(descending) is not bool or not isinstance(columns,list)
            or not columns or len(columns)>len(COLUMNS) or any(c not in COLUMNS for c in columns)
            or len(set(columns))!=len(columns)):
        raise ValueError("Invalid master-results view")
    for values in facets.values():
        if (not isinstance(values,list) or not 1<=len(values)<=100 or
                any(not isinstance(v,str) or not v or len(v)>500 for v in values)):
            raise ValueError("Invalid facet values")
    return dict(text=text.strip(),facets={k:sorted(set(v)) for k,v in facets.items()},
                sort=sort,descending=descending,columns=list(columns))


def _abstract(record):
    if isinstance(record.get("abstract_sections"),list):
        return "\n".join(v["text"] for v in record["abstract_sections"]
                         if isinstance(v,dict) and isinstance(v.get("text"),str))
    return record["text"] if isinstance(record.get("text"),str) else ""


def _citation(snapshot, mappings, name):
    chosen = _citation_chosen_source(snapshot,name)
    if chosen is not None:
        return snapshot.chosen_fields[name]["value"]
    values = [m["fields"][name] for m in mappings if m["fields"][name]["status"]=="present"]
    if len({f["normalised"] for f in values}) != 1:
        return None
    if name in ("year","doi"):
        return values[0]["normalised"]
    return values[0]["value"]


def _rows(db,run):
    # Common singletons are read in one ordered join. Multi-source identities,
    # chosen fields and reviewed classifications use the canonical project services.
    members = {}
    for rid,gid,label in db.execute(
        "SELECT m.retrieval_id,q.group_id,g.label FROM query_retrievals m JOIN source_queries q "
        "ON m.query_id=q.query_id AND m.run_id=q.run_id AND m.source_name=q.source_name JOIN strategy_groups g "
        "ON g.strategy_version_id=q.strategy_version_id AND g.group_id=q.group_id WHERE m.run_id=? "
        "ORDER BY m.retrieval_id,q.group_id",(run,)):
        members.setdefault(rid,{})[gid] = label
    multiple = {r[0] for r in db.execute("SELECT publication_id FROM publication_retrievals "
                                          "GROUP BY publication_id HAVING COUNT(*)>1")}
    reviewed = {r[0] for r in db.execute("SELECT DISTINCT publication_id FROM classifications UNION "
                "SELECT json_extract(details_json,'$.publication_id') FROM audit_events WHERE event_type=?",
                (study_classification.EVENT,))}
    rows = db.execute(
        "SELECT r.retrieval_id,r.run_id,r.source_name,r.source_record_id,r.retrieved_at_utc,r.original_metadata_json,"
        "s.status,l.publication_id,l.decision_provenance_json,p.created_at_utc,p.chosen_metadata_json,"
        "a.event_id,a.event_type,a.occurred_at_utc,a.details_json FROM source_retrievals r "
        "JOIN search_runs s ON s.run_id=r.run_id JOIN publication_retrievals l ON l.retrieval_id=r.retrieval_id "
        "JOIN publications p ON p.publication_id=l.publication_id LEFT JOIN audit_events a "
        "ON a.event_id=json_extract(l.decision_provenance_json,'$.event_id') WHERE r.run_id=? "
        "ORDER BY l.publication_id,r.retrieval_id",(run,))
    previous = None
    for raw in rows:
        pid = identity._identifier(raw[7])
        if pid == previous:
            continue
        previous = pid
        if pid in multiple or pid in reviewed or raw[10]!="{}":
            snapshot = identity._snapshot(db,pid)
        else:
            source = identity._source_from_row(raw[:6],raw[6])
            identity._link_from_evidence(source,pid,raw[8],raw[11:])
            snapshot = identity.PublicationSnapshot(pid,raw[9],source["source_sha256"],(source,),{})
        if pid in reviewed:
            view = study_classification._view(db,pid)
            dimensions,statuses = view["current"],sorted(set(view["review_status"].values()))
            conflict = view["warnings"]
        else:
            dimensions,_,conflict = study_classification._proposals(snapshot)
            statuses = ["requires-review" if conflict else "machine-provisional"]
        sources = [s for s in snapshot.retrievals if s["run_id"]==run]
        mappings = [project_source(s) for s in sources]
        groups = {k:v for s in sources for k,v in members.get(s["retrieval_id"],{}).items()}
        originals = []
        searchable = [pid]
        for src,fields in zip(sources,mappings):
            record = src["original_metadata"].get("record")
            record = record if isinstance(record,dict) else {}
            citation = {k:v["value"] for k,v in fields["fields"].items() if v["status"]=="present"}
            entry = dict(retrieval_id=src["retrieval_id"],source=src["source_name"],source_record_id=src["source_record_id"],
                         sha256=src["source_sha256"],fields=citation,groups=members.get(src["retrieval_id"],{}))
            originals.append(entry)
            searchable.extend([entry["source_record_id"],identity._json(citation),_abstract(record)])
        row = dict(publication_id=pid,**{k:_citation(snapshot,mappings,k) for k in ("title","year","journal","doi")},
                   sources=sorted({s["source_name"] for s in sources}), groups=groups,**dimensions,
                   review_status=statuses,warnings=conflict,source_evidence=originals)
        yield row," ".join(searchable).casefold()


class MasterResults:
    """A disposable read projection. Selection and paging never change project records."""
    def __init__(self):
        self.db = sqlite3.connect("",check_same_thread=False)
        self.db.executescript(
            "CREATE TABLE rows(id TEXT PRIMARY KEY,title TEXT,year TEXT,search_text TEXT,record TEXT);"
            "CREATE INDEX by_title ON rows(title,id);CREATE INDEX by_year ON rows(year,id);"
            "CREATE TABLE facets(kind TEXT,value TEXT,id TEXT,PRIMARY KEY(kind,value,id)) WITHOUT ROWID;"
            "CREATE TABLE chosen(id TEXT PRIMARY KEY) WITHOUT ROWID;")

    @classmethod
    def capture(cls, project, run):
        identity._identifier(run)
        results = cls()
        try:
            with _read(project) as original, results.db:
                info = original.execute("SELECT strategy_version_id,status FROM search_runs WHERE run_id=?",(run,)).fetchone()
                if not info:
                    raise ValueError("Unknown run")
                results.project_id,results.run,results.strategy_id,results.run_status = str(project.identifier),run,*info
                results.captured_at = _utc_now()
                digest = sha256(identity._json([results.project_id,run,info]).encode())
                results.total = 0
                for row,search_text in _rows(original,run):
                    pid, record = row["publication_id"],identity._json(row)
                    digest.update(sha256(record.encode()).digest())
                    results.db.execute("INSERT INTO rows VALUES(?,?,?,?,?)",(pid,(row["title"] or "").casefold(),
                                       row["year"] or "",search_text,record))
                    values = dict(source=row["sources"],group=row["groups"],review_status=row["review_status"],
                                  **{k:row[k] for k in study_classification.LABELS})
                    results.db.executemany("INSERT INTO facets VALUES(?,?,?)",
                                           ((k,v,pid) for k,group in values.items() for v in group))
                    results.total += 1
                results.revision = digest.hexdigest()
            return results
        except BaseException:
            results.close()
            raise

    def close(self):
        self.db.close()

    def options(self):
        result = {}
        for key,value in self.db.execute("SELECT DISTINCT kind,value FROM facets ORDER BY kind,value"):
            result.setdefault(key,[]).append(value)
        return result

    def _query(self, spec, selected=False):
        spec = specification(**spec)
        clauses,params = [],[]
        if spec["text"]:
            clauses.append("instr(r.search_text,?)>0")
            params.append(spec["text"].casefold())
        for kind,values in spec["facets"].items():
            marks = ",".join("?" for _ in values)
            clauses.append(f"r.id IN (SELECT id FROM facets WHERE kind=? AND value IN ({marks}))")
            params.extend([kind,*values])
        if selected:
            clauses.append("r.id IN (SELECT id FROM chosen)")
        where = " FROM rows r" + (" WHERE "+" AND ".join(clauses) if clauses else "")
        order = " ORDER BY r."+SORTS[spec["sort"]]+(" DESC" if spec["descending"] else " ASC")+",r.id"
        return where,params,order

    def page(self,spec,*,offset=0,page_size=25):
        if type(offset) is not int or offset<0 or type(page_size) is not int or not 1<=page_size<=100:
            raise ValueError("Invalid results page")
        spec = specification(**spec)
        where,params,order = self._query(spec)
        count = self.db.execute("SELECT COUNT(*)"+where,params).fetchone()[0]
        items = []
        for raw,is_selected in self.db.execute("SELECT record,r.id IN (SELECT id FROM chosen)"+where+
                       order+" LIMIT ? OFFSET ?",[*params,page_size,offset]):
            record = json.loads(raw)
            items.append(dict(publication_id=record["publication_id"],selected=bool(is_selected),
                              **{c:record[c] for c in spec["columns"]}))
        return dict(revision=self.revision,captured_at=self.captured_at,total=self.total,matching=count,
                    selected=self.db.execute("SELECT COUNT(*) FROM chosen").fetchone()[0],offset=offset,
                    page_size=page_size,rows=items,spec=spec)

    def select(self,spec,*,all_matching=False,ids=(),remove=False):
        where,params,_ = self._query(spec)
        if not all_matching:
            if not isinstance(ids,(tuple,list)) or len(ids)>100:
                raise ValueError("Select a page or all matching publications")
            if not ids:
                return
            for pid in ids:
                identity._identifier(pid)
            where += (" AND " if " WHERE " in where else " WHERE ")+"r.id IN ("+",".join("?" for _ in ids)+")"
            params.extend(ids)
        query = "SELECT r.id"+where
        with self.db:
            if remove:
                self.db.execute("DELETE FROM chosen WHERE id IN ("+query+")",params)
            else:
                self.db.execute("INSERT OR IGNORE INTO chosen "+query,params)

    def records(self,spec,scope):
        if scope not in ("entire","filtered","selected"):
            raise ValueError("Select an export scope")
        where,params,order = self._query(DEFAULT if scope in ("entire","selected") else spec,scope=="selected")
        for raw, in self.db.execute("SELECT record"+where+order,params):
            yield json.loads(raw)

    def detail(self,project,pid):
        """Read full text locally only after rechecking its original retrieval and current identity."""
        found = self.db.execute("SELECT record FROM rows WHERE id=?",(identity._identifier(pid),)).fetchone()
        if not found or str(project.identifier)!=self.project_id:
            raise ValueError("Choose a publication in this result snapshot")
        row = json.loads(found[0])
        with _read(project) as db:
            snapshot = identity._snapshot(db,pid)
            sources = {s["retrieval_id"]:s for s in snapshot.retrievals if s["run_id"]==self.run}
            if {s["retrieval_id"]:s["sha256"] for s in row["source_evidence"]} != {
                    rid:s["source_sha256"] for rid,s in sources.items()}:
                raise ValueError("Publication evidence changed. Refresh the results.")
            for entry in row["source_evidence"]:
                raw = sources[entry["retrieval_id"]]["original_metadata"]
                record = raw.get("record")
                entry["abstract"] = _abstract(record) if isinstance(record,dict) else ""
                entry["rights"] = raw.get("rights_status") or "review redistribution permissions"
                if entry["source"] in ("conference_jats","conference_pdf","society"):
                    entry["specialist_record"] = record
                if raw.get("container_id"):
                    container = db.execute("SELECT metadata_json FROM containers WHERE container_id=?",
                                           (raw["container_id"],)).fetchone()
                    if container:
                        entry["container"] = identity._object(container[0])
        return row


def save_view(project, name, spec, expected_event=None):
    identity._text(name,100)
    spec = specification(**spec)
    with _validated_project_connection(project) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT event_id,details_json FROM audit_events WHERE event_type=? "
                         "AND json_extract(details_json,'$.name')=? ORDER BY event_id DESC LIMIT 1",(SAVED,name)).fetchone()
        if row and identity._object(row[1])["spec"] == spec:
            return row[0]
        if (row[0] if row else None) != expected_event:
            raise ValueError("The saved view has changed")
        return identity._audit(db,SAVED,dict(at_utc=_utc_now(),name=name,spec=spec))


def saved_views(project):
    with _read(project) as db:
        views = {}
        for event,raw in db.execute("SELECT event_id,details_json FROM audit_events WHERE event_type=? ORDER BY event_id",(SAVED,)):
            entry=identity._object(raw)
            views[entry["name"]] = dict(event=event,spec=specification(**entry["spec"]))
        return views
