"""Researcher controls for official guidance, conference documents and targeted DOI enrichment."""
from datetime import date

from research_y.society_sources import GUIDANCE_TYPES


def _lines(value):
    return [line.strip() for line in (value or "").splitlines() if line.strip()]


def society_panel(ui,state,act):
    specialist = state.get("specialist", {})
    def send(operation, **data):
        return act("specialist", {"action":operation, "data":data})

    with ui.expansion("Professional society sources"):
        terms = ui.textarea("Topic terms (one per line)")
        ui.button("Find society libraries and open directory", on_click=lambda:
                  send("directory",terms=_lines(terms.value)))
        if "directory" not in specialist:
            return
        actor = ui.input("Researcher")
        directory = {r["society_id"]:r["name"] for r in specialist["directory"]}
        for candidate in specialist["suggestions"]:
            with ui.row():
                ui.label(candidate["name"])
                ui.link("Official library", candidate["official_url"], new_tab=True)
                ui.button("Add to directory",on_click=lambda c=candidate:
                    send("society_save",name=c["name"],official_url=c["official_url"],actor=actor.value))
        name, url = ui.input("Society name"), ui.input("Official website")
        ui.button("Confirm new society",on_click=lambda:
                  send("society_save",name=name.value,official_url=url.value,actor=actor.value))
        if not directory:
            return
        selection=ui.select(directory,label="Project society")
        ui.button("Open society visits",on_click=lambda:send("society_select",society_id=selection.value))
        current=specialist.get("society")
        if not current:
            return
        ui.label(current["name"])
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
                actor=ui.input("Researcher requesting lookup")
                refresh=ui.checkbox("Request fresh metadata even if a response is cached")
                ui.button("Confirm DOI lookup",on_click=lambda:send("enrichment_lookup",contact=contact.value,
                          actor=actor.value,revision=target["revision"],refresh=refresh.value))
            if specialist.get("lookup_result"):
                ui.label("Last lookup: "+specialist["lookup_result"])
    if not native:
        return
    with ui.expansion("Conference abstract review"):
        eligible={r["retrieval_id"]:r["source_name"]+" "+r["source_record_id"] for r in detail["source_retrievals"]
                  if r["run_id"]==state["selected_run_id"] and r["source_name"] in {"pubmed","wos"}}
        if not eligible:
            return
        source=ui.select(eligible,label="Original collection source")
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
            for unresolved in preview["unresolved"]:
                ui.label(unresolved["locator"]+" · "+unresolved["reason"])
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
            actor=ui.input("Researcher confirming extraction")
            rights=ui.checkbox("I may retain the selected abstract text locally")
            ui.button("Confirm selected abstracts",on_click=lambda:send("conference_admit",revision=preview["revision"],
                      locators=chosen.value or [],actor=actor.value,retention_authorized=rights.value))
        if specialist.get("conference_receipt"):
            receipt=specialist["conference_receipt"]
            ui.label(f'Retained {receipt["selected_count"]} of {receipt["extracted_count"]} extracted abstracts.')
