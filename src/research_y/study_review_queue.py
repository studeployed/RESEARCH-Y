"""Cursor-paged, source-backed publication review views with explicit filter denominators."""
from research_y import publication_identity as identity
from research_y import study_classification as classification
from research_y.projects import _validated_project_connection


def read_study_page(project, run_id, *, after=None, only_review=True, hide_non_english=False,
                    hide_non_human_only=False, page_size=20):
    identity._identifier(run_id)
    if after is not None:
        identity._identifier(after)
    if type(page_size) is not int or not 1 <= page_size <= 50 or any(
            type(v) is not bool for v in (only_review,hide_non_english,hide_non_human_only)):
        raise ValueError("Invalid study review page")
    with _validated_project_connection(project) as db:
        db.execute("BEGIN")
        if not db.execute("SELECT 1 FROM search_runs WHERE run_id=?", (run_id,)).fetchone():
            raise KeyError("Unknown run")
        ids = [row[0] for row in db.execute(
            "SELECT DISTINCT p.publication_id FROM publication_retrievals p JOIN source_retrievals r "
            "ON r.retrieval_id=p.retrieval_id WHERE r.run_id=? AND (? IS NULL OR p.publication_id>?) "
            "ORDER BY p.publication_id LIMIT ?",(run_id,after,after,page_size+1))]
        selected = ids[:page_size]
        results=[]
        for pid in selected:
            view=classification._view(db,pid)
            if not classification.visible_in_filtered_view(view,hide_non_english=hide_non_english,
                                                          hide_non_human_only=hide_non_human_only):
                continue
            unresolved=[k for k,v in view["review_status"].items() if v=="requires-review"]
            conflicts=[v for v in view["warnings"] if v.startswith(("conflicting_","reviewed_"))]
            if only_review and not (unresolved or conflicts):
                continue
            results.append(dict(publication_id=pid,revision=view["revision"],dimensions=view["current"],
                                unresolved=unresolved,warnings=view["warnings"]))
        return dict(run_id=run_id,rows=results,after=after,examined=len(selected),hidden_by_filter=len(selected)-len(results),
                    displayed=len(results),only_review=only_review,hide_non_english=hide_non_english,
                    hide_non_human_only=hide_non_human_only,next_after=selected[-1] if len(ids)>page_size else None)
