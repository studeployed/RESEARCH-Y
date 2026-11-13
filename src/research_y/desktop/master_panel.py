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
                ui.button("Choose folder and write results",on_click=lambda:act("native_master_export",dict(
                          name=file.value,revision=view["revision"],scope=scope.value,include_abstracts=rights.value)))
                if "export" in view:
                    done = view["export"]
                    ui.label(f'Saved {done["rows"]} publication rows to {done["filename"]}')
        with ui.expansion("Search, filters and columns"):
            query = ui.input("Search titles, abstracts, citations or identifiers",value=spec["text"])
            filters = {key:ui.select(values,value=spec["facets"].get(key,[]),label=key.replace("_"," ").title(),
                                     multiple=True) for key,values in view["options"].items()}
            sort = ui.select(["title","year","publication_id"],value=spec["sort"],label="Sort by")
            reverse = ui.checkbox("Descending",value=spec["descending"])
            columns = ui.select(list(COLUMNS),value=spec["columns"],label="Visible columns",multiple=True)
            ui.button("Apply filters and columns",on_click=lambda:send("apply",spec=dict(text=query.value or "",
                      facets={k:v.value for k,v in filters.items() if v.value},sort=sort.value,
                      descending=reverse.value,columns=columns.value)))
            name = ui.input("Save applied view as")
            ui.button("Save current view",on_click=lambda:send("save",name=name.value))
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
                for item in detail["source_evidence"]:
                    ui.label(item["source"]+" · "+item["source_record_id"])
                    ui.label(item["abstract"] or "Abstract unavailable from this source")
                    ui.label("Reuse status · "+item["rights"])
                    ui.label("Groups · "+(", ".join(item["groups"].values()) or "No query membership"))
                    with ui.expansion("Original citation and provenance"):
                        ui.label(json.dumps({k:v for k,v in item.items() if k!="abstract"},
                                            ensure_ascii=False,indent=2)).style("white-space: pre-wrap")
