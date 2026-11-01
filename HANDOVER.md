# RESEARCH-Y handover — P1-05b review baseline

## Authority and merged state

Repository: https://github.com/studeployed/RESEARCH-Y. The approved version-controlled `RESEARCH-Y_SPEC.md` version 1.0.0-draft.1 remains authoritative and unchanged. This is an independent Python project. Current merged base: **`cc0f695c2e5c8b2d9710cc6ddb091640890d9b20`**, PR #27 / P1-05a. In-scope development and PR creation are authorised; **merging still requires explicit owner approval**. No new dependencies are introduced.

The Windows test-reporting problem in PR #27 was corrected by compact parameter labels and a regression guard, without weakening oversized-response tests. The revised four Windows/Linux Python 3.12/3.13 checks passed before merge. Keep those labels and the 15-minute ordinary test-job timeout.

## Verified live boundaries

- PubMed [run #41235232458](https://github.com/studeployed/RESEARCH-Y/actions/runs/41235232458), 31 October 2026: 19,483 unique identifiers, 43/43 pages, six disjoint leaves and controlled pause/reopen passed. See the existing `docs/evidence/pubmed-41235232458-summary.json`. Full metadata, broader queries and product-wide completion remain partial.
- Web of Science Starter [run #41254004073](https://github.com/studeployed/RESEARCH-Y/actions/runs/41254004073), 31 October 2026 at 23:48 UTC on the merged base: valid Clarivate credentials, actual 5,000/day allowance, 19,574 reported matches, two adjacent 50-record pages and 100 validated records. Three requests left 4,997 available; all sampled titles were present and abstracts were not returned. The original credential-safe aggregate artifact is retained as `docs/evidence/wos-starter-41254004073.json`.
- The owner has already configured **`RESEARCHY_WOS_STARTER_API_KEY`** with the working Clarivate key. Do not ask for it in chat or repeat an access-only smoke without a reason. The earlier Elsevier-key mismatch is resolved.
- Starter access/sample pagination is live-verified. **Full Starter acquisition and durable recovery have not been run live.** No fixture pass substitutes for that evidence.

## P1-05b — implemented for review, not yet accepted live

Read `docs/WOS_CHECKPOINTS.md`. New schema v4 adds immutable plans, journalled attempts, observed source responses, acquisition pages, accession/source-record links and independent identity-verification receipts. Existing projects are backed up and upgraded atomically; failure preserves the old database. Existing PubMed data and behaviour are unchanged apart from recognising the latest schema version.

The checkpoint worker binds the exact compiler-produced approved query and explicit source collection, retains every returned source field with rights/missingness labels, and atomically commits page/record/membership/audit data. Resumption probes actual source count/quota then fetches only missing acquisition pages. Unknown in-flight outcomes stay unknown; explicit confirmation that a prior worker stopped is needed before crash recovery. Tokens fence stale callbacks, and one Starter worker may own a project at a time.

Quota exhaustion pauses without assuming midnight or any other reset. Explicit later revalidation must respect saved cooldown/Retry-After and actual new quota. A finite request budget and three-failure-without-forward-progress ceiling prevent retry loops. No automatic background scheduler is introduced.

A separate, intentionally budgeted ordered-accession verification sweep plus final count/first-accession probe detects same-count changes. Verification restarted across processes creates a new epoch; prior receipts remain but cannot prove a fresh snapshot. **Acquisition is resumable across days; final verification must fit one uninterrupted session and available quota.** Unstable or too-large sources remain incomplete rather than weakening the checks.

Successful enumeration is `completed_with_warnings` with `enumeration_reconciled=True`, **not** a frozen provider snapshot, complete abstract enrichment, full group/chunk union or complete multi-source run. `source_retrieval_verified=False` and parent run `incomplete` remain intentional. Source conflicts retain observations without overwriting prior records.

## Tests and review requirements

New offline integration tests exercise production project/compiler/client/storage paths with synthetic source responses: 10,005 records, quota recovery on a later day, backoff/budget persistence, count and same-count identity drift, duplicates, metadata conflicts, shared group memberships, atomic rollback, ownership fencing, cancellation, relocation and a child process terminated after a request reservation. Migration tests preserve/recover v1/v2/v3 fixtures and validate backups. Local subset results and full-repository cross-platform CI must be distinguished in the PR.

Before merge advice, retrieve current PR HEAD, all four required CI jobs, code/security summaries, individual receipts and outstanding findings. Existing reviews are invalidated by any new commit. Recognise automatic reviews, do not create duplicates, and treat missing or contradictory completion/finding evidence as unverified. Never merge without owner authorisation.

## Next live gate after review and owner-approved merge

Dispatch **Web of Science Starter durable retrieval and recovery (manual)** on the new `main`. The required checkbox confirms that source terms permit temporary local retention for this controlled test. It uses the existing secret and fixed public ECMO Topic query. A first Python process commits one source page and pauses; another reopens, obtains remaining pages, performs the separate identity pass and final count check.

Limits: more than 50 and at most 30,000 matches, 1 initial plus at most 1,300 resume requests, 40 minutes, existing serial pacing and actual quota. At the historical 19,574 count this plans 786 requests including verification/revalidation. Only aggregate/hash evidence is publicly uploaded; the licensed local database is ephemeral. This is not live multi-day, portable archive, enrichment or whole-literature acceptance.

AT-08/09/19 remain partial until observed real-source full enumeration/recovery and remaining failure scenarios are assessed. Parent issue #8 stays open. Next milestones: remaining source acceptance, then P1-06 deduplication/master results/export/application shell. Deferred Windows junction hardening issue #11 still applies before untrusted archives/import.
