# P1-06f6 — Audited Web of Science Starter minimal-page pilot

Date: 3 November 2026. Source-of-truth: repository
`RESEARCH-Y_SPEC.md` (SEARCH-06–14, SRC-05–08, RUN-01/03/04/05,
COUNT-01/03/05, AUDIT-01/03, SEC-03/04/05, partial AT-05/08/17/19/21).
Baseline: owner-merged PR #60, `main`
`fd61d1eedd46e58c703a9b60c472eec84042e411`. Parent #8, #6, #41, #43.

## Exact provider contract

The Web of Science (WoS) Starter `/documents` endpoint accepts a page size
from **1 to 50**; zero is *not* a supported value for that endpoint.
Consequently, unlike PubMed ESearch `retmax=0`, this is **not truly a
count-only HTTP request**. A strictly bounded GET
`https://api.clarivate.com/apis/wos-starter/v1/documents` with
`db=WOS`, `page=1`, `limit=1`, `sortField=LD+A` and the
**unmodified, approved `TS=(...)` group query** can transiently return
one licensed source record. The existing `WoSStarterClient` checks the
response, rejects redirects, uses an `X-ApiKey` header, obeys a
conservative 1.05-second rate floor, has no automatic retries and
understands observed (not presumed) quota facts.

**Only the reported count and narrowly scoped non-licensed method evidence
are retained** by `research_y.wos_starter_pilot.probe_wos_starter_once`.
There is no storage of returned accession numbers, titles, abstracts,
unknown fields, complete response JSON, or a separate one-record publication.
A response SHA-256 is retained as a content-integrity fingerprint; it is not
a replacement for legally retained original metadata or proof that source
results did not change. Zero matches are a real observed count of zero; an
error/uncertain attempt is **null**, not zero. The transient record is
discarded after validation; `bibliographic_records_persisted=0`.

The Starter contract does **not** expose server-accepted rewritten query
text: `accepted_translation=null`,
`translation_status=not_exposed_by_starter_contract` and no invented
semantic equivalence. Web-interface All Fields and article full text are not
searched by Starter Topic. This pilot does not apply Medical Subject
Headings, AND/NOT intersections, language/species exclusions or arbitrary
query mutation.

## Trust, entitlement and quota

The trusted Python service accepts a validated project, one explicitly
approved **pending** run, one stored `wos` query and exact immutable
preflight plan SHA, a fresh caller-owned canonical UUID, actual
`WoSStarterClient` with a runtime key, and `confirmed=True`.
The user must explicitly consent to the single one-record provider
request; there is **no browser control or networked CI job** in this
increment. There is no new GUI framework dependency or schema migration.

The provider response supplies `metadata.total` and quota headers.
Successful institutional status requires valid observed daily allowance
of **at least 5,000**, rather than assuming a purchased entitlement, and
a known positive daily headroom. Other outcomes remain honest:

- `count_reported_sample_not_retained`: validated count with institutional
  daily allowance observed and headroom positive; **not** retrieval success.
- `entitlement_unverified`: a count was observed, but header absence,
  inconsistency, trial allowance or lack of remaining allowance evidence
  prevents claiming the required institutional entitlement.
- `quota_exhausted_after_probe`: valid institutional allowance observed,
  but its recorded remaining daily requests are zero.
- `probe_failed`: provider/protocol failure with unknown count, redacted
  static error and bounded Retry-After when supplied.
- `stale_plan`: provider replied, but the saved query/run/plan was modified
  before a durable result could be appended; count is **discarded**.
- `requested_indeterminate`: the request journal committed but there is
  no trustworthy outcome receipt. It may or may not have reached Clarivate.

Provider key and licensed payload fields never enter the pilot journal,
read result, ordinary logs, or test artifacts. The existing source client
also rejects a provider reply echoing the configured key, including
unrecognised source fields. Only safe quota integer facts, response digest,
count/status, observed UTC timestamp, query/plan identities and zero-record
retention labels are written.

The reservation transaction consults the project's **shared durable
WoS provider guard**. It refuses a live WoS retrieval worker, an unexpired
project cooldown, or recorded exhaustion unless a **new explicit
quota-revalidation** request is authorised *after* any server-directed
cooldown. Importantly, this guard now consumes both existing checkpoint
attempts and newer pilot audit observations. **An exhausted pilot blocks
the regular checkpoint retrieval worker as well**, preventing a fresh
client or different query from bypassing previously observed quota facts.

Quota headers from HTTP failures (including 429/403) and malformed
HTTP-200 bodies are captured **independently** of whether a valid count
was returned. All provider-observed `Retry-After` instructions—including
ones on otherwise successful HTTP 200 responses—create a durable absolute
hold that neither a new UUID nor `revalidate_quota=True` may bypass.
If a saved run becomes stale while its provider request is in flight,
its **count is discarded** but safe observed quota and cooldown evidence
are preserved and still restrict other pending runs. A non-representable
server-directed delay fails closed instead of being dropped. The
pilot's durable request timestamp also applies the existing **1.05-second
request pacing floor to subsequent checkpoint workers**, not merely to
fresh pilot clients. All such restrictions are enforced inside the same
shared provider guard. No daily reset time is guessed.
This is **project-scoped only**, not a cross-project or organisation-wide
quota coordinator; product-level and account-wide quota controls remain
future acceptance work. A pilot does not alter the underlying checkpoint
ledger or claim to have obtained user licence rights.

## Crash safety and evidence

Two append-only events, `wos_starter_pilot_requested_v1` and
`wos_starter_pilot_outcome_v1`, use the existing SQLite audit table.
The first is durably committed **before** requesting the provider;
the second after strict parsing and fresh plan revalidation. The ordinary
`source_queries.reported_matches`, run state, page/retrieval data and
global-unique publication counts remain untouched.

An identical attempt UUID replay only reads its previous journal; it
**never resends** the GET. A fatal process interruption or audit-write
failure after the first event leaves `requested_indeterminate`, not a
claim of failed network access. A different query, changed plan hash, or
different quota-revalidation choice using the same UUID is a conflict.
Concurrent callers of the same UUID cannot both send the provider request.
A genuinely new attempt requires a different UUID and explicit new
authorisation. Historical evidence stays readable after a run changes.

The returned status always includes
`count_only=false`, `sample_only=true`, `retrieval_verified=false`,
`source_retrieval_verified=false`, `search_completed=false`,
`execution_authorized=false`, `automatically_retryable=false`, and
`bibliographic_records_persisted=0`. There is no automatic transition
to final source execution, peer review verified, or a completed search.

## Tests, nonclaims and next task

Synthetic, disk-backed offline tests exercise an exact page-1/limit-1
fixed-origin request; safe title/UID non-retention; zero counts;
missing, trial or exhausted quota; quota observations from failed HTTP
responses; absolute server Retry-After deadlines shared with checkpoint
workers; HTTP authentication/network/rate failures; reflected secrets;
stopped worker, lost result, conflicting UUID, concurrent callers, audit
rollback, changed immutable source plan/run state, old project cooldowns,
separate explicit quota revalidation and inter-request pacing. Normal CI makes **no live Starter call**.

The next increment should expose this service in the isolated GUI/worker
using a **trusted host-only Starter key**, explicit single-query preview and
a separate consent action, with read-only recovery. Do **not** claim a
zero-record count-only API, actual independent PRESS completion, a full
source search, working credential installer, user-driven native Windows
click test, abstract enrichment, product release, or final completeness
from this service alone.

Merge requires all four Windows/Linux Python 3.12/3.13 checks on exact
HEAD, completed exact-commit Codex code review first then security review,
individual review receipts and resolved findings, followed by **explicit
project-owner approval**. No merge is performed automatically.


## Shared provider reservation while an attempt is in flight

A durable pilot request without its matching outcome is an **outstanding
provider reservation**, even after the minimum 1.05-second spacing interval
has elapsed. The shared project-scoped provider guard used by both the
minimal-page pilot service and the Web of Science checkpoint worker refuses
new claims while such a reservation remains unclosed. This is necessary
because a slow HTTP request might finish after the spacing deadline and
return a new provider cooldown or exhausted quota. A revalidation flag
does not authorise overlapping requests.

Completed pilots close their reservation only when the corresponding
immutable outcome is committed; their observed quota, Retry-After and
request-start pacing limits remain in force. An interrupted attempt
without a durable outcome may have already been sent, and remains
`provider_pilot_outcome_unknown` rather than being automatically
cleared after an arbitrary timeout. A future explicit recovery
mechanism needs to verify the prior worker has stopped and disposition
the unknown attempt, without overwriting audit receipts or silently
reissuing it. That recovery mechanism is **not** included here.
This is a fail-closed scope limitation, not a claim that ordinary
checkpoint work can always resume after a pilot process crashes.
