# RESEARCH-Y handover

## Windows usability

Version 0.1.5 enables native text selection, keeps project navigation and the next step visible during scrolling, and distinguishes routine guidance, warnings, errors and results. Acronyms have hover help. The owner approved presenting the existing seven audited items as plain-language Search checks. Group and term entry accepts Enter, retains failed entries and restores focus after adding a term. The explicitly entered researcher name is retained in the existing project audit and reused after approval and reopening. Self-checks offer that saved name and an explicit choice of another reviewer.

Regression coverage includes researcher persistence and concurrent name changes, legacy projects, keyboard entry and duplicate recovery, narrow and wide sticky navigation, and the installed Windows lifecycle. The checklist retains its existing record and source-confirmation semantics.

## Question feedback and search milestones

Version 0.1.4 confirms a project question save inline and returns to a read-only summary. Edit question restores the form. Failed saves retain the entered text. Plan search tracks the current draft. Run search tracks a selected saved plan and its first recorded collection response separately from pilots. The Windows lifecycle fixture exercises validation, saving, editing and reopening. No provider requests are needed for these checks.

## Simplified Windows project workspace

Version 0.1.3 centres the work area and gives the research question and terms separate columns on wide windows. Plan search, Run search, Results and Export show the actions for each stage. Saved runs use short names in the daily workflow. Project details retains identifiers and audit history. The Windows lifecycle check covers responsive buttons and fields, switching stages with an unsaved theme, explicit run selection and workbook verification.

## Windows forms and first-search guide

Version 0.1.2 places field labels above their editors and lets them wrap as the window narrows. **How to use RESEARCH-Y** opens the packaged first-search guide from the home screen. The native lifecycle check opens the guide and measures populated, focused and empty Research Setup fields at two window widths.

## Windows project picker

In 0.1.0, starting the packaged launcher without `HOMEPATH` reproduced a
folder picker that never appeared. The Windows backend accessed that variable
when no starting directory was supplied. An exception in the native process
left the app waiting for a reply and holding its action lock. Version 0.1.1
supplies an existing starting directory and returns a failure to the launcher
if the native call raises. The installer test drives the packaged launcher
with `HOMEPATH` absent, cancels the first picker, creates a project and opens
a different project by selecting its folder.

## Initial release verification

[Issue #163](https://github.com/studeployed/RESEARCH-Y/issues/163) tracks the
product requirements that remained partial after Phase 3. The Windows launcher
accepts the project index as well as its folder. The project storage evidence
for PROJ-01 through PROJ-06 is in the [requirement register](docs/requirements-traceability.csv).
The launcher now shows the most recent successful source checkpoint across the
project. The selected run shows source and group counts, society coverage,
supplementary imports and the global total supported by a current acceptance receipt.
The master workbook includes those denominators even for a filtered export.
Record detail retains original and researcher-chosen citations separately and can
request a DOI lookup for a missing abstract. The export dialog lets researchers
choose which sources permit sharing abstract text. Each RIS bibliography has an
accompanying JSON scope receipt, including an empty selection.

Open **Review queues** under the selected run to inspect conflicting source
tags, citation differences, missing abstracts or incomplete conference
extraction. Society follow-up covers the project directory and links to the
original visits. Reviewing a citation preserves the source values and records
the researcher's reason. A changed publication can require review again.
Researchers can inspect the project audit while a pilot request is running
and edit their draft during inference. A late response for a removed seed
cannot add suggestions to the revised draft.

The Windows workflow rehearses both a clean install and an upgrade of a project
written by the Phase 3 build. The release register maps all 117 product requirements
and 22 acceptance scenarios to verification evidence. Issue #163 records the
Windows installer verification for the final merged commit.

Research Setup defaults to PubMed and Web of Science with unrestricted
publication dates. Researchers can select a database, an optional publication
year and a smaller query byte limit. Each executable OR chunk is previewed
and stored separately. A single-database run leaves mandatory primary coverage
incomplete. Reopen the selected run's pre-run verification after a pilot to
see counts and estimated pages for each exact query. Record a known item's
observed outcome, date and evidence there. Both workbook formats preserve
the check and any subsequent correction. The publication-year limit uses
the sources' publication date fields. [PubMed date searching](https://pubmed.ncbi.nlm.nih.gov/help/#searching-by-date)
and [Web of Science Starter field tags](https://github.com/clarivate/wosstarter_python_client/blob/master/docs/DocumentsApi.md).

In duplicate review, each possible move shows which citation choices and
specialist links would follow the original. A previously selected destination
value takes precedence. Classifications and documents remain attributed to
the publication where the researcher recorded them. When its last original
moves, the receiving publication's source detail links to that earlier
evidence. Reversing the move restores the source and its eligible field
choices and specialist links in one project transaction.

The run comparison shows classifications attached to recurring source records,
including the earlier researcher, decision and rationale. When the later run
has a separate publication identity, a researcher can verify the evidence and
record a new decision linked to the earlier one. Changed evidence or an edited
decision requires reopening the comparison. The summary separates shared
publication identities, recurring sources and unresolved splits or associations.

The native launcher provides access to Windows Credential Manager and an
explicit PubMed connection check. The test uses a public fixed query and the
existing paced client. A project-level provider pause also applies to the test.
The launch screen explains saved credential errors, quota holds and recovery.

New source receipts preserve the API operation, application version, HTTP
client identifier and the local time with UTC offset. Both spreadsheet exports
and the selected run show the versions used at execution. Earlier source
receipts without this evidence retain their original unknown status.

The execution monitor shows all nine processing stages with their own units.
The retry counts distinguish PubMed sessions restarted after failure from
Starter page attempts repeated after failure or abandonment.

## Phase 3 delivery

See the [release matrix](docs/PHASE3_ACCEPTANCE.md) for all 22 scenarios,
the [installation guide](docs/WINDOWS_INSTALLER.md) for the Windows build
and [desktop guide](docs/DESKTOP.md) for researcher workflows. The full
master workbook can record a researcher-verified complete scope once all
mandatory retrievals and the retained identity union have reconciled.
The project diagnostic is a separate local JSON export with fixed fields.

Issue [#11](https://github.com/studeployed/RESEARCH-Y/issues/11) covers
Windows project containment. The desktop lifecycle check chooses a folder
with a redirected data directory, verifies that the current project stays
selected, then opens, saves and relocates an ordinary project. The storage
tests compare the independent project's metadata and audit history.

[Issue #142](https://github.com/studeployed/RESEARCH-Y/issues/142) tracks
the three approved Phase 3 units. The [portable project workflow](docs/PROJECT_ARCHIVES.md)
includes a Windows restore action, a consistent database snapshot and selected
supporting files. The archive tests restore a reviewed project, compare every
database table and independently read a linked document. They also check a
concurrent SQLite writer and interruption before publication.

## Phase 2 delivery

The [Phase 2 acceptance record](docs/PHASE2_ACCEPTANCE.md) links the eight
roadmap scenarios to the researcher workflows, tests and review records.

The combined specialist acceptance case is in `tests/test_phase2_acceptance.py`.
It begins with a reviewed two-publication primary master, then admits two
separately located conference abstracts and an official society-only guideline.
After reopen, the five publications can be inspected independently, while
the reviewed primary count and workbook still cover the original two. The
supplementary sources retain separate denominators and source-backed names
and classification evidence. See `docs/CONFERENCE_EXTRACTION.md`,
`docs/SOCIETY_SOURCES.md` and `docs/CROSSREF_ENRICHMENT.md`.

[Issue #121](https://github.com/studeployed/RESEARCH-Y/issues/121) tracks
the four specialist-processing milestones. The first P2-01 increment adds a
[biomedical benchmark](docs/BIOMEDICAL_BENCHMARK.md) with blind prompts,
versioned answers and per-dimension scoring. Model evaluation and the
researcher approval flow have separate evidence under issue #122.

## Phase 1 delivery

Use the [Phase 1 acceptance record](docs/PHASE1_ACCEPTANCE.md) for
the completed six-unit core gate, native Windows evidence, live source
limits and the distinction between publication and membership counts.
The additional live Web of Science cross-day observation is tracked in
[issue #119](https://github.com/studeployed/RESEARCH-Y/issues/119).

Issue #9 adds a reviewed master count and an explicitly selected,
versioned workbook when the retained original records are fully distinguished
by current researcher decisions. The ordinary strategy-only workbook and its
existing journal receipts remain readable. See `docs/DESKTOP.md` and
`tests/test_reviewed_master.py` for the two-source acceptance case.

The owner approved optional Windows desktop adoption on 12 November. The
normal installed entry point is `research-y`. Its ordinary local session
shares project operations with the isolated harness and starts with an empty
selection. See `docs/DESKTOP.md` for source settings and the dedicated native
two-process acceptance test.

[Issue #105](https://github.com/studeployed/RESEARCH-Y/issues/105) records the
six roadmap units and their closeout evidence from baseline `cf331c2`.
The first retrieval regression concerns a reopened run missing an approved
source/group query. The run board now checks the frozen plan before reporting
enumeration or metadata coverage. See `docs/GUI_RUN_EXECUTION.md` and the
application-worker traceability table. The scope of the completed source
and workbook tests is recorded in #7, #8 and #9.

Merged PR #107 exercises a complete **offline** two-provider
path. A synthetic PubMed journal citation and book contribution survive
metadata recovery, and a saved Starter job must supply its independent
verification/final-count observations. A reopened project with three source
records in two groups yields two reviewed/provisional identities after an
explicit match and preserves six original query memberships in an audited
XLSX. This provides scoped AT-08/09/10/18 evidence. Live quota behaviour,
production Windows launch and full scientific acceptance remain separate.

The PubMed metadata recovery change for #7 checks the saved EFetch evidence
before counting a checkpointed record as acquired. The regression covers
altered source, receipt digest, timestamp, rights and abstract availability
after reopen, plus reuse of an original record across two distinct responses.
See `docs/PUBMED_EFETCH.md` and the application-worker traceability table.

Issue #104 connects consent preview, explicit confirmation and durable receipt
history to the guarded graphical prototype. The two synthetic lifecycle cases
`manifest_consent` and `manifest_reopen` use separate host processes on the same
project. Verify their Linux loopback and native Windows results on the PR.
Consent alone leaves the exports directory untouched. Optional dependency
adoption for an operational Windows launcher is tracked separately under #43.

The follow-up save action runs staging and guarded publication under the
original consent in a supervised worker. The graphical `manifest_publish`
fixture reopens a separate process, selects the saved consent, saves and
inspects its receipt, and independently opens the resulting workbook.

## Current work — P1-06l8, issue #102

PR #100 merged at `c5a6f1c` and PR #101 at `d018726`. Issue #102 extends the trusted worker with
whole-run preview, explicit researcher consent and consent-receipt inspection.
Use the selected revision and retain the export UUID across retries. Check the
issue's PR for CI and commit-specific review evidence. The next application
step is to present the preview and confirmation through a trusted host control.
See `docs/APPLICATION_WORKER.md` for the command arguments and receipt states.

## P1-06l6, issue #39

PR #99 merged at `2ab1d0c2809b63ff737e1bdaeb055cf13c21cb07`.
The next recovery increment exercises six abrupt process exits during provisional
workbook publication. All 55 publication-results tests passed locally on Windows
with Python 3.12. See `docs/PROVISIONAL_MANIFEST_PUBLICATION.md` for the
boundaries and `docs/provisional-manifest-publication-traceability.csv` for the
mapping. Consult the PR for current CI, review receipts and merge status.
The next application integration step is read-only inspection of a selected
export through the supervised worker.

## Historical handover — PR #42

## Authority and baseline

The repository RESEARCH-Y_SPEC.md version 1.0.0-draft.1 remains authoritative and
unchanged. Independent Python implementation; no imported project assumptions.
Owner-merged PR #42 is bc4666fa7aaefe8082ad7ea21a1918f0ac4187f1, merged on
1 November 2026 at 22:41 Coordinated Universal Time (UTC). Its post-merge run is
#41358424799; retrieve current outcomes rather than inheriting older status claims.

Standing owner direction: start the next ready approved task at each completion,
without another routine go. This does not authorise automatic merges, substantive
scope/dependency changes, waived gates, live retention consent or asynchronous
monitoring promises.

## Current increment — P1-06e2a, parent #43 / #41 / #9

Read docs/APPLICATION_WORKER.md and docs/application-worker-traceability.csv.
application_commands.py allowlists six existing inspection/export services using
an already-opened expected project identity. application_worker.py runs one task
per explicitly spawned child with a supervisor thread and a fresh private pipe.
Conflicts are refused; in-flight identical commands coalesce. Public terminal status
and readiness for a fresh submission now both wait for supervisor exit, correcting
the initial review's stale-result race. Six regressions were added and the integration
helper no longer joins a private thread before submitting the next operation. Real service work
runs off the future interface event loop. This is NOT a GUI, launcher or installer.

Operation identity is ephemeral. Export identity remains caller-supplied and
journal-backed. Returned means a service returned, not that a search/export passed.
Shutdown can interrupt but never fabricates cancellation or completion. Only a
committed preparation receipt is a durable export request; restart reconciliation
uses the existing validated inventory. Parent-death watching, bounded stop/escalation,
reaping and explicit shutdown_unconfirmed are implemented. No reusable broken pipe,
second persistent queue or unbounded operation backlog is introduced.

Local Linux/Python 3.13.5: 89 targeted lifecycle/command cases passed, 93% rounded
combined branch-aware coverage. Real processes/pipe/parent-death tests use synthetic
service functions; routing tests substitute service boundaries. Fifteen actual
project/workbook integration cases are committed for the full repository checks,
not claimed locally executed. Full checkout download failed because local DNS could
not resolve github.com. No native Windows or graphical acceptance is inferred.

No dependency, workflow, database schema, source query, credential or specification
change. The 32 MiB worker response bound fails explicitly without truncation; it does
not change retrieval or workbook limits. Commands contain transient host paths and
must never be exposed as a browser API. Future renderer/session/origin/path selection
safeguards are still required. A Python watchdog is not a hostile-native-code sandbox.

## Next step already advanced

Read docs/GUI_DEPENDENCY_PROPOSAL.md. Live upstream release checks identify NiceGUI
3.18.0 and pywebview 6.2.1 as evaluation candidates. Their declared dependencies,
licences, native prerequisites and relevant upstream security fixes were inspected.
No dependency resolution, installed vulnerability audit, browser/native prototype or
packaging test is claimed. No GUI dependency is adopted.

Obtain owner approval for a pinned isolated feasibility prototype, resolve/audit the
full graph and frontend assets, then propose the graphical dependencies and thin
adapter in a reviewed PR. Bind loopback explicitly, disable reload/remote sharing,
use trusted native path selection, validate every request/socket/session boundary
and render project/source text as plain data. Test actual Windows launch/close and
server/worker cleanup. Do not keep fragmenting dependency-free infrastructure once
these dependency gates are satisfied. #43/#41 remain open.

## Preserve existing guarantees and limits

Read docs/APPLICATION_INSPECTION.md, docs/WORKBOOK_PUBLICATION.md,
docs/WINDOWS_EXPORT_GUARD.md, docs/STRATEGY_WORKBOOK.md and their traceability files.
The merged read model captures one consistent project/run/export snapshot; inventory
never establishes live-worker or current-file success. File observation checks the
retained original and output without repairing history. A last audit event is NOT
a source checkpoint. Unknown counts are not zero; group sums are not global unions.

Export saving preserves immutable original reports and independent original bytes,
append-only receipts and no-overwrite publication. Visible files and database commits
are separate; an unreceipted output requires validated recovery. No destructive cleanup,
universal power-loss guarantee or hostile same-account sandbox. Existing 128 MiB
workbook bound, filename/local-filesystem restrictions and Windows reparse limitations
remain. Broader archive security #11 is open.

PubMed run #41235232458 observed 19,483 identifiers, 43 pages, six disjoint leaves and
controlled restart; full metadata/broader live acceptance remain partial. Starter run
#41306953908 observed 19,584 reported/committed records, 392 acquisition and 392
verification pages, 786 requests and a separate-process restart. Neither a frozen
provider snapshot nor complete abstracts/live multi-day recovery is inferred. Keep
#7/#8 open; never repeat live calls merely for documentation or request secrets in chat.

Keep #33/#35/#37 open for project-wide duplicate discovery/scaling, broader reconciled
counts and full exports. Manual candidate review's 2–32-record limit is not an
acquisition limit. Preserve transactional creation, recoverable schema-v4 migrations,
immutable source metadata/plans, all memberships, fencing, retry budgets and provider-
wide longest cooldowns. Local request budgets pause rather than consume failure
budgets. Final Starter verification still needs an uninterrupted available-quota session.

## Reviews

**P1-06l7, prepared independently from merged PR #99:** trusted hosts can
inspect one known provisional workbook export through the supervised worker.
Interrupted and missing-file observations leave the project available for
explicit recovery. Windows Python 3.12 passed 241 command and worker integration
tests. See the P1-06l7 PR for cross-platform CI and matching review receipts.
The next host-facing write step needs explicit researcher consent tied to the
selected run, destination and current revision as specified in the export contract.

Before merge advice retrieve current HEAD, all four required continuous integration
(CI) results, code/security summaries, completion timestamps, matching individual
receipts and outstanding findings. Definitive exact-HEAD code review first; then
security unless valid automatic review already exists. No duplicate running reviews,
reaction-based acceptance, waived gates or automatic merges. Every new commit invalidates
earlier acceptance. Report the verified state without promising asynchronous work.
