"""Desktop session for specialist sources. Project and run come from the trusted project selection."""
from uuid import uuid4

from research_y import conference_review
from research_y.conference_jats import MAX_BYTES
from research_y.conference_project import preview_extraction, admit_extraction
from research_y.crossref_client import enrich_publication
from research_y.crossref_metadata import inspect_enrichment
from research_y.export_files import Directory
from research_y.publication_identity import _hash
from research_y.society_guidance_review import suggest_societies
from research_y.society_sources import (list_societies, list_society_visits, save_society,
                                        record_society_visit, import_guidance)


class SpecialistWorkbench:
    def __init__(self):
        self.context = None
        self.state = {}
        self.conference = None
        self.lookup = None
        self.visit_request = None
        self.guidance_request = None

    def select(self, project, run):
        key = (project.identifier, run)
        if key != self.context:
            self.__init__()
            self.context = key

    def directory(self, project, terms):
        self.state["directory"] = list_societies(project)
        self.state["suggestions"] = suggest_societies(terms)
        self.state["society_terms"] = list(terms)

    def save_directory_entry(self, project, *, name, official_url, actor, society_id=None):
        known = {r["society_id"]:r for r in self.state.get("directory",[])}
        if society_id is not None and society_id not in known:
            raise ValueError("Select a current directory entry")
        org = save_society(project, society_id=society_id or str(uuid4()), name=name, official_url=official_url,
                           actor=actor, expected_revision=known[society_id]["revision"] if society_id else None,
                           confirmed=True)
        self.state["directory"] = list_societies(project)
        self.choose_society(project,org["society_id"])

    def choose_society(self, project, society_id):
        rows = {row["society_id"]:row for row in self.state["directory"]}
        self.state["society"] = rows[society_id]
        self.state["visits"] = list_society_visits(project,society_id)
        self.visit_request, self.guidance_request = str(uuid4()), str(uuid4())
        self.visit_key = self.guidance_key = None
        self.state.pop("guidance_receipt", None)

    def visit(self, project, *, url, examined_on, method, terms, outcome, limitations, actor):
        org = self.state["society"]
        key = (url,examined_on,method,tuple(terms),outcome,limitations,actor)
        if key != self.visit_key:
            self.visit_request, self.visit_key = str(uuid4()), key
        record_society_visit(project, request_id=self.visit_request, society_id=org["society_id"],
            revision=org["revision"], actor=actor, method=method, terms=terms,
            pages=[dict(url=url,examined_on=examined_on)] if url else [], outcome=outcome,
            limitations=limitations, confirmed=True)
        self.state["visits"] = list_society_visits(project,org["society_id"])

    def guidance(self, project, run, *, visit_id, record, roles, actor):
        found = [v for v in self.state.get("visits",[]) if v["event_id"]==visit_id and v["details"]["outcome"]=="guidance_found"]
        if len(found)!=1:
            raise ValueError("Select a recorded guidance discovery")
        key = _hash([run,visit_id,record,roles,actor])
        if key != self.guidance_key:
            self.guidance_request, self.guidance_key = str(uuid4()),key
        receipt = import_guidance(project,request_id=self.guidance_request,run_id=run,visit_event_id=visit_id,
                                  record=record,roles=roles,actor=actor,confirmed=True)
        self.state["guidance_receipt"] = receipt

    def conference_preview(self, project, run, source_id, path, options):
        self.conference = None
        self.state.pop("conference",None)
        with Directory(path.parent) as directory:
            payload = directory.read_selected(path.name, limit=MAX_BYTES)
        result = preview_extraction(project,source_id,payload,**options)
        if result["run_id"] != run:
            raise ValueError("Source is outside the selected run")
        self.conference = (source_id,payload,options,result)
        self.conference_page(0,result["revision"])
        self.state.pop("conference_receipt",None)

    def conference_page(self, offset, revision):
        if not self.conference or self.conference[3]["revision"] != revision:
            raise ValueError("Conference preview changed")
        result=self.conference[3]
        extraction=result["extraction"]
        total=max(len(extraction["abstracts"]), len(extraction["unresolved"]))
        if type(offset) is not int or offset < 0 or offset % 20 or (offset and offset >= total):
            raise ValueError("Invalid conference preview page")
        visible = [{k:r[k] for k in ("locator","title","printed_first_page","pdf_page","matched_terms","warnings")}
                   for r in extraction["abstracts"][offset:offset+20]]
        self.state["conference"] = dict(original_retrieval_id=result["original_retrieval_id"],revision=revision,
              offset=offset,total=len(extraction["abstracts"]),unresolved_total=len(extraction["unresolved"]),
              has_more=offset+20<total, abstracts=visible, unresolved=extraction["unresolved"][offset:offset+20])

    def conference_detail(self, locator, revision):
        page=self.state.get("conference")
        if not page or page["revision"] != revision or locator not in {r["locator"] for r in page["abstracts"]}:
            raise ValueError("Select an abstract from the current page")
        rows=self.conference[3]["extraction"]["abstracts"]
        page["detail"] = next(r for r in rows[page["offset"]:page["offset"]+20] if r["locator"] == locator)

    def conference_admit(self, project, *, revision, locators, actor, retention_authorized):
        if not self.conference or revision != self.conference[3]["revision"]:
            raise ValueError("Reopen the original preview")
        if not isinstance(locators,list) or not set(locators) <= {r["locator"] for r in self.state["conference"]["abstracts"]}:
            raise ValueError("Select abstracts on the current preview page")
        source, data, options, _ = self.conference
        receipt = admit_extraction(project,source,data,locators=locators,expected_revision=revision,actor=actor,
                                   confirmed=True,retention_authorized=retention_authorized,**options)
        self.state["conference_receipt"] = receipt
        self.state.pop("conference",None)
        self.conference = None

    def queue_block(self, project, retrieval_id, revision, locator, actor):
        page = self.state.get("conference")
        if (not page or page["original_retrieval_id"] != retrieval_id or page["revision"] != revision
                or locator not in {r["locator"] for r in page["unresolved"]}):
            raise ValueError("Select a visible unresolved block")
        conference_review.queue_block(project,retrieval_id,self.conference[3]["extraction"],locator,actor)
        self.review_tasks(project,retrieval_id)

    def review_tasks(self, project, retrieval_id, after=0):
        self.state["conference_tasks"] = conference_review.read_tasks(project,retrieval_id,after=after)

    def finish_task(self, project, retrieval_id, **decision):
        page = self.state.get("conference_tasks")
        if (not page or page["retrieval_id"] != retrieval_id or
                decision.get("task_id") not in {r["task_id"] for r in page["tasks"]}):
            raise ValueError("Select a visible source task")
        conference_review.finish_task(project,retrieval_id,**decision)
        self.review_tasks(project,retrieval_id,page["after"])

    def offer_lookup(self, project, publication_id):
        view = inspect_enrichment(project,publication_id)
        self.lookup = (publication_id,view["target"]["revision"])
        self.state["enrichment"] = view
        self.state.pop("lookup_result",None)

    def lookup_work(self, project, publication_id, *, contact, actor, revision, refresh):
        if self.lookup != (publication_id,revision):
            raise ValueError("Reopen the DOI preview for the current publication")
        self.lookup = None
        result = enrich_publication(project,publication_id,contact=contact,actor=actor,
                                    expected_revision=revision,refresh=refresh,confirmed=True)
        self.state["lookup_result"] = result["status"]
        self.state["enrichment"] = inspect_enrichment(project,publication_id)
