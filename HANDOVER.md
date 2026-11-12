# RESEARCH-Y handover

## Phase 1 delivery

[Issue #105](https://github.com/studeployed/RESEARCH-Y/issues/105) tracks all six
roadmap units, existing evidence and remaining gates from main `cf331c2`.
The first retrieval regression concerns a reopened run missing an approved
source/group query. The run board now checks the frozen plan before reporting
enumeration or metadata coverage. See `docs/GUI_RUN_EXECUTION.md` and the
application-worker traceability table. Source-specific live evidence and
remaining product acceptance are tracked separately in #7, #8 and #9.

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
