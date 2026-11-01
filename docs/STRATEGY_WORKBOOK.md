# P1-06d, first increment: frozen strategy/count inputs and Excel rendering

Parent #37 / #9. Baseline: merged PR #36, commit
`9a91e905a40a89c86193d68677f2f95cfb4bf7b5`. The approved specification is unchanged.

## Implemented contract

`capture_strategy_report(project, run_id)` uses the existing validated read-only
connection and count projection on **one read transaction**. Approved strategy,
indexed group labels, source queries/parameters, stored timestamps, PubMed partition
count-plan nodes, named denominators and warnings belong to the same snapshot.
No second count connection, new query compilation, source request, database migration,
identity change or completion-state write occurs. Unknown values do not become zero.
Filtered scopes and unreviewed parameter keys fail closed rather than being ignored.

`StrategyReport` retains canonical immutable JavaScript Object Notation (JSON) text;
`as_dict()` returns a fresh copy. Secure Hash Algorithm 256-bit (SHA-256) binds that
text. The count projection's own revision and software/report method versions remain
visible. This freezes the **current** identity interpretation of an existing run;
it is not a reconstruction of the run's original historical publication identities,
a digital signature, validated deduplication, source acceptance or export permission.

`render_strategy_workbook(report)` returns genuine `.xlsx` bytes. It does NOT save a
user-selected file, append a database export receipt, publish an artifact, or expose
a graphical export action. The backend can use temporary files internally. A caller
must not report successful audited export merely because rendering returned bytes.
This split keeps the mixed database/filesystem transaction and recovery problem out
of a renderer change; the next increment must implement that missing contract.

## Workbook contents

Search Summary; Source Totals; Publication Counts; Run Totals; Search Terms;
Executed Queries; Query Partitions; Warnings; Methods; Report Snapshot; and Text
Continuations when necessary. Every sheet prominently states **INCOMPLETE**. The
workbook distinguishes retrieved identifiers from saved metadata, group identity sums
from global unions, provisional identities from unknown verified-publication totals,
and unplanned or unknown searches from actual zero-hit observations.

Stored timestamps are labelled as stored evidence, not independent verification of
requests. Split-plan internal nodes are not additional independent searches. Accepted
query translations and complete request logs remain in the project, not this bounded
workbook. Original approved term text, origin, enabled state and rationale are retained;
unavailable ancestry of term suggestions is not invented. Unimplemented master-results,
conference and society worksheets are disclosed rather than presented as empty results.

Only source/user strategy text and aggregate/local-identifier evidence enter this
report. Original provider records, titles, abstracts, document links, candidate actor
and evidence text, credentials and arbitrary query parameter objects are not copied.
Researcher-entered labels/rationales remain researcher text: the application cannot
prove that a user has not typed a secret into an ordinary text field.

## Spreadsheet safety and limits

All text is explicitly typed as literal text, including strings beginning with `=`,
`+`, `-`, `@`, tabs, line breaks or spreadsheet-error-like text. No formulas, macros,
external connections or external hyperlinks are generated. Fixed internal navigation
links point to the Methods sheet. XML-incompatible text is refused, not silently
removed. Integers with more than 15 digits are stored as exact text rather than
rounded spreadsheet numbers.

Long strings are divided into ordered chunks of at most 30,000 UTF-16 code units.
Main cells reference Text Continuations; each continuation records the original cell,
part number/count and full text hash. Concatenate parts without separators to recover
the exact string. Report Snapshot contains all canonical input chunks and their hash.
No query, term or rationale is silently truncated. Row/column overflow explicitly
refuses rendering; automatic multi-sheet row overflow remains future work. The 64 MiB
report-input bound is an explicit internal safety limit, NOT a source acquisition cap.

The workbook uses readable headings, alternating rows, wrapped literal text, frozen
headers, filters, defined numeric formatting and landscape print headers. These are
internal report renderings, not a certification of Preferred Reporting Items for
Systematic Reviews and Meta-Analyses literature search extension (PRISMA-S) compliance
or Peer Review of Electronic Search Strategies (PRESS) peer-review completion.

## Dependency proposal

The approved architecture names openpyxl or an equivalent. This branch proposes
`openpyxl==3.1.5` and its `et-xmlfile==2.0.0` dependency as the optional `excel` extra;
the core runtime's `dependencies=[]` remains unchanged. Imports are lazy and an
absent backend produces an explicit feature-unavailable error. The test environment
installs the same pins so rendering tests run rather than skip. Adoption is part of
the owner's review/approval of this PR; no dependency has been activated on main by
opening it. No new external service or paid subscription is introduced.

This renderer only writes new workbooks. It does not load untrusted Excel files;
future spreadsheet import would require a separate threat model, parser protections
and validation. Do not infer safe untrusted-file import from renderer testing.

Primary documentation checked 1 November 2026:
- https://pypi.org/project/openpyxl/3.1.5/
- https://pypi.org/project/et-xmlfile/2.0.0/
- https://openpyxl.readthedocs.io/en/stable/
- https://openpyxl.readthedocs.io/en/3.1.2/_modules/openpyxl/cell/cell.html

## Verification and traceability

`tests/test_strategy_workbook.py`: literal type and exact-text round trips; real
workbook parts/sheets/filters/frozen panes/internal links; unknown/zero and large
integers; lossless long Unicode queries/snapshot reconstruction; invalid text and
bounds; optional-backend absence; immutable inputs and render failure boundaries.

`tests/test_strategy_report.py`: actual repository project/storage/count integration,
approved terms, two-source/two-group identity unions, missing metadata despite
identifier retrieval, parameter-policy refusal, read-only state preservation,
concurrent writer during capture, relocation, corrupted/unsupported input and exact
partition text. These integration tests require the repository modules and are not
claimed locally passed merely because the independent renderer tests pass.

Scoped mappings are in `docs/export-renderer-traceability.csv`, supplementing the
existing master matrix. They do not promote product-wide export or release acceptance.
The first local run passed 48 renderer/contract tests on Linux Python 3.13.5; renderer
branch-aware coverage was 98%, combined new-module coverage 81% because capture needs
the full repository. A full checkout was unavailable locally; complete Windows/Linux
Python 3.12/3.13 continuous integration is the integration gate. Review current-commit
results, not these initial local figures, before merge advice.

## Immediate next increment: audited file publication and recovery

Before any user-facing successful Export action:
1. Define an append-only prepared/published/failure receipt contract binding project,
   report snapshot/hash, renderer version, artifact hash and destination identity.
2. Stage complete bytes, validate them, and publish without overwriting existing files.
   A database commit and filesystem publication are not one atomic transaction:
   interrupted intermediate states need explicit recovery, not an assumed success.
3. Test permission/disk errors, cancellation, audit failure, abrupt process death,
   idempotent retry, destination replacement, Windows reparse/junction paths, and
   another concurrent export. Never overwrite or delete unrelated files during cleanup.
4. Preserve the old frozen report when research data changes. Reopening/recovery must
   use the retained snapshot, not silently regenerate a different report under its ID.

Keep #37 open. Full master/bibliographic exports, historical report comparisons,
exhaustive duplicate discovery (#33), source acceptance (#7/#8), count acceptance
(#35), and the Windows junction release blocker (#11) remain open. The minimal
application shell follows the usable, audited export increment, not a renderer alone.
