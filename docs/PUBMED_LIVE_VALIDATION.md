# P1-04e — Controlled live PubMed source acceptance

**Status:** P1-04e manual workflow merged. Its second live PubMed ESearch / one-PMID EFetch smoke **succeeded on 30 October 2026**; this does not establish complete retrieval.
The local execution environment cannot resolve the NCBI E-utilities hostname;
the public web retriever also could not access the ESearch API endpoint. No
runtime NCBI contact email or private API key is configured here. These are
external blockers, **not** evidence that PubMed or its API is unavailable.

The authoritative requirements remain `RESEARCH-Y_SPEC.md` (SEARCH-07,
SRC-01 through SRC-04, RUN-04/05 and AT-06/07/09/19). No substantive
specification or source-query logic is changed in this increment.

## First real NCBI response — 30 October 2026

[Actions run #41066478463](https://github.com/studeployed/RESEARCH-Y/actions/runs/41066478463)
submitted the generic query ("ECMO"[All Fields]). PubMed accepted
"ECMO"[All Fields] (without redundant outer parentheses) and issued no warnings.
The script returned query_review_required / exit code 3 because it required
literal string equality. No count was printed, no PMID page retrieved,
and no EFetch metadata acquired. The contact and transport worked.

P1-04f proposes treating only balanced *whole-expression* outer grouping
as equivalent. Every other term, field, operator or internal-group change
still requires review. Exact provider translation is retained for audit.
AT-06/07/09 remain partial pending rerun and larger live validations.
## Verified one-record live smoke — 30 October 2026

[GitHub Actions run #41073931474](https://github.com/studeployed/RESEARCH-Y/actions/runs/41073931474)
on merged commit `19ba4d2de7359d9f814858bd90b7f2b46db171b1` completed
successfully at 14:42 UTC. The exact query `("ECMO"[All Fields])`
was accepted as `"ECMO"[All Fields]` with no warnings. PubMed reported
**19,479** source matches. The first fetched PMID was `42958294`;
matching EFetch metadata and a three-section abstract were received.
The script correctly retained `source_retrieval_verified=false`.
Thus query acceptance for this test expression and the one-record
metadata path are live-verified, but full AT-06 terminology coverage,
full >10,000 source ID union (AT-07), and real checkpoint recovery
(AT-09) are **not** established by this smoke.

The next proposed increment P1-04g adds a separate strictly manual
>10,000-ID + first-page durable pause + fresh-process resume validation.
See [P1-04g validation procedure](PUBMED_LIVE_IDENTIFIERS.md).
## What can be tested now, and what cannot be inferred

The already merged `scripts/pubmed_source_smoke.py` uses the actual
`PubMedESearchProbeClient`, bounded PubMed identifier page parser, and
`PubMedEFetchClient`. On live provider access, it:

1. Submits the exact test query `("ECMO"[All Fields])` with fixed HTTPS POST,
   registered tool/contact details and optional key, at no more than the
   existing client rate limit.
2. Captures PubMed's source-reported count, `querytranslation`, ESearch
   warnings and any unexpected expression mapping; it stops for researcher
   review rather than silently accepting changed interpretation.
3. Requests **one** of the matching PMIDs in an ESearch ID page and checks
   the count and accepted translation are consistent with the count query.
4. Requests that PMID through EFetch XML, checks its exact PMID identity, and
   reports source title, abstract status, UTC time and missingness without
   printing abstract text, secrets, private paths or provider XML.

A successful smoke establishes only **AT-06 partial live query acceptance and
one SRC-04 live metadata path** for the specific query and date. It is NOT a
complete database search, full query/term permutation acceptance, a validated
`>10,000` PMID identifier union, record retention-rights clearance or a
passed live crash/restart test. Preserve all these as **partial/unverified**
until additional controlled validations exist.

## How to run securely

For a local source check (PowerShell) in a trusted clone, install the
application in Python 3.12 or 3.13, then use:

```powershell
$env:RESEARCHY_NCBI_CONTACT_EMAIL = "contact-you-control@example.org"
# Optional, if independently configured:
# $env:RESEARCHY_NCBI_API_KEY = "<your private key>"
python scripts/pubmed_source_smoke.py --query '("ECMO"[All Fields])'
Remove-Item Env:RESEARCHY_NCBI_CONTACT_EMAIL
Remove-Item Env:RESEARCHY_NCBI_API_KEY -ErrorAction SilentlyContinue
```

For a hosted run, configure the private Actions secret
`RESEARCHY_NCBI_CONTACT_EMAIL` in the GitHub repository at
**Settings → Secrets and variables → Actions → New repository secret**.
Use a legitimate developer contact for NCBI E-utilities, and follow any
necessary NCBI registration policy. Optionally configure
`RESEARCHY_NCBI_API_KEY` in the same location. **Do not** paste values in
workflow inputs, public commit history or PR comments.

The workflow is already merged on `main`. Open **Actions → PubMed live
ESearch / EFetch smoke (manual) → Run workflow**. GitHub only exposes manual dispatch for workflow
files available on the default branch. This workflow is deliberately absent
from automatic PR/push/scheduled events. There is no credentialed action on a
pull request. The script runs the generic query only; GitHub Actions logs of
this public repository may be publicly visible.

If the email secret is absent, the workflow fails before any source request.
If the source is unreachable, rate-limited, translates unexpectedly, or
returns inconsistent results, record **not verified** and investigate the
failure. Do not translate a failed test into a fabricated zero-hit result.

## Evidence checklist (record after actual execution)

- Repository commit SHA and GitHub Actions run URL (or local script version).
- UTC execution time, exact generic submitted query, accepted translation,
  PubMed reported hit count and any warnings/review reasons.
- ESearch page count and selected PMID; EFetch returned matching PMID,
  field/abstract availability and source XML digest when available.
- Response status, retryability/transport errors, scientific interpretation,
  and explicit pass, review-required, incomplete, or not-run outcome.
- API key, real contact address, full protected abstract text, and raw
  licensed/provider content must **not** enter public evidence logs.

**Additional validation still needed** (separate controlled runs):

- AT-07: an explicit and safe >10,000-hit PubMed query with complete,
  auditable Create Date coverage, disjoint partition counts, unique retrieved
  PMID union, and no silent truncation; a count-only split is insufficient.
- AT-09: deliberately interrupt real paginated retrieval after a verified
  checkpoint commit; close/reopen and resume; compare unique IDs, completed
  batches and source status without unverified success claims.
- Final metadata and source-count reconciliation, changing provider
  collections, overfull single-day partition fallback and rights compliance.

## Large-scale validation incident — 31 October 2026

On merged commit `d08402931d5e4cc23d662b71c0da65a30931afeb`,
[live run #41207501975](https://github.com/studeployed/RESEARCH-Y/actions/runs/41207501975)
reported 19,483 unrestricted PubMed matches but could not
establish the first Create Date partition plan. It made three
source requests and committed zero PMID pages; no recovery
stage was reached. The earlier script retained only a generic
failure reason, not the first partition's accepted translation,
warnings or reported count.

P1-04h adds a separate [manual count-only diagnostic](PUBMED_PARTITION_DIAGNOSTIC.md)
to capture those distinctions without changing the accepted
query or fetching identifiers. AT-07 and live AT-09 remain partial.

## NCBI references

- E-utilities parameters and PubMed 10,000-identifier limit:
  https://www.ncbi.nlm.nih.gov/books/NBK25499/
- E-utilities contact and pacing:
  https://eutilities.github.io/site/API_Key/usageandkey/
- PubMed field/phrase interpretation:
  https://pubmed.ncbi.nlm.nih.gov/help/
