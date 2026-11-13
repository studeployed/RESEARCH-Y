"""Researcher controls for official guidance, conference documents and targeted DOI enrichment."""
from datetime import date
from importlib.util import find_spec

from research_y.society_sources import GUIDANCE_TYPES


def _lines(value):
    return [line.strip() for line in (value or "").splitlines() if line.strip()]


def society_panel(ui,state,act,*,native):
    specialist = state.get("specialist", {})
    def send(operation, **data):
        return act("specialist", {"action":operation, "data":data})

    with ui.expansion("Professional society sources", value="directory" in specialist).props("data-testid=society-panel"):
        terms = ui.textarea("Topic terms (one per line)", value="\n".join(specialist.get("society_terms", []))).props("data-testid=society-terms")
        ui.button("Find society libraries and open directory", on_click=lambda:
                  send("directory",terms=_lines(terms.value))).props("data-testid=society-search")
        if "directory" not in specialist:
            return
        actor = ui.input("Researcher").props("data-testid=society-actor")
        directory = {r["society_id"]:r["name"] for r in specialist["directory"]}
        for candidate in specialist["suggestions"]:
            with ui.row():
                ui.label(candidate["name"])
                if native:
                    ui.button("Open official library in browser",on_click=lambda c=candidate:act("native_society_site",
                              dict(kind="suggestion",key=c["name"]))).props("data-testid=society-library")
                else:
                    ui.link("Official library",candidate["official_url"],new_tab=True)
                ui.button("Add to directory",on_click=lambda c=candidate:
                    send("society_save",name=c["name"],official_url=c["official_url"],actor=actor.value))
        name = ui.input("Society name").props("data-testid=society-name")
        url = ui.input("Official website").props("data-testid=society-url")
        ui.button("Confirm new society",on_click=lambda:
                  send("society_save",name=name.value,official_url=url.value,actor=actor.value)).props("data-testid=society-save")
        if not directory:
            return
        selection=ui.select(directory,label="Project society")
        ui.button("Open society visits",on_click=lambda:send("society_select",society_id=selection.value))
        current=specialist.get("society")
        if not current:
            return
        ui.label(current["name"]).props("data-testid=current-society")
        if native:
            ui.button("Open confirmed website in browser",on_click=lambda:act("native_society_site",
                      dict(kind="selected",key=current["society_id"])))
        else:
            ui.link("Visit confirmed official website",current["official_url"],new_tab=True)
        edit_name=ui.input("Directory name",value=current["name"])
        edit_url=ui.input("Directory URL",value=current["official_url"])
        ui.button("Save directory changes", on_click=lambda:send("society_save",society_id=current["society_id"],
                  name=edit_name.value,official_url=edit_url.value,actor=actor.value))
        page=ui.input("Official page examined")
        examined=ui.input("Date examined",value=date.today().isoformat())
        method=ui.select(["manual_browse","site_search"],value="manual_browse",label="How the page was examined")
        outcome=ui.select(["guidance_found","none_seen","unavailable","review_needed"],value="review_needed",label="Outcome")
        limitations=ui.input("Coverage and limitations")
        ui.button("Record visit",on_click=lambda:send("society_visit",url=page.value,examined_on=examined.value,
                  method=method.value,terms=_lines(terms.value),outcome=outcome.value,limitations=limitations.value,
                  actor=actor.value))
        found={}
        for visit in specialist.get("visits",[]):
            d=visit["details"]
            ui.label(f'{visit["at_utc"]} · {d["outcome"]} · {d["limitations"]}')
            if d["outcome"]=="guidance_found":
                found[visit["event_id"]]=f'{visit["at_utc"]} · '+", ".join(p["url"] for p in d["pages"])
        if not found:
            return
        selected=ui.select(found,label="Visit supporting this document")
        title=ui.input("Guidance title")
        kinds=ui.select(sorted(GUIDANCE_TYPES),multiple=True,label="Document types")
        landing=ui.input("Observed official landing URL")
        fields={key:ui.input(label) for key,label in (("edition","Edition"),("issue_date","Issue date"),
                ("document_url","Document link"),("journal_citation","Journal citation"),("doi","DOI"),
                ("update_statement","Update or supersession statement"),("supplement","Supplement"))}
        authors=ui.textarea("Authors (one per line)")
        roles={role:ui.select(directory,multiple=True,label=role.capitalize()+" societies")
               for role in ("issuing","collaborating","endorsing")}
        def admit():
            record={"title":title.value,"landing_url":landing.value,"document_types":kinds.value or []}
            record.update({k:v.value for k,v in fields.items() if v.value})
            if authors.value:
                record["authors"]=_lines(authors.value)
            return send("society_guidance",visit_id=selected.value,record=record,
                        roles={k:v.value for k,v in roles.items() if v.value},actor=actor.value)
        ui.button("Confirm guidance import",on_click=admit)
        if specialist.get("guidance_receipt"):
            ui.label("Saved publication "+specialist["guidance_receipt"]["publication_id"])


def publication_panel(ui,state,detail,act,native):
    specialist=state.get("specialist",{})
    def send(name, **data):
        return act("specialist",{"action":name,"data":data})
    with ui.expansion("Crossref metadata"):
        ui.button("Inspect DOI and cached evidence",on_click=lambda:send("enrichment_offer"))
        view=specialist.get("enrichment")
        if view and view["target"]["publication_id"] == detail["publication"]["publication_id"]:
            target=view["target"]
            ui.label("DOI lookup: "+target["status"])
            if view["current"]:
                ui.label("Recorded outcome: "+view["current"]["outcome"])
                ui.label("Available fields: "+", ".join(view["current"]["fields"]))
                ui.label("Missing fields: "+", ".join(view["current"]["gaps"]))
            if target["request_url"] and not specialist.get("lookup_result"):
                ui.label("Crossref will receive this DOI and your contact email: "+target["doi"])
                contact=ui.input("Contact email for Crossref")
                lookup_actor=ui.input("Researcher requesting lookup")
                refresh=ui.checkbox("Request fresh metadata even if a response is cached")
                ui.button("Confirm DOI lookup",on_click=lambda:send("enrichment_lookup",contact=contact.value,
                          actor=lookup_actor.value,revision=target["revision"],refresh=refresh.value))
            if specialist.get("lookup_result"):
                ui.label("Last lookup: "+specialist["lookup_result"])
    if not native:
        return
    with ui.expansion("Conference abstract review",value=bool(specialist.get("conference") or specialist.get("conference_tasks") or specialist.get("pdf_page"))):
        eligible={r["retrieval_id"]:r["source_name"]+" "+r["source_record_id"] for r in detail["source_retrievals"]
                  if r["run_id"]==state["selected_run_id"] and r["source_name"] in {"pubmed","wos"}}
        if not eligible:
            return
        source=ui.select(eligible,label="Original collection source",
                         value=next(iter(eligible)) if len(eligible) == 1 else None)
        if find_spec("pypdf") is not None:
            pdf_review_panel(ui,specialist,source,eligible,act,send)
        else:
            ui.label("Local PDF verification is available with the optional PDF reader.")
        ui.button("Open saved block reviews",on_click=lambda:send("conference_tasks",retrieval_id=source.value))
        task_page = specialist.get("conference_tasks")
        if task_page and task_page["retrieval_id"] in eligible:
            source_id = task_page["retrieval_id"]
            ui.label("Saved block reviews for "+eligible[source_id])
            if not task_page["tasks"]:
                ui.label("No saved block reviews on this page.")
            for task in task_page["tasks"]:
                with ui.expansion(task["locator"]+" · "+task["reason"]):
                    ui.label("Document SHA-256 "+task["document_sha256"])
                    if task["decision"]:
                        decision = task["decision"]
                        ui.label(decision["disposition"]+" · "+decision["actor"]+" · "+decision["note"])
                    elif task["original_current"]:
                        reviewer=ui.input("Researcher completing review")
                        outcome=ui.select(["not_an_individual_abstract","reviewed_in_source"],label="Outcome")
                        note=ui.input("Source observation")
                        ui.button("Record block review",on_click=lambda tid=task["task_id"], who=reviewer,
                                  result=outcome, notes=note:send("conference_finish_task",retrieval_id=source_id,
                                  task_id=tid,actor=who.value,disposition=result.value,note=notes.value))
                    else:
                        ui.label("The original source has changed since this task was saved.")
            if task_page["next_after"] is not None:
                ui.button("Next saved reviews",on_click=lambda:send("conference_tasks",retrieval_id=source_id,
                          after=task_page["next_after"]))
        words=ui.textarea("Match terms (one per line)")
        landing=ui.input("Supplement landing URL")
        pdf=ui.input("Supplement PDF URL")
        mapped=ui.textarea("Verified PDF file pages (XML ID and one-based page per line)")
        def choose():
            try:
                entries=[line.rsplit(None,1) for line in _lines(mapped.value)]
                pages={key:int(page) for key,page in entries}
                if len(pages)!=len(entries):
                    raise ValueError
            except ValueError:
                ui.notify("Enter one unique XML ID and page number on each line.")
                return
            return act("native_conference",dict(source_id=source.value,terms=_lines(words.value),
                       landing_url=landing.value or None,pdf_url=pdf.value or None,pdf_pages=pages))
        ui.button("Choose local JATS supplement",on_click=choose)
        preview=specialist.get("conference")
        if preview and preview["original_retrieval_id"] in eligible:
            ui.label(f'Extracted blocks: {preview["total"]}. Unresolved blocks: {preview["unresolved_total"]}.')
            actor=ui.input("Researcher reviewing extraction")
            for unresolved in preview["unresolved"]:
                ui.label(unresolved["locator"]+" · "+unresolved["reason"])
                ui.button("Save block for follow-up",on_click=lambda loc=unresolved["locator"]:
                          send("conference_queue_block",retrieval_id=preview["original_retrieval_id"],
                               revision=preview["revision"],locator=loc,actor=actor.value))
            entries={r["locator"]:(r["title"] or "Untitled")+" · "+r["locator"] for r in preview["abstracts"]}
            for r in preview["abstracts"]:
                ui.button("Inspect "+(r["title"] or r["locator"]),on_click=lambda loc=r["locator"]:
                          send("conference_detail",locator=loc,revision=preview["revision"]))
                ui.label(f'{r["locator"]} · printed page {r["printed_first_page"] or "unknown"} · PDF page {r["pdf_page"] or "unknown"}')
                if r["warnings"]:
                    ui.label(", ".join(r["warnings"]))
            if preview.get("detail"):
                item=preview["detail"]
                ui.label(item["text"] or "Abstract text unavailable")
                ui.label(", ".join(item["authors"]))
                ui.label("Matched terms: "+", ".join(item["matched_terms"]))
            if preview["offset"]:
                ui.button("Previous abstracts",on_click=lambda:send("conference_page",offset=preview["offset"]-20,revision=preview["revision"]))
            if preview["has_more"]:
                ui.button("Next abstracts",on_click=lambda:send("conference_page",offset=preview["offset"]+20,revision=preview["revision"]))
            chosen=ui.select(entries,multiple=True,label="Abstracts to retain")
            rights=ui.checkbox("I may retain the selected abstract text locally")
            ui.button("Confirm selected abstracts",on_click=lambda:send("conference_admit",revision=preview["revision"],
                      locators=chosen.value or [],actor=actor.value,retention_authorized=rights.value))
        if specialist.get("conference_receipt"):
            receipt=specialist["conference_receipt"]
            ui.label(f'Retained {receipt["selected_count"]} of {receipt["extracted_count"]} extracted abstracts.')


def pdf_review_panel(ui, specialist, source, eligible, act, send):
    page_view = specialist.get("pdf_page")
    with ui.expansion("Verify a text-based PDF page",value=bool(page_view)):
        field = ui.number("PDF file page (first page is 1)",value=1,min=1,max=4096,step=1)
        def choose_page():
            if field.value is None or not float(field.value).is_integer():
                ui.notify("Enter a whole page number.")
                return
            return act("native_pdf",dict(source_id=source.value,page=int(field.value)))
        ui.button("Choose local PDF",on_click=choose_page)
        if not page_view or page_view["retrieval_id"] not in eligible:
            return
        rid = page_view["retrieval_id"]
        ui.label(f'PDF page {page_view["page"]} of {page_view["total_pages"]} · {eligible[rid]}')
        if page_view["status"] == "no_extractable_text":
            ui.label("No extractable text on this page. Check the source visually.")
            return
        ui.textarea("Page text",value=page_view["text"]).props("readonly")
        title = ui.input("Exact abstract title")
        excerpt = ui.textarea("Paste the complete individual abstract passage, including its title")
        authors = ui.textarea("Authors appearing in this passage (one per line)")
        printed = ui.input("Printed page as observed")
        number = ui.input("Abstract or poster number as observed")
        url = ui.input("Full supplement PDF URL, if available")
        ui.button("Verify selected passage",on_click=lambda:send("pdf_select",retrieval_id=rid,
                  page_revision=page_view["revision"],
                  title=title.value,excerpt=excerpt.value,authors=_lines(authors.value),
                  printed_page=printed.value or None,number=number.value or None,pdf_url=url.value or None))
        block = specialist.get("pdf_block")
        if block and block["retrieval_id"] == rid:
            ui.label(block["title"]+" · "+block["locator"])
            ui.label(block["text"])
            ui.label("Printed page "+(block["printed_first_page"] or "unknown"))
            if block["pdf_page_url"]:
                ui.label(block["pdf_page_url"])
            reviewer = ui.input("Researcher confirming PDF passage")
            rights = ui.checkbox("I verified this individual abstract and may retain its text locally")
            ui.button("Retain verified PDF abstract",on_click=lambda:send("pdf_admit",retrieval_id=rid,
                      revision=block["revision"],actor=reviewer.value,retention_authorized=rights.value))
        receipt = specialist.get("pdf_receipt")
        if receipt and receipt["original_retrieval_id"] == rid:
            ui.label("Saved PDF abstract "+receipt["admitted"][0]["locator"])
