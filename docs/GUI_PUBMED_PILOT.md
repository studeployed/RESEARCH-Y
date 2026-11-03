# P1-06f5 — Host-confirmed PubMed pilot count in the isolated desktop prototype

Date: 3 November 2026. Verified owner-merged PR #59 baseline:
`8bbe11281c982ba9aa3b7684fa76e1aeceb2dfb3`.
Parents: issues #41, #43, #9, #7 and #6. The version-controlled
`RESEARCH-Y_SPEC.md` remains authoritative and unchanged. Scoped
requirements: SEARCH-06–14, SRC-01, RUN-01/03/04/05, COUNT-01/03/05,
AUDIT-01/03, UI-04/05, SEC-01/03/04/05 and partial AT-05/06/17/19/21.

## Purpose and bounds

The user can approve frozen OR-only strategies, explicitly select a saved
pending run, and verify exact PubMed and Web of Science Starter source plans
and a Peer Review of Electronic Search Strategies (PRESS) self-check.
PR #59 introduced a one-shot, audited, *count-only* PubMed ESearch service
that validates the exact saved plan and records the submitted-versus-accepted
provider query translation. This increment connects that **existing
service** to the existing supervised application worker and the approved
*isolated* NiceGUI 3.18.0 / pywebview 6.2.1 feasibility interface.

**This is not a completed desktop application, source retrieval, or
authorisation to run live NCBI tests as part of development.** The feature
requires a separately and deliberately configured host contact, an exact
approved query, and **two distinct researcher actions** before the actual
provider request. No live requests are made by the new automated tests.

## Local trust and credential handling

A transient `PubMedHostProfile` contains the software contact email and
optional National Center for Biotechnology Information (NCBI) PubMed E-utilities
application programming interface (API) key. In this **experimental** launcher
only, the Python host may consume
`RESEARCHY_GUI_PUBMED_CONTACT_EMAIL` and optionally
`RESEARCHY_GUI_PUBMED_API_KEY` from its **pre-existing trusted process
environment** at startup. It immediately removes both names from the host
process environment. The native/browser page cannot set, read or inspect
the profile or send a contact/key through a route. An absent/invalid profile
disables the pilot control; an API key without a contact fails closed.
No key is needed for a slower, unauthenticated ESearch account when a
valid contact is provided, but the existing client still enforces
conservative pacing.

The host keeps credentials in memory only. An allowlisted
`pubmed_pilot_count` `ApplicationCommand` conveys them transiently
to the supervised, spawn-isolated Python worker. The command's repr excludes
its arguments, the worker returns static failure codes and the underlying
`pubmed_pilot` audit service refuses to journal credential echoes.
The separate `pubmed_pilot_read` operation accepts **only the original
canonical pilot ID**, no query, contact or key. The application never writes
credentials to the project, source data, SQLite audit, recent-project index,
GUI read model, test artifact or ordinary diagnostics. The browser receives
only a boolean saying whether the profile is configured.

This environment hook is **not** final installation/key management.
User-friendly, persistent secrets management (e.g., protected operating-system
credential facilities), authorised contact setup and security validation of
the packaged application are future design/release work. Environment
variables can be observed by sufficiently privileged local processes; this
prototype does not claim a hostile same-account sandbox.

## Explicit offer and consent

Once the researcher explicitly selects a pending run and invokes the
`preflight_read` verification, the interface lists the source-backed
**PubMed group query identifiers and exact stored expressions**. Selecting
one only offers a preview; the trusted host independently refreshes the
whole frozen plan through the worker and requires the chosen ID to belong
to its exact PubMed query inventory. This stage never calls NCBI.

The browser then shows the *locked exact query* and explains that the
separate **Confirm one PubMed count-only request** control will send one
official ESearch HTTPS POST (`retmax=0`; no records or abstracts), use
provider rate limits and consume any applicable request budget. **Cancel
without sending** discards the proposed attempt and writes nothing.
No automatic or test-only HTTP route can authorise the count.

On the explicit confirmation action only, the trusted host generates/preserves
one UUID, passes the original run/query/plan hash and transient contact/key
to the supervised `pubmed_pilot_count` operation. The existing core service
rechecks that the run remains pending and that the exact OR-only source plan
has not changed, writes its immutable *request* event before the provider
call, and appends an *outcome* event after strict count/translation inspection
and fresh plan validation. Any returned count, including **0**, is a
**provisional provider-reported pilot count**, not source-query completion.
Translation changes, warnings, provider errors and an uncertain request
are surfaced prominently without inventing matches.

## Failure, restart and recovery

The host retains the exact pilot UUID/query/plan when an operation or
its immediate post-response observation is uncertain. It blocks project/run
changes or incompatible operations until the researcher invokes
**Inspect original pilot receipt (no network)**. This read-only worker
operation checks the original journal receipt and its identities; it
**never reissues ESearch**. If an outcome was committed but the worker reply
was lost, it shows that durable result. If a request exists without a final
outcome, the attempt is **`requested_indeterminate`**; it is not
automatically retryable. If there is definitively no request receipt after
the first supervised worker became terminal, the attempt is
**`not_recorded`**, not an inferred network success.

A new source attempt requires reselecting the exact query and confirming
a **new UUID**, even after an indeterminate old attempt. Earlier journal
receipts remain append-only and independently readable by the original
ID from the core service. The experimental GUI does not yet have a complete
restart-aware historical pilot ledger or full credential-management workflow;
those remain future acceptance items.

Results always retain `count_only=true`,
`retrieval_verified=false`, `source_retrieval_verified=false`,
`search_completed=false`, `execution_authorized=false`,
`automatically_retryable=false`. The ordinary source-query reported counts,
run status, complete-retrieval indicators and Excel source-count projections
are unchanged; group counts are never summed as the global publication union.
No Web of Science pilot, actual peer review, provider query-length splitting,
known-relevant-paper matching, final query execution or source completeness
is claimed.

## Tests and merge gate

Offline cross-platform tests exercise worker allowlists and credential
redaction, missing/invalid host profiles, exact approved query selection,
two-step user confirmation, cancelled offers without writes, mocked official
ESearch transport, zero/provider provisional counts, preserved source counts,
lost result replies, failed journal inspection, indeterminate interrupted
queries, new-request-ID consent and invalidated query plans. The project,
preflight and read-only original-receipt operations use real SQLite and the
real supervised application worker; synthetic count transport prevents
live provider requests. Existing graphical dependency/lifecycle checks are
preserved, but a separate physical Windows UI click-journey acceptance case
remains unverified until recorded.

For merge: verify exact current HEAD; four core Python regressions plus
graphical dependency/lifecycle checks where run; completed exact-commit
Codex code review FIRST then security review, matching individual receipts
and dispositioned findings. Do not merge without explicit owner approval.
