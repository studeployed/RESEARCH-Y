"""Keyboard-operable run results, evidence inspection and persistent view controls."""
import json

from research_y.master_results import COLUMNS


def _label(value):
    if isinstance(value,dict):
        return ", ".join(value.values())
    if isinstance(value,list):
        return ", ".join(value)
    return value if value is not None else "Unknown"


def render_master(ui,state,act,*,native):
    view = state.get("master_results")
    with ui.expansion("Master results",value=view is not None).props("data-testid=master-panel"):
        def send(operation,**data):
            if view:
                data["revision"] = view["revision"]
            return act("master_results",dict(operation=operation,data=data))
        ui.button("Refresh results from project",on_click=lambda:send("capture")).props("data-testid=master-refresh")
        if not view:
            return
        spec = view["spec"]
        ui.label(f'{view["matching"]} of {view["total"]} publication identities match · {view["selected"]} selected')
        ui.label("Snapshot captured "+view["captured_at"])
        if native:
            with ui.expansion("Export master results",value="export" in view):
                file = ui.input("Output filename (.xlsx or .ris)",value="Master Results.xlsx")
                scope = ui.select({"entire":"Entire captured dataset","filtered":"All filtered matches",
                                   "selected":"All selected publications"},value="entire",label="Records to export")
                rights = ui.checkbox("Include abstract text that I am permitted to export")
                allowed = ui.select(view["options"].get("source",[]),multiple=True,value=[],
                                    label="Sources whose abstract text I may export")
                ui.button("Choose folder and write results",on_click=lambda:act("native_master_export",dict(
                          name=file.value,revision=view["revision"],scope=scope.value,include_abstracts=rights.value,
                          abstract_sources=allowed.value or [])))
                if "export" in view:
                    done = view["export"]
                    ui.label(f'Saved {done["rows"]} publication rows to {done["filename"]}')
                    if done.get("scope_filename"):
                        ui.label("Run status and export scope · "+done["scope_filename"])
        with ui.expansion("Search, filters and columns"):
            query = ui.input("Search titles, abstracts, citations or identifiers",value=spec["text"])
            languages = ui.checkbox("Hide explicitly non-English records",value=spec.get("hide_non_english",False))
            population = ui.checkbox("Hide reviewed non-human-only records",value=spec.get("hide_non_human_only",False))
            filters = {key:ui.select(values,value=spec["facets"].get(key,[]),label=key.replace("_"," ").title(),
                                     multiple=True) for key,values in view["options"].items()}
            sort = ui.select(["title","year","publication_id"],value=spec["sort"],label="Sort by")
            reverse = ui.checkbox("Descending",value=spec["descending"])
            columns = ui.select(list(COLUMNS),value=spec["columns"],label="Visible columns",multiple=True)
            ui.button("Apply filters and columns",on_click=lambda:send("apply",spec=dict(text=query.value or "",
                      facets={k:v.value for k,v in filters.items() if v.value},sort=sort.value,
                      descending=reverse.value,columns=columns.value,hide_non_english=languages.value,
                      hide_non_human_only=population.value)))
            view_name = ui.input("Save applied view as")
            ui.button("Save current view",on_click=lambda:send("save",name=view_name.value))
            if view["saved"]:
                saved = ui.select(list(view["saved"]),label="Saved view")
                ui.button("Load saved view",on_click=lambda:send("load",name=saved.value))
        keys = spec["columns"]
        table_rows = [{k:_label(r[k]) for k in keys} | {"publication_id":r["publication_id"]} for r in view["rows"]]
        table = ui.table(columns=[dict(name=k,label=k.replace("_"," ").title(),field=k,align="left") for k in keys],
                         rows=table_rows,row_key="publication_id",selection="multiple",
                         pagination={"rowsPerPage":0}).props('hide-bottom data-testid=master-table aria-label="Master publication results"')
        table.selected = [r for r,raw in zip(table_rows,view["rows"]) if raw["selected"]]
        def selection(remove=False):
            return send("select",ids=[r["publication_id"] for r in table.selected],remove=remove)
        with ui.row():
            ui.button("Add checked rows to selection",on_click=lambda:selection())
            ui.button("Remove checked rows",on_click=lambda:selection(True))
            ui.button("Select all matching",on_click=lambda:send("select",all_matching=True))
            ui.button("Clear matching selection",on_click=lambda:send("select",all_matching=True,remove=True))
        if view["rows"]:
            start = view["offset"]+1
            ui.label(f'Showing {start}–{start+len(view["rows"])-1} of {view["matching"]}')
            rows = {r["publication_id"]:str(r.get("title") or r["publication_id"]) for r in view["rows"]}
            record = ui.select(rows,label="Record to inspect")
            ui.button("Open source evidence",on_click=lambda:send("detail",id=record.value))
        with ui.row():
            if view["offset"]:
                ui.button("Previous results",on_click=lambda:send("page",direction=-1))
            if view["offset"]+len(view["rows"])<view["matching"]:
                ui.button("Next results",on_click=lambda:send("page",direction=1))
        detail = view.get("detail")
        if detail:
            with ui.expansion(detail["title"] or detail["publication_id"],value=True):
                selected = dict(id=detail["publication_id"],publication_revision=detail["publication_revision"])
                lookup = detail["enrichment"]
                with ui.expansion("Crossref abstract and metadata"):
                    receipt = lookup["current"]
                    ui.label("Lookup status · "+lookup["lookup_status"].replace("_"," "))
                    if receipt:
                        ui.label(f"Crossref · {receipt['outcome']} · {receipt['retrieved_at_utc']}")
                        ui.label(receipt["fields"].get("abstract") or "Crossref supplied no abstract for this response.")
                    elif lookup["prior_receipts"]:
                        ui.label("Earlier Crossref evidence belongs to a previous publication revision.")
                    else:
                        ui.label("No Crossref metadata receipt for this publication.")
                    if detail.get("last_lookup"):
                        ui.label("Last lookup · "+detail["last_lookup"])
                    target = lookup["target"]
                    if target["doi"]:
                        ui.label("DOI to send to Crossref · "+target["doi"])
                        contact = ui.input("Contact email sent to Crossref with this DOI")
                        lookup_actor = ui.input("Researcher requesting metadata")
                        refresh = ui.checkbox("Refresh previously retrieved Crossref metadata")
                        ui.button("Confirm DOI lookup",on_click=lambda:send("lookup",**selected,
                            contact=contact.value,actor=lookup_actor.value,refresh=refresh.value,confirmed=True))
                    else:
                        ui.label(target["status"].replace("_"," "))
                with ui.expansion("Choose citation values from source records"):
                    if detail["conflicting_fields"]:
                        ui.label("Sources disagree on "+", ".join(detail["conflicting_fields"]))
                    choices = {f"{n}/{field}":f"{field} · {evidence['value']} · {item['source']} {item['source_record_id']}"
                               for n,item in enumerate(detail["source_evidence"])
                               for field,evidence in item["field_evidence"].items()
                               if field in ("title","doi","year","journal") and evidence["status"]=="present"}
                    for field,choice in detail["chosen_fields"].items():
                        ui.label(f"Chosen {field} · {choice['value']}")
                    if choices:
                        chosen = ui.select(choices,label="Source value")
                        editor = ui.input("Researcher selecting the value")
                        reason = ui.input("Reason for this selection")
                        def choose_value():
                            if chosen.value in choices:
                                index,field = chosen.value.split("/",1)
                                return send("choose_field",**selected,field=field,
                                    retrieval_id=detail["source_evidence"][int(index)]["retrieval_id"],
                                    actor=editor.value,reason=reason.value)
                        ui.button("Confirm source value and close snapshot",on_click=choose_value)
                with ui.expansion("Project documents"):
                    for historical in detail.get("prior_identity_evidence",[]):
                        ui.label(f'Earlier publication {historical["origin"]} · identity review {historical["event_id"]} · '
                                 f'{historical["actor"]} · {historical["reason"]}')
                        for review in historical["classifications"]:
                            ui.label(f'Historical {review["dimension"]} · {review["label"]} · {review["status"]}')
                        for doc in historical["documents"]:
                            ui.label("Document on original identity · "+str(doc["relative_path"] or doc["source_url"]))
                        for field in historical["prior_fields"]:
                            ui.label("Earlier source choice retained in history · "+field)
                        for role in historical["retained_roles"]:
                            ui.label("Historical organisation and role · "+" · ".join(role))
                        for container in historical["retained_containers"]:
                            ui.label("Historical container · "+container)
                    for attachment in detail.get("attachments",[]):
                        ui.label(attachment.get("original_filename") or attachment.get("relative_path") or "Linked document")
                        ui.label(attachment.get("relative_path") or attachment.get("source_url"))
                    if native:
                        who=ui.input("Researcher attaching PDF")
                        origin=ui.input("Document source URL (optional)")
                        permission=ui.checkbox("I may retain this PDF in the project")
                        ui.button("Choose and attach local PDF",on_click=lambda:act("native_attach_pdf",
                                  dict(publication_id=detail["publication_id"],actor=who.value,
                                       source_url=origin.value or None,permission_confirmed=permission.value)))
                for item in detail["source_evidence"]:
                    ui.label(item["source"]+" · "+item["source_record_id"])
                    ui.label(item["abstract"] or "Abstract · "+item["abstract_status"])
                    for link_label,url in item["links"].items():
                        if native:
                            ui.button("Open "+link_label,on_click=lambda n=link_label,r=item["retrieval_id"]:act("native_master_link",
                                dict(**selected,revision=view["revision"],retrieval_id=r,link=n)))
                        else:
                            ui.link(link_label,url,new_tab=True)
                    ui.label("Reuse status · "+item["rights"])
                    ui.label("Groups · "+(", ".join(item["groups"].values()) or "No query membership"))
                    with ui.expansion("Original citation and provenance"):
                        ui.label(json.dumps({k:v for k,v in item.items() if k!="abstract"},
                                            ensure_ascii=False,indent=2)).style("white-space: pre-wrap")
