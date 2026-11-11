# P1-06k4d3 — Explicit two-batch materialisation in the experimental graphical interface

**Authority:** version-controlled `RESEARCH-Y_SPEC.md` (unchanged). **Baseline:** project-owner-merged pull request (PR) #85, `main` commit `f0874cefb41aa7a087231199077fe30b10035c80`, 11 November 2026.

This is a bounded interface increment for original-source provisional publication preparation, not a released desktop application, a verified deduplicated master list, or full acceptance test AT-22.

## User-visible workflow

Once a researcher explicitly opens a saved project **and selects a search run**, the experimental NiceGUI project application offers **two distinct alternatives**:

- The unchanged **one-batch** preparation, at most 64 source records per separate approval.
- An optional **finite two-batch** preview: at most 128 selected-run source records, in at most two separately audited transactions, with *one explicit consent* for this exact frozen window. It is **not** an automatic loop that runs to the end of a large project.

**Preview** is a read-only trusted-host `publication_window_preview` operation. The graphical panel displays the exact bounded batch count, number of separate provisional publication identities proposed, and total still unmaterialised. It plainly distinguishes provisional source-linked identities from *verified unique publications* (still **unknown**). No original abstract or licensed content is shown; no API request is made.

**CONFIRM** is a separate deliberate button with a researcher's entered name. The browser sends only the action and name: it cannot supply project paths, search runs, source IDs, batch sizes or SHA-256 consent tokens. The host supplies the exact selected-run identity and latest reviewed digest to the already allowlisted `publication_window_confirm` service. The worker retains PR85's full `BEGIN IMMEDIATE` scope/ID checks under each 64-record transaction, preserves unmodified originals and query memberships, and never merges publications because they have identical titles or digital object identifiers. The host consumes its offer **before** submitting the worker; it cannot be clicked twice to reuse approval.

The graphical page also supplies **Dismiss** (no write), and **Inspect stored originals (READ-ONLY)**. A user may switch between the old one-batch and new two-batch preview modes; creating an offer in one immediately invalidates an offer in the other. Switching selected run or opened project clears both offers, previous local observations and any consent. The new interface does not introduce a timer, background agent, new database table, new dependency or source-collection request.

## Returned worker messages are not accepted as proof of a durable write

After a successful-looking worker result, the host independently rereads the **original `publication_window_preview` count/evidence projection**, verifies the exact source/unmaterialised/provisional-identity transitions, and then inspects the retained selected-run report. Only after both checks pass does the interface display a *confirmed local receipt*. All previously visible publication pages, duplicate-candidate previews and revision-fenced selections are cleared. Verified source completeness and deduplicated global counts remain false/unknown.

For a worker timeout, error, interrupted response, mismatching receipt, or failed follow-up inspection, the graphical interface **does not claim success**. It clearly states that **zero, one, or two 64-record transactions may have committed**, consumes and removes the original approval, hides stale result and candidate pages, and requires an explicit **Inspect durable source/identity counts** before any new preparation offer may be made. This inspection uses an original read-only worker operation, returns aggregate counts, and **does not automatically offer or authorise the next batch**; its consent revision is never copied into the inspection-only display. A later fresh offer requires a distinct explicit action and confirmation.

No failure automatically retries a stored `ApplicationCommand`. On reopen, the researcher must reselect the project/run and explicitly inspect current durable evidence. PR85's original core service already rejects stale token replay and protects partial committed batches from reversal.

## Validation

`tests/test_gui_materialisation_window.py` uses a disposable versioned SQLite project containing 132 synthetic original PubMed/Web of Science source records. It checks:

1. Read-only preview, one-use host consent, two separate transactions, exactly 128 independent provisional identities, four remaining and original count/revision checking.
2. Failure injected during the **second** original transaction: the first 64 are committed and remain auditable; the graphical host reports unknown result, blocks further approval and requires read-only inspection before a fresh consent for the remaining 68.
3. A lost worker reply *after* both transactions commit: the host refuses success, does not replay the consumed consent and explicitly recovers the original 128 linked identities through fresh inspection.
4. Switching runs, cancellation of competing one- versus two-batch offers, source-free labels, action allowlisting and empty researcher confirmation refusal.

The four-platform core Python continuous integration (CI) checks (Python 3.12/3.13 on Windows and Linux), graphical lifecycle feasibility checks and any impacted performance tests must run on the exact PR commit. The existing 100,000-original-source production two-batch benchmark remains a separate, not GUI-rendering, performance gate.

## Outstanding acceptance boundaries

The interface is an **experimental** NiceGUI/pywebview feasibility project. This increment does not establish actual native Windows manual accessibility/usability, reliable full 100,000-row user-led materialisation, final verified publication counts, complete deduplication, source acquisition completeness, Excel master-row export or packaged Windows installation. No claim is made that a two-batch window solves the whole-project throughput cost. `global_unique_publications=null`, `deduplication_complete=false`, `source_retrieval_verified=false`, and `verified_complete=false` remain mandatory.

**Merge gate:** exact latest PR HEAD, all required test/benchmark jobs successful, definitive Codex **code review first**, then **security review** for that exact HEAD, resolved/dispositioned individual findings, and no outstanding product acceptance claims. Never merge without explicit project-owner authorisation.
