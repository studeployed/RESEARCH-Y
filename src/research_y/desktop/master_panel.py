"""Keyboard-operable run results, evidence inspection and persistent view controls."""
import json
from research_y.desktop.feedback import readable_time
from research_y.desktop.candidate_panel import display_value

from research_y.master_results import COLUMNS


def _label(value):
    if isinstance(value,dict):
        return ", ".join(value.values())
    if isinstance(value,list):
        return ", ".join(value)
    return value if value is not None else "Unknown"


def render_master(ui,state,act,*,native):
    view = state.get("master_results")
    with ui.column().props("data-testid=master-panel"):
        def send(operation,**data):
            if view:
                data["revision"] = view["revision"]
            return act("master_results",dict(operation=operation,data=data))
        if not view:
            ui.button("Refresh results from project",on_click=lambda:send("capture")).props("data-testid=master-refresh")
            return
        spec = view["spec"]
        with ui.row().classes('results-toolbar'):
            ui.label(f'{view["matching"]} of {view["total"]} articles · {view["selected"]} selected').classes('section-title')
            ui.button("Refresh results from project",on_click=lambda:send("capture")).props("flat data-testid=master-refresh")
        ui.label('Tick articles to select them. Open an article for its details.').classes('review-hint')
        ui.label('Snapshot · ' + readable_time(view['captured_at']) + '. Refresh after collecting more records.').classes('review-hint')
        search_row = ui.row().classes('results-toolbar')
        with search_row:
            query = ui.input('Search articles', value=spec['text']).props('dense clearable data-testid=master-query')
        def search_text():
            return send('apply', spec={**spec, 'text': query.value or ''})
        query.on('keydown.enter', search_text)
        with search_row:
            ui.button('Search results', on_click=search_text).props('outline')
        with ui.expansion("Filters, columns and saved views"):
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
        table = ui.table(columns=[dict(name=k,label=k.replace("_"," ").title(),field=k,align="left") for k in keys] +
                         [dict(name='open', label='', field='publication_id', align='left')],
                         rows=table_rows,row_key="publication_id",selection="multiple",
                         pagination={"rowsPerPage":0}).classes('w-full results-table').props('hide-bottom wrap-cells data-testid=master-table aria-label="Master publication results"')
        table.selected = [r for r,raw in zip(table_rows,view["rows"]) if raw["selected"]]
        table.on_select(lambda e: send('select_page', ids=[r['publication_id'] for r in e.selection],
                                      visible=[r['publication_id'] for r in view['rows']]))
        table.add_slot('body-cell-open', '''<q-td :props="props"><q-btn flat dense no-caps label="Open"
                       @click="$parent.$emit('open-record', props.row.publication_id)" /></q-td>''')
        table.on('open-record', lambda e: send('detail', id=e.args))
        with ui.row():
            ui.button("Select all matching",on_click=lambda:send("select",all_matching=True))
            ui.button("Deselect all matching",on_click=lambda:send("select",all_matching=True,remove=True)).props('flat')
        if view["rows"]:
            start = view["offset"]+1
            ui.label(f'Showing {start}–{start+len(view["rows"])-1} of {view["matching"]}')
        with ui.row():
            if view["offset"]:
                ui.button("Previous results",on_click=lambda:send("page",direction=-1))
            if view["offset"]+len(view["rows"])<view["matching"]:
                ui.button("Next results",on_click=lambda:send("page",direction=1))
        detail = view.get("detail")
        if detail:
            with ui.expansion(detail["title"] or detail["publication_id"],value=True):
                for field in ("authors", "year", "journal", "doi"):
                    value = detail.get(field)
                    if value:
                        ui.label(field.capitalize()+" · "+display_value(value))
                selected = dict(id=detail["publication_id"],publication_revision=detail["publication_revision"])
                for item in detail["source_evidence"]:
                    ui.label({"pubmed":"PubMed", "wos":"Web of Science"}.get(item["source"],item["source"])+" · "+item["source_record_id"])
                    ui.label(item["abstract"] or "Abstract unavailable · "+item["abstract_status"].replace("_"," ")).classes("article-abstract")
                    for link_label,url in item["links"].items():
                        if native:
                            ui.button("Open "+link_label,on_click=lambda n=link_label,r=item["retrieval_id"]:act("native_master_link",
                                dict(**selected,revision=view["revision"],retrieval_id=r,link=n)))
                        else:
                            ui.link(link_label,url,new_tab=True)
                    ui.label("Reuse permission · "+item["rights"].replace("_"," ")).classes("review-hint")
                    ui.label("Groups · "+(", ".join(item["groups"].values()) or "No query membership"))
                    with ui.expansion("Original citation and provenance"):
                        ui.label(json.dumps({k:v for k,v in item.items() if k!="abstract"},
                                            ensure_ascii=False,indent=2)).style("white-space: pre-wrap")

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
                        lookup_actor = ui.input("Researcher requesting metadata", value=state.get('researcher_name', ''))
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
                        editor = ui.input("Researcher selecting the value", value=state.get('researcher_name', ''))
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
                        who=ui.input("Researcher attaching PDF", value=state.get('researcher_name', ''))
                        origin=ui.input("Document source URL (optional)")
                        permission=ui.checkbox("I may retain this PDF in the project")
                        ui.button("Choose and attach local PDF",on_click=lambda:act("native_attach_pdf",
                                  dict(publication_id=detail["publication_id"],actor=who.value,
                                       source_url=origin.value or None,permission_confirmed=permission.value)))
