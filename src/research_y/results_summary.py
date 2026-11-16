"""Project recorded denominators for the normal run summary and publication workbook."""
from research_y.society_sources import VISIT_EVENT


def society_coverage(db, run_id):
    linked = dict(db.execute(
        "SELECT a.event_id,json_extract(a.details_json,'$.details.society_id') "
        "FROM audit_events a JOIN source_retrievals r ON a.event_id=json_extract(r.original_metadata_json,'$.visit_event_id') "
        "WHERE a.event_type=? AND r.run_id=? AND r.source_name='society' GROUP BY a.event_id",
        (VISIT_EVENT,run_id)))
    project_visits = db.execute("SELECT COUNT(*) FROM audit_events WHERE event_type=?", (VISIT_EVENT,)).fetchone()[0]
    return dict(project_recorded_visits=project_visits,visits_linked_to_this_run=len(linked),
                societies_linked_to_this_run=len(set(linked.values())),total_site_hits=None)


def results_summary(counts, receipt, coverage):
    groups = []
    queries = {q["query_id"]:q for q in counts["queries"]}
    for group in counts["groups"]:
        for source in group["sources"]:
            if source["source_name"] in ("pubmed","wos"):
                groups.append(dict(group=group["label"],group_id=group["group_id"],source=source["source_name"],
                    reported_matches=source["reported_matches"],retrieved_identifiers=source["retrieved_source_records"],
                    reconciliation=source["numeric_reconciliation"],reported_status=source["reported_count_status"],
                    metadata_missing=source["identifiers_without_metadata"],
                    stored_query_statuses=sorted({queries[q]["stored_query_status"] for q in source["query_ids"]}),
                    accepted_group_publications=group["publication_identities"] if receipt else None))
    sources = {s["source_name"]:s["source_unique_records"] for s in counts["sources"]}
    supplements = {name:sources.get(name,0) for name in ("society","manual_bibliographic","conference_jats","conference_pdf")}
    return dict(groups=groups,source_unique_records=sources,supplementary_retained_records=supplements,
                society_coverage=coverage,
                group_publication_sum=counts["totals"]["group_publication_identity_sum"] if receipt else None,
                extracted_individual_abstracts=supplements["conference_jats"]+supplements["conference_pdf"],
                global_unique_publications=receipt["global_unique_publications"] if receipt else None,
                status="Verified Complete" if receipt else "Incomplete",
                limitations=receipt["limitations"] if receipt else None)
