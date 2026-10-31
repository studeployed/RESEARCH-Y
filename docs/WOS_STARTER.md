# P1-05a — Web of Science Starter source contract and live access gate

**Status:** First P1-05 increment, proposed for review. No live Starter response has been obtained in this increment. The authoritative `RESEARCH-Y_SPEC.md` is unchanged.

**Requirements:** SEARCH-06/08/09/10/13, SRC-05–08, RUN-04/05, METH-04/05 and SEC-05; AT-08/09/19/21 remain partial. Parent issue: [#8](https://github.com/studeployed/RESEARCH-Y/issues/8).

## Increment boundary

P1-05a implements the source-facing contract first: safe access, observable institutional allowance, strict pages, source-record preservation and a small manual live check. It does **not** implement the whole P1-05 milestone. P1-05b must add durable SQLite page/audit storage, transactional source linkage, quota-aware multi-day pause/reopen, bounded retry scheduling and full result reconciliation. No temporary in-memory client is described as a durable checkpoint.

This staging avoids building persistence around an unverified service response. It follows the same distinction between fixture evidence and real-source acceptance established during PubMed validation.

## Verified provider documentation versus adapter hypotheses

The current Clarivate [Starter description](https://developer.clarivate.com/apis/wos-starter) and [OpenAPI definition](https://developer.clarivate.com/apis/wos-starter/swagger), consulted 31 October 2026, establish:

- The institutional member allowance is up to 5,000 requests/day, distinct from the 50/day trial. Higher institutional plans exist, so an observed daily allowance of at least 5,000 meets this diagnostic's allowance floor; this does not infer the licence's other terms.
- `GET https://api.clarivate.com/apis/wos-starter/v1/documents` uses an `X-ApiKey` header. This adapter uses HTTPS only, even where older generated examples show HTTP.
- Topic (`TS`) searches title, abstract, author keywords and Keywords Plus. This is narrower than web All Fields and does not search article full text.
- Responses expose `metadata.total`, `metadata.page`, `metadata.limit` and `hits`; endpoint page limits are 1–50. General introductory pagination text mentions zero, but the endpoint parameter schema specifies a minimum of one. Accordingly the access probe requests **one real record**, not an assumed count-only mode.
- The documented record schema includes `uid`, bibliographic fields and optional identifiers/citations/keywords. It does not promise abstract text or a server-returned translated query.

**Unverified adapter expectations:** `X-RateLimit-Limit-Day`, `X-RateLimit-Remaining-Day` and `X-RateLimit-Limit-Second` are recognised quota headers. Their actual presence and meaning for this user's subscription must be checked live; the OpenAPI document does not guarantee those response headers. Missing, contradictory or malformed headers remain **unverified**, never replaced with configured values. Remaining requests alone do not prove the daily entitlement. Annual/per-second quotas are not mistaken for daily quotas. A failed or missing quota check preserves the initial source count but prevents continuation.

## Implemented behaviour

`src/research_y/wos_starter.py` validates the existing compiler's quoted, OR-only `TS=(...)` expressions without rewriting them. Request page sizes are 1–50. Operational bounds reject excessive query bytes, invalid pages and oversized responses without truncation; they are safety bounds, not claimed provider maxima. Database selection is explicit and recorded; the manual smoke uses `db=WOS` (Core Collection). No publication-date, language, species, edition or publication-type exclusions are added. `LD+A` is the documented ascending Load Date sort, not a snapshot guarantee.

The parser distinguishes genuine zero matches from failures. It rejects missing metadata, non-integer counts, unexpected page/limit echoes, truncated pages, invalid/repeated accessions, malformed/duplicate-key/non-finite JSON and embedded provider errors or warnings. It preserves all returned record fields, including unfamiliar ones, in an independent serialised source record. Missing abstracts are `not_returned_by_source`, not evidence that the publication has no abstract. Unexpected abstract fields are retained but not silently normalised. Rights remain `licence_review_required`. The original response string and its SHA-256 digest are available in memory for later lawful storage.

`accepted_translation=None` and `translation_status=not_exposed_by_starter_contract` are deliberate. Successful HTTP or matching counts do not establish semantic equivalence of a server translation that the service does not supply. Representative known-item and terminology checks remain a separate live acceptance task.

`src/research_y/wos_starter_client.py` uses a fixed origin, refuses redirects, keeps the key out of URLs and exception messages, serialises calls and spaces them by at least 1.05 seconds. Each call makes at most one network attempt; attempts consume an explicit local budget. No automatic retries occur in P1-05a. HTTP 429/5xx and `Retry-After` (seconds or HTTP-date) are surfaced safely; subsequent calls cannot disregard an observed delay. An error requires explicit revalidation rather than an uncontrolled retry loop. No daily reset time is guessed. Separate clients do not yet coordinate durable quota consumption; that is P1-05b work.

A page-sequence validator checks a contiguous prefix with unchanged query, collection, sort, page size and source count, and rejects cross-page duplicate accessions. It never marks the entire source verified.

## Manual live check after merge

The new workflow is **Web of Science Starter entitlement and paging smoke (manual)**, `.github/workflows/wos-starter-live-smoke.yml`. It runs only through `workflow_dispatch`, never normal push/PR/scheduled tests, and shares a dedicated concurrency lock.

After review and explicit owner-approved merge, add the existing institutional Starter application programming interface (API) key as the private repository Actions secret **`RESEARCHY_WOS_STARTER_API_KEY`**. This is not the National Center for Biotechnology Information key; do not paste either credential into chat, a query or a pull request. The secret is exposed only to the smoke step.

The fixed public diagnostic `TS=("ECMO")`, with `db=WOS`, makes at most **three requests**: a one-record access/count probe and, only with verified daily allowance/headroom, pages one and two at 50 records/page. The pilot's first accession must agree with the first full page. Counts and duplicate-free adjacent pages must reconcile, and institutional quota evidence must remain valid on each response. A small result set cannot claim the two-page acceptance scenario passed. Quota exhaustion, unknown entitlement or changing source data stops the sample as incomplete.

The result artifact contains only the fixed query, scope, counts, missingness totals, quota observations, timestamps, response/accession-union hashes and safe error categories. It contains **no titles, accession list, abstracts, source payloads or credentials**. It is saved on expected failure as well as success. The workflow does not modify a research project. The result always retains `source_retrieval_verified=false`, `full_retrieval_tested=false` and `durable_recovery_tested=false`.

## Tests and acceptance still required

Offline tests cover a 103-record 50+50+3 fixture, exact page identity, source-count drift, duplicate IDs, missing fields, unknown/trial/exhausted quota, request budgets, pacing, authentication failure, redirects, Retry-After, malformed JSON and secret echoes. Smoke tests verify the request sequence, absence of licensed content in public evidence and equality of the fixed query with the production compiler.

Required before claiming P1-05 complete: real entitlement and 50-record pagination evidence; durable project migration and transactional storage; quota exhaustion and resumption across days without refetching successful pages; source-change reconciliation; bounded retry/recovery; metadata linkage and final count/uniqueness checks. Passing this increment's tests does **not** pass all of AT-08 or AT-09.
