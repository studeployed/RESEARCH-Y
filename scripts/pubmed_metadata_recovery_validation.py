"""Opt-in, bounded PubMed OR translation and small complete metadata recovery sample."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

from research_y.projects import create_project, open_project, _validated_project_connection
from research_y.pubmed_checkpoint_resume import start_checkpointed_pubmed_retrieval, resume_pubmed_checkpoint
from research_y.pubmed_metadata import PubMedEFetchClient, MAX_BATCH_IDS
from research_y.pubmed_metadata_store import collect_pubmed_metadata, _known_query_records
from research_y.pubmed_partition import DateWindow
from research_y.pubmed_probe import PubMedESearchProbeClient
from research_y.strategy_admission import commit_approved_strategy
from research_y.storage import ApprovedTerm, StrategyGroup

PROJECT = "pubmed-sample"
STATE = "metadata-state.json"
EVIDENCE = "metadata-evidence.json"
GROUPS = {"clinical": ("ECMO", "extracorporeal membrane oxygenation"),
          "reporting": ("10.1186/s13643-020-01542-z", "10.1136/bmj.n71")}


class SampleClient(PubMedESearchProbeClient):
    """Keep network budgets and record limits independent of changing provider counts."""

    def __init__(self, stage, **kwargs):
        super().__init__(**kwargs)
        self.requests = 0
        self.stage = stage
        self.queries = {group: "(" + " OR ".join(f'"{term}"[All Fields]' for term in terms) + ")"
                        for group, terms in GROUPS.items()}

    def fetch_esearch_page(self, exact_query, *, retstart=0, retmax=0):
        allowed = ((self.stage == "start" and exact_query == self.queries["clinical"] and retmax == 0) or
                   (exact_query == self.queries["reporting"] and
                    (retmax == 0 or self.stage == "start" and 1 <= retmax <= MAX_BATCH_IDS)))
        if not allowed or retstart != 0 or self.requests >= (6 if self.stage == "start" else 2):
            raise ValueError("request_outside_sample")
        self.requests += 1
        return super().fetch_esearch_page(exact_query, retstart=retstart, retmax=retmax)

    def probe(self, exact_query, **kwargs):
        result = super().probe(exact_query, **kwargs)
        if exact_query == self.queries["reporting"] and not 2 <= result.reported_matches <= MAX_BATCH_IDS:
            raise ValueError("metadata_query_outside_sample_size")
        return result


class SampleEFetch(PubMedEFetchClient):
    def __init__(self, client, **kwargs):
        super().__init__(client, **kwargs)
        self.expected = ()
        self.called = False

    def fetch(self, pmids):
        if self.called or not self.expected or tuple(pmids) != self.expected:
            raise ValueError("metadata_request_outside_sample")
        self.called = True
        return super().fetch(pmids)


def _records(project, run_id, query_id):
    with _validated_project_connection(project) as db:
        return _known_query_records(db, query_id, run_id)


def start(workspace, client, efetch):
    workspace.mkdir(mode=0o700, parents=True, exist_ok=False)
    project = create_project(workspace, "PubMed OR and metadata recovery", directory_name=PROJECT)
    accepted = commit_approved_strategy(
        project, request_id=str(uuid4()), theme="Fixed public source diagnostic", approved_by="Manual diagnostic",
        approval_confirmed=True, groups=tuple(StrategyGroup(
            group, group, tuple(ApprovedTerm(term, "researcher", True) for term in terms))
            for group, terms in GROUPS.items()))
    with _validated_project_connection(project) as db:
        queries = {group: (query_id, exact) for group, query_id, exact in db.execute(
            "SELECT group_id,query_id,exact_query FROM source_queries WHERE run_id=? AND source_name='pubmed'",
            (accepted.run_id,))}
    if {key: entry[1] for key, entry in queries.items()} != client.queries:
        raise ValueError("compiler_output_changed")
    phrase = client.probe(queries["clinical"][1])
    if phrase.review_required or not phrase.translation_matches_submitted or not phrase.reported_matches:
        raise ValueError("phrase_translation_unverified")
    query_id = queries["reporting"][0]
    identifiers = start_checkpointed_pubmed_retrieval(
        project, query_id, client, date_window=DateWindow(date(1900, 1, 1), datetime.now(timezone.utc).date()),
        page_size=MAX_BATCH_IDS)
    if identifiers.status != "identifiers_reconciled_metadata_pending":
        raise ValueError("identifiers_unverified")
    efetch.expected = identifiers.snapshot.pmids[:1]
    partial = collect_pubmed_metadata(project, query_id, efetch, batch_size=1, max_batches=1)
    records = _records(project, accepted.run_id, query_id)
    if partial.committed_metadata_ids != 1 or not partial.missing_pmids or len(records) != 1:
        raise ValueError("metadata_pause_unverified")
    pmid, raw = next(iter(records.items()))
    state = dict(project_id=str(project.identifier), run_id=accepted.run_id, query_id=query_id,
                 first_pmid=pmid, first_sha256=sha256(raw.encode()).hexdigest(),
                 count=identifiers.snapshot.root_count, requests=client.requests+1)
    (workspace / STATE).write_text(json.dumps(state), encoding="utf-8")


def resume(workspace, client, efetch):
    saved = json.loads((workspace / STATE).read_text(encoding="utf-8"))
    project = open_project(workspace / PROJECT)
    run_id, query_id = saved["run_id"], saved["query_id"]
    if str(project.identifier) != saved["project_id"]:
        raise ValueError("wrong_project")
    records = _records(project, run_id, query_id)
    if (set(records) != {saved["first_pmid"]} or
            sha256(records[saved["first_pmid"]].encode()).hexdigest() != saved["first_sha256"]):
        raise ValueError("first_batch_changed")
    ids = resume_pubmed_checkpoint(project, query_id, client)
    if ids.status != "identifiers_reconciled_metadata_pending" or ids.snapshot.root_count != saved["count"]:
        raise ValueError("source_recount_failed")
    efetch.expected = tuple(pmid for pmid in ids.snapshot.pmids if pmid not in records)
    done = collect_pubmed_metadata(project, query_id, efetch, batch_size=MAX_BATCH_IDS, max_batches=1)
    final = _records(project, run_id, query_id)
    if (done.batches_requested != 1 or done.missing_pmids or set(final) != set(ids.snapshot.pmids) or
            done.committed_metadata_ids != saved["count"] or final[saved["first_pmid"]] != records[saved["first_pmid"]]):
        raise ValueError("metadata_resume_unverified")
    result = dict(checked_at_utc=datetime.now(timezone.utc).isoformat(), queries=client.queries,
                  checked_phrase_translation=True, identifiers=saved["count"], metadata=len(final),
                  first_batch_unchanged=True, first_record_skipped_on_resume=efetch.called,
                  requests=saved["requests"]+client.requests+1,
                  source_retrieval_verified=False, licensed_text_exported=False)
    (workspace / EVIDENCE).write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("start", "resume"))
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args(argv)
    email = os.environ.get("RESEARCHY_NCBI_CONTACT_EMAIL")
    if not email or os.environ.get("RESEARCHY_PUBMED_SAMPLE_AUTHORIZED") != "true":
        print("Manual sample authorization and private NCBI contact configuration required.", file=sys.stderr)
        return 2
    try:
        client = SampleClient(args.stage, email=email, api_key=os.environ.get("RESEARCHY_NCBI_API_KEY") or None)
        (start if args.stage == "start" else resume)(args.workspace, client, SampleEFetch(client))
    except Exception:
        print("Source acceptance incomplete. Sample did not pass.", file=sys.stderr)
        return 3
    print("Completed the authorized sample stage.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
