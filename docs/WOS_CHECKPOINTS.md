# P1-05b — Durable Web of Science Starter retrieval

**Status:** implementation for review; no new live full-result/recovery acceptance is claimed. The approved `RESEARCH-Y_SPEC.md` is unchanged. This increment addresses SRC-05–08, RUN-01–07, PROJ-04/06, DATA-03–06, COUNT-01/03/05 and AT-08/09/19/21. Product-wide acceptance remains partial.

## Verified source baseline

The real Starter smoke [run #41254004073](https://github.com/studeployed/RESEARCH-Y/actions/runs/41254004073), 31 October 2026 at 23:48 UTC on `cc0f695c2e5c8b2d9710cc6ddb091640890d9b20`, used `TS=("ECMO")`, `db=WOS`, `sortField=LD+A`. It observed 19,574 matches, a 5,000/day allowance, and 4,997 remaining after three requests. Two adjacent 50-record pages passed; titles were present and abstracts were not returned. `docs/evidence/wos-starter-41254004073.json` retains the original aggregate evidence, not licensed records. This historical count is not a permanently expected value.

Official reference: [Starter API](https://developer.clarivate.com/apis/wos-starter) and [OpenAPI contract](https://developer.clarivate.com/apis/wos-starter/swagger). Starter Topic coverage is narrower than web All Fields and does not search full article text. No accepted-query translation or frozen result-set token is exposed by the consumed contract. Source warnings/errors remain fail-closed.

## Versioned local storage

SQLite schema **4** adds six source-query-scoped tables for the immutable plan, request attempts, observed payloads, acquisition pages, accession/source-record links and verification receipts. Existing v1/v2/v3 projects receive a consistent, verified pre-upgrade backup and an atomic schema/audit upgrade; failure leaves the prior database and backup intact. New projects start on v4. No existing PubMed table or record is replaced.

`create_wos_checkpoint(project, query_id, retention_authorized=True)` only accepts an existing pending WoS query that exactly matches a chunk compiled from its frozen, researcher-approved OR strategy. It binds project/run/strategy/group identity, the exact query, explicit collection, page size, sort order and compiler snapshot hash. Unknown extra parameters are refused. A count remains unknown until observed, never inferred from inserted records.

The caller must confirm permitted local retention under the applicable source terms. Original Starter fields (including unknown fields), missingness and rights labels remain separate from chosen publication metadata. Each acquisition page, source records, query memberships, accession index and audit event commit atomically. Repeated group membership shares identical source records within a run; conflicting metadata is preserved as a separate response observation and stops reconciliation, never overwrites an existing source record. No publication is automatically created or deduplicated here.

Payload and descriptor SHA-256 checksums, reparsed provider metadata, contiguous page numbers, ordered accession hashes, source-record values and query memberships are checked before reuse. SQL triggers protect immutable history. These checks detect accidental or inconsistent modification; they are not authenticity guarantees against someone able to rewrite the entire database.

## Bounded worker and recovery

`run_wos_checkpoint(...)` is a synchronous, bounded worker session, independent of any graphical interface. A request is reserved durably **before** network access. Validated responses and their safe quota facts are then committed transactionally. A stopped process may leave an outcome-unknown reservation; the code does not claim that request succeeded, failed or cost zero quota.

One Starter worker may own a project at a time. Ownership tokens fence stale callbacks. A crashed worker is not silently stolen: `recover_wos_worker(..., previous_worker_stopped=True)` requires explicit confirmation that the old process is stopped, records abandoned outcome-unknown attempts and permits a new ownership token. Cooperative pause and cancellation persist; an in-flight validated page may finish committing, but no next page is requested.

Each resumed session requires a fresh credential-bearing client and performs a one-record source count/first-accession/quota revalidation. Acquisition then requests **only missing pages**, retaining successful pages unchanged. A network response lost before its transaction commits may need refetching; the uncertain attempt stays in the journal.

Progress exposes reported matches, records/pages committed, expected pages, verification pages, total reserved requests, confirmed transport attempts, unknown outcomes, observed allowance/headroom, failure count and earliest retry time. Credentials are never passed to the checkpoint store or serialized into plans, payloads or audit events; the existing client rejects a provider response that echoes its configured key.

## Quota and retries

The verified source headers, not a configured assumption, establish the allowance. No midnight reset time is invented. Exhausted allowance causes a durable pause and at least a one-hour **probe cooldown**, not a prediction of reset. Later resumption must explicitly request `revalidate_quota=True`; even then the saved cooldown and any longer server Retry-After remain binding, and new provider headers must permit continuation. A fresh client cannot erase the stored stop state.

Retryable failures persist exponential minimum delays and respect longer Retry-After values. Three failures without forward acquisition/verification progress stop further retries as incomplete; a successful revalidation probe alone does not reset this counter. Each invocation also has a finite request budget. There is no implicit background timer, busy polling, unlimited retry or automatic multi-day credentialled workflow. A user/application scheduler must explicitly invoke an eligible later session.

## Reconciliation and its limits

Matching counts alone cannot detect replacement of records while retaining the same total. After all acquisition pages are stored, the worker makes a **separate, explicitly budgeted identity-verification pass** over every page, comparing ordered accession identities to the acquisition ledger, then makes a final one-record count/first-accession check. This deliberate verification is not a repeated acquisition or duplicate insertion.

A restarted verification session starts a new verification epoch from page 1; old receipts are preserved but cannot establish consistency for a new session. Acquisition remains resumable across days without repeating successful acquisition pages. **The final verification sweep must fit within one uninterrupted worker session and available quota.** Very large or unstable sources may therefore remain incomplete and require later provider-specific reconciliation design. No source restriction is bypassed or query silently narrowed to force success.

Successful observed enumeration uses `completed_with_warnings` and `enumeration_reconciled=True`, with `provider_snapshot_guaranteed=False`, `source_retrieval_verified=False` and `abstract_enrichment_complete=False`. Two matching observations are not proof of an atomic frozen provider snapshot. Count drift, same-count identity changes, page overlap, metadata conflicts, invalid responses or incomplete verification prevent reconciliation. The parent multi-source run remains incomplete, and group/chunk union, cross-source deduplication, enrichment and release-level completion remain separate gates.

## Tests and opt-in live gate

Offline fixtures use the actual project, schema, compiler, source client/parser and checkpoint code with synthetic network responses. They cover 10,005 records; 50-record/final-page boundaries; zero versus failed search; source-count and same-count identity changes; repeated memberships; quota exhaustion and next-day observed recovery; persisted backoff/failure budgets; pause/cancel; rollback on audit failure; migration backup/rollback; checksums; project relocation; concurrency fencing; and an actual child process terminated after request reservation. Local fixture passes are not live acceptance.

After review and explicit owner-approved merge, **Web of Science Starter durable retrieval and recovery (manual)** can be dispatched on `main`. It reuses `RESEARCHY_WOS_STARTER_API_KEY`. A required checkbox confirms that source terms allow temporary local retention of up to 30,000 records for the test. The workflow is not triggered on push, pull request or schedule.

The first process saves one real 50-record acquisition page and pauses. A second process reopens the local project, revalidates and acquires the remaining pages, performs the identity sweep and final count check. The fixed public query must have more than 50 and no more than 30,000 matches. Budgets are one initial request and at most 1,300 resume requests, 40 minutes total, with existing serial pacing and actual quota enforcement. At the historical 19,574-match count, the planned successful path is 392 acquisition pages plus 392 verification pages and two one-record checks: **786 requests**, not just 392.

Only aggregate counts, purpose counts and hashes are exported in `wos-checkpoint-evidence.json` (14-day artifact retention). Source titles, accessions, abstracts, raw payloads, project database and credentials remain off public artifacts/logs. The runner's local project is ephemeral; this is controlled two-process same-run evidence, **not live multi-day or portable-archive validation**. A stopped/failed job is not a pass. No new large live test has yet been performed for this increment.
