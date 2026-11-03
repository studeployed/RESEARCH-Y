# P1-06f4 — Audited one-shot PubMed ESearch count-only pilot

Date: 3 November 2026. Authority: the unchanged repository
`RESEARCH-Y_SPEC.md` (especially SEARCH-06–14, SRC-01–04, RUN-01/03/05,
AUDIT-01/03, COUNT-01/03/05, SEC-01/03/05 and partial AT-05/06/17/19/21).
Baseline: owner-merged PR #58, `main` SHA
`6cfdf254709f15bb7738e178c9b8081350e297b5`.

## Boundary and purpose

An approved strategy and run may now be created from the isolated Research
Setup GUI, and PR #58 validates the exact immutable source query plan and
records an honest Peer Review of Electronic Search Strategies (PRESS)
self-check. The next bounded dependency is **one real count-only PubMed
probe**, using the project's already-tested National Center for Biotechnology
Information (NCBI) ESearch client; a recorded count is *not* a retrieved
article, accepted search strategy, or proof of complete results.

`research_y.pubmed_pilot.probe_pubmed_count_once` is a **trusted Python
service**, not an HTML route, graphical action, automatic background job, or
provider-execution worker. It takes a validated local project, an existing
pending run, one preflight-verified stored PubMed query ID, the SHA-256 hash of
the entire frozen plan, an explicit `confirmed=True`, a fresh caller-owned
canonical UUID for the attempt, and a host-configured
`PubMedESearchProbeClient`. The client validates contact information and
optional API key and only addresses the fixed official NCBI HTTPS endpoint.
Keys and contacts are never copied into the audit event. Credentials,
endpoint configuration and user consent remain prerequisites for the later
GUI/worker integration; this increment **does not** launch unauthorised live
requests.

This service calls the existing strict `client.probe(exact_query)`, which
requests `retmax=0` (no record identifiers), applies conservative pacing,
strictly parses provider counts/translation, and flags unexpected translation,
warnings, new Medical Subject Headings (MeSH), or unintended AND/NOT
operators for review. ESearch counts describe the provider's **current
reported matches** only. No hidden publication/language/species filters
or intersections are added. A count of zero is genuine and distinct from
missing/unverified count (`null`).

## Auditing, idempotency and failure recovery

Every explicitly confirmed attempt writes
`pubmed_count_pilot_requested_v1` to the pre-existing append-only
`audit_events` table **before** any network work, in a guarded SQLite
transaction. It binds the canonical pilot UUID, pending run/query IDs,
exact plan SHA, and frozen exact query, with no secrets. Existing immutable
plan checks validate the source, group coverage, query, status and empty
parameters before authorisation; no new schema/columns are introduced.

The provider call happens outside the SQLite write transaction. If a
strictly validated count/translation is returned, a separate
`pubmed_count_pilot_outcome_v1` record captures the count, checked UTC
timestamp, submitted versus accepted translation, review reasons and
source warnings (bounded and checked against the host contact/key).
Protocol errors create a static-code *failed* outcome with
`reported_matches=null`, never an invented zero. The service validates the
same plan again before recording any outcome. A changed/paused/invalidated
run is `stale_plan` and cannot accrue a verified pilot count.

A repeated call with the **same attempt UUID** returns the original audit
receipt without another provider call. If the process stops between the
request and its final receipt, the event remains
`requested_indeterminate`. This *does not* prove the request was sent,
nor that it was not sent, and the system must **not retry automatically**:
new requests consume an explicit new UUID and new researcher authorisation.
This fail-closed behaviour also prevents accidental duplicate counts after
a crashed worker or failed audit write. Concurrent attempts using the same
UUID cannot cause duplicate provider requests. Existing audit contents
remain independently readable after the run moves out of `pending`.

## Deliberate limitations

The main `source_queries.reported_matches` and status remain untouched.
The pilot count is stored in a **separate method-specific audit receipt**,
not as a completed search run. Return flags are always
`count_only=true`, `retrieval_verified=false`,
`source_retrieval_verified=false`, `search_completed=false`, and
`execution_authorized=false`. No record IDs, metadata, source completeness,
final deduplicated counts or combined multi-group union counts are implied.

This increment handles **one saved PubMed group query per explicit call**,
not Web of Science Starter pilot counts, all-source workload calculations,
query-size partitioning, known-relevant items, independent PRESS peer
review, full PRISMA-S reporting, source retrieval, GUI controls, permanent
user-key configuration or search execution. A per-group count cannot be
summed with others to invent a global publication count. The next step is
to connect this service to the supervised local application flow with
credential-safe configuration, visible consent and status, then develop
corresponding Web of Science pilot functionality.

## Test and merge gate

Offline disk-backed tests use synthetic ESearch transport responses and a
real approved strategy, source query plan and SQLite audit. They exercise
exact `retmax=0` requests, correctly reported counts including zero,
translation mismatch, official provider warnings, malformed inputs,
credential-echo rejection, network failures, crash/indeterminate audit,
concurrent same-UUID calls, stale plan changes, non-repeat after failed
outcome storage, immutable replay, reopening and unchanged final
source-record counters. **No public provider or institutional API call
occurs in normal CI.** These tests do not prove that a live provider will
return the expected count or fully recognise the medical terminology.

Require four Windows/Linux Python jobs on the current HEAD, plus definitive
completed Codex code then security review on the exact same SHA, matching
individual receipts and disposition of any substantive findings. Owner
authorisation is necessary to merge; no extra production dependency,
framework selection or specification change is approved by this PR.
