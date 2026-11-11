# P1-06l1 — Original-source-backed provisional publication workbook (internal renderer)

**Authoritative baseline:** owner-merged pull request (PR) #94, `main` `a53d47fb45108d096ab0522cb30ba21d18fbfbc5` (11 November 2026). The version-controlled `RESEARCH-Y_SPEC.md` remains unchanged. This is a bounded **Phase 1 preparatory export** contribution toward EXPORT-01/03/04, AUDIT-01, DUP-01, COUNT-01 and AT-10/18/19/21/22, not acceptance of those requirements.

## Why this increment follows the foundation/performance work

The current audited workbook covers only approved terms, strategy, original source queries and counts. It correctly avoids claiming that a collection of **independently materialised provisional identities** is a verified deduplicated master list. The real 100,000-source, original-SQLite project work has now demonstrated full source/audit retention and bounded source-linked pagination. Before enabling any user-facing **Master Results** export, RESEARCH-Y needs a reproducible, lossless original-link and group/query-membership **workbook foundation** that does not copy unlicensed article contents, mark source retrieval complete, invent unique publication totals or silently omit unmaterialised originals.

## Precise scope

New internal `render_provisional_manifest(project, run_id)` in `src/research_y/provisional_manifest_workbook.py` accepts one already opened versioned project and an exact run ID. It uses the **existing validated read-only original SQLite transaction**, computes the canonical entire-run `result_counts._snapshot` **once**, and generates a separate, genuine Excel workbook. The existing strategy/count workbook, published export receipts, user-facing command allowlist and graphical controls are completely unchanged.

It includes four clearly-labelled worksheets:

1. **Evidence & Limits** — original run/project ID, current count projection SHA-256 revision, original source and provisional identity denominators, unmaterialised original count, explicitly **UNKNOWN** verified unique publications, unverified source coverage, rights limits and `INCOMPLETE` status.
2. **Provisional Identities** — one row for every independently audited current-run publication identity (not an asserted unique paper), counts of selected-run and contributing historical-run sources, reviewed/confirmed source links and source/group memberships. It is not named `Master Results`.
3. **Original Source Links** — the internal retrieval ID and provider label of **each linked source contributing to a current-run identity**, including historical source contributions, plus **every otherwise unmaterialised original source in the selected run**, with its original run, linked provisional ID or explicit unmaterialised state. These rows do not infer accepted or rejected publications.
4. **Query Memberships** — original group/query identifiers and stored execution statuses for every source listed in the original-link worksheet, including retained historical-run contributions. No group membership is silently collapsed because the same publication belongs to several groups or sources.

All cells use the existing `_literal` workbook encoder with explicit text types and Unicode/Excel safeguards (no formula evaluation or metadata reinterpretation). Strict row limits are checked **before each output append**; the existing 128 MiB maximum output-size policy fails explicitly rather than truncating or uploading a partial result.

**No source titles, article text, abstracts, author names, accession identifiers, DOI strings, or provider-supplied metadata** appear anywhere in these worksheets. Internally assigned source and publication UUIDs and original query/group IDs remain for auditable linkage. This intentionally conservative rights boundary must be reviewed separately before wider redistribution of published literature metadata.

## Scientific and operational safeguards

- The canonical run count projection is recomputed from original audit and membership evidence in the **same read-only transaction** as workbook generation. The read is not a cached or guessed count, and does not alter or reclassify the original records.
- Each current-run publication ID comes from the actual selected-run association union, not from an arbitrary query-text match, browser cursor or inferred title/DOI. Every linked publication is revalidated through `identity._snapshot` and its complete original source/association event. Additional historical sources remain distinct source records.
- The renderer independently reconciles its number of provisional identity rows and selected-run source-link + unmaterialised counts against the original canonical run projection. Missing or duplicate originals, unverified/count-inconsistent evidence, workbook row-limit overruns and unsafe provider text fail rather than produce a plausible-looking partial file.
- It returns workbook bytes only to internal code. **It is not registered with `ApplicationCommand`, the audited export journal, or the graphical download interface.** It never chooses a destination, creates a published file, issues a provider network call, or grants researcher consent. The presence of a renderer is *not* an authorisation to publish source data.
- This is an original provenance **manifest**, not the complete Master Results sheet specified by EXPORT-01. It does not contain full abstracts/classification, deduplicated unique paper counts, faceted filters, source-specific rights decisions or a tested 100,000-row production export. Unverified source and deduplication status remain explicit.

## Failure-path temporary file hygiene

OpenPyXL 3.1.5 is pinned as the existing optional Excel dependency. Its write-only worksheets create intermediate on-disk XML files during `append()`, and `Workbook.close()` alone does not remove those files if generation aborts before `save()`. The renderer now explicitly closes each still-active worksheet's XML generator/writer and invokes the original writer's registered temporary-file cleanup on **every failure path**, including early Excel row-limit errors and interrupted cell serialization. Successfully saved worksheets have already been cleaned by OpenPyXL's own archive writer; they are not recreated or deleted again.

A regression exercises four actual write-only worksheets, three repeated row-limit failures and a separate injected serialization failure. It checks the original OpenPyXL temp registry **and the physical filesystem**, plus original SQLite byte immutability and absence of any published workbook. Unexpected cleanup failure itself is reported explicitly, not silently ignored. This safeguard does not authorise export publication, change the source rights boundary or change scientific counts.

## Offline regression acceptance

Versioned original SQLite fixture tests examine actual `.xlsx` worksheet structure and source rows for one linked, one unmaterialised and a separate historical run, multi-group membership, cross-run confirmed source association, no abstract/title/DOI/provider accession leakage, no spreadsheet formula execution, one original full-run validation, byte-for-byte original DB immutability, explicit Excel row/byte limit failures, and refusal of original source corruption without publishing an output.

The final specification's full EXPORT-01/03/04, AT-18/19 and AT-22 acceptance is **not** claimed. A later bounded increment must independently evaluate safe full-results metadata rights, large-workbook streaming throughput and audited publication/recovery before the user may select this export. `global_unique_publications` remains **unknown**, `deduplication_complete=false`, `source_retrieval_verified=false`, and `verified_complete=false`.

## Mandatory merge gate

Review exact current HEAD, Windows/Linux Python 3.12/3.13 ordinary tests, any new dedicated manifest workbook workflow and downstream original SQLite/GUI regressions triggered by changed paths. Obtain definitive commit-matched Codex **code review first**, then **security review**, examine individual review receipts and dispose of findings. A new commit restarts the gate. Never merge without explicit project-owner authorisation.
