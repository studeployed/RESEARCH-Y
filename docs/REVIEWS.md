# Local review record — 23 October 2026

**Review target:** `feat/project-storage-increment-1` (first Phase 1 increment); main baseline `5ea6d85ae6b6`. These reviews assess locally tested source, **not** independent human peer review.

## Code-quality review

- Scope adheres to `PROJ-02`, `PROJ-03` and initial `PROJ-04`; no connector, GUI or AI functionality is claimed.
- Manifest has an immutable Universally Unique Identifier (UUID), format version and no absolute paths. SQLite schema version is explicit and unsupported versions fail closed; migration/backup is a later task.
- `create_project` exclusively creates a new folder; detects collisions and removes partially initialised content after creation failure.
- `open_project` validates manifest syntax/identity and database identity; absence/corruption does not silently regenerate data.
- Theme/objectives update and audit event are in one SQLite transaction; injected audit failure rolls the update back.
- **Issue found and resolved:** database handles initially relied on SQLite context manager without explicit close. Updated all connections to explicit close, important for Windows file locking and folder relocation.
- **Remaining verification:** Windows CI; large-scale read/write performance; concurrent-writer locking beyond the single SQLite transaction is not yet designed/tested.

## Security review

- Manifest and directory-name handling block path separators, dot components and Windows device names; generated folder names are Windows-compatible.
- All project database writes use SQL parameters; a malicious-looking research theme is treated as data.
- Project open rejects a symbolic-link manifest/database; a missing database is never created by a read operation.
- No API credentials, network access, cloud processing, models or external source payloads occur in this increment.
- GitHub workflow has `contents: read` minimum privilege and no secrets; `.gitignore` excludes live project data and common secrets, but is not a security boundary.
- **Remaining verification:** archive import hostile-path checks, Windows access controls, secure credential store, external-source rate/terms handling and formal dependency scanning are future increments. No claim is made that these later SEC requirements are complete.

## Test evidence and limits

- Python 3.13.5 / Linux: **40 offline tests passed**, branch-inclusive coverage of `research_y` **96%**, warning-as-error ResourceWarnings: none.
- Source compile and requirements traceability checks pass.
- GitHub Actions remote run [40004516700](https://github.com/studeployed/RESEARCH-Y/actions/runs/40004516700): **all four matrix jobs passed**, verified from job logs (Linux/Windows, Python 3.12/3.13; **40 passed and 96% coverage in each**). Pull-request run [40004743754](https://github.com/studeployed/RESEARCH-Y/actions/runs/40004743754) also completed successfully. These are automated checks, not human peer review.
- PubMed / Web of Science: **not tested**; connectors do not exist yet.
- The shared local Python runner had an unrelated moviepy/pillow dependency conflict; clean GitHub Actions dependency consistency checks succeeded across the matrix.

## Review remediation — 24 October 2026

The requested Codex code review and separate security review on original head `437d6fce600f` identified three valid issues. These were not previously covered by the 40-test suite. All three findings have been corrected on the feature branch in `1777ba7163ba`:

1. **P1 — SQLite hot rollback-journal recovery:** project validation no longer opens a read-only database that cannot recover after a terminated write. A non-creating `mode=rw` connection permits SQLite rollback recovery before validating identity. New child-process crash fixture creates a real hot journal and verifies preservation of previously committed data and subsequent updates.
2. **P2 — directory named `project.ryproj`:** open distinguishes supplied file from directory before stripping the manifest filename. New regression test covers new/open/by-manifest and data update for the ambiguous name.
3. **P3 — security, validation/write handle swap:** validation and subsequent read/write now use a single bound SQLite connection, eliminating the second-open race. Two deterministic regression tests simulate replaced connections and verify that a different project's values are not modified.

Original inline threads were replied to with evidence and marked resolved after successful cross-platform checks. A fresh code and security review on the corrected implementation was requested; **pending at the time of this documentation entry**. The closed discussions are not a claim of zero remaining vulnerabilities.

**Verified tests on corrected code:** local Python 3.13.5/Linux, 44 passed with ResourceWarnings treated as errors, 95% branch-aware coverage. GitHub Actions [pull-request run 40081458246](https://github.com/studeployed/RESEARCH-Y/actions/runs/40081458246) reports success for Windows and Linux with Python 3.12 and 3.13; logs in each environment show **44 passed and 95% coverage**. No live-source or full Windows installer tests have yet been performed.

**Merge policy:** maintain the unmerged PR until renewed reviews are checked and the project owner explicitly authorises merge.

## P1-02a — Schema migration review (24 October 2026)

**Scope:** Schema-v2 table definitions and transactional version-1 upgrade. No API integrations, imports, external dependencies, GUI or release.

- **Correctness:** separate publications from source retrievals and preserve multiple group/source memberships; foreign keys prevent cross-run and cross-provider membership errors. Exact source queries and reported counts have nullable, unexecuted initial states. Approved strategy versions/groups and audit history reject update/delete.
- **Recovery:** existing version-1 identity is validated first; a SQLite backup is completed and checked before DDL. Migration uses individual SQL executions within `BEGIN IMMEDIATE` and atomically commits schema number and audit event. Failure rolls back all new tables and leaves a valid pre-upgrade snapshot.
- **Security:** no credentials or licensed data added. SQL is static or parameterised. This change does not alter previously documented Windows-junction trust boundaries; tracked issue #11 remains separate.
- **Evidence:** local Python 3.13.5 / Linux: 53 tests passed, 93% branch-aware coverage; Python compile and mapping verification passed. Cross-platform GitHub Actions runs must be checked after branch publication. Shared local runner has an unrelated installed moviepy/pillow conflict; a clean CI runner provides package-integrity evidence.
- **Limits:** schema creation alone does not implement deduplication, source count reconciliation, immutable run write APIs, archive import, or final AT-01…AT-22. This PR is only the first increment of issue #5.

## P1-02b initial self-review — 24 October 2026

- **Scope:** Version-2 storage methods for researcher-approved OR-only atomic terms, immutable strategy versions, pending runs and planned (not executed) source queries. No SQL schema changes or new dependencies.
- **Scientific correctness:** unapproved atomic terms and missing approval confirmation are rejected; accepted term origin, rationale, enabled state and group order persist. The application itself does not yet verify that a UI really obtained approval. Pending queries never create provider counts or imply execution.
- **Integrity:** one transaction contains each write and its append-only audit event; version numbering is allocated under `BEGIN IMMEDIATE`; source queries can only refer to a group in their run's frozen strategy; failed audit inserts roll back.
- **Security:** all database writes use static parameterised SQL. Untrusted query strings are stored as data only; no executing SQL, source network calls or credentials. Previously tracked Windows junction issue #11 remains deferred to project import work.
- **Test plan:** persistent reopen/relocation, immutable versions, cross-version group rejection, unapproved proposals, invalid JSON values, unknown source counts, audit failure/rollback, Windows/Linux compatibility. CI evidence must be recorded after the branch is published. This is assistant self-review, not an external sign-off.

## P1-02b GitHub Actions evidence — 24 October 2026

- Code-bearing PR #13 head `1aed8dee684d`, [push workflow 40096279206](https://github.com/studeployed/RESEARCH-Y/actions/runs/40096279206): successful in all four jobs (Windows/Linux, Python 3.12 and Python 3.13).
- Actual job logs each report **74 tests passed, 93% branch-inclusive code coverage**, successful requirement-to-test mapping, source compilation, dependency installation and dependency consistency.
- This evidence validates tested persistence behaviour but does **not** demonstrate completed source retrieval, full study-count reconciliation, provider syntax validation, end-user GUI or all mandatory acceptance tests.
- Codex code/security reviews and any final documentation-only commit CI must be inspected independently before a merge recommendation.

## P1-03a offline compiler initial review — 24 October 2026

- **Scope:** Python-only, deterministic broad-OR compiler; no network, credentials, source API calls, backend mutation or new dependency.
- **Method:** atomic approved literals are quoted and joined by OR at both group and global levels; PubMed uses `[All Fields]`, WoS Starter uses `TS`. Field coverage limitations and non-full-text status are disclosed. Excluded/draft terms never silently enter a query.
- **Accuracy limitations:** PubMed phrase-index fallback and exact accepted translation, and authorised WoS Starter API parsing, require separate real-source verification. These are explicitly documented unresolved acceptance gates, not claimed successes.
- **Robustness:** explicit invalid-syntax rejection, optional provider-verified UTF-8 query-size bounds, never-truncated partition chunks, correct group provenance and no fabricated hit counts. Chunk counts must be reconciled via provider identifiers, not summed.
- **Tests:** 39 pure offline tests passed Python 3.13.5/Linux; source compilation successful. Full Windows/Linux GitHub Actions is currently blocked by existing pre-runner setup failures on `main` (issue #14); do not claim cross-platform verification before actual jobs run.
- **Further scope:** request code/security review on new PR, resolve material compiler defects within this increment, then return to provider connectors rather than unrelated hardening loops.

## Public-repository governance and CI event optimisation — 24 October 2026

The repository is now public, with a verified ruleset protecting `main`. Four required GitHub Actions jobs must pass, and review threads must be resolved. After PR #15 merged, PR #16 was brought up to date with the current `main` branch without dropping compiler code or documentation.

This increment changes only GitHub Actions triggers from redundant feature-branch push plus pull-request runs to:
- `push` on `main` after merge;
- `pull_request` targeting `main` before merge;
- explicit `workflow_dispatch` for manual runs.

The workflow's permissions, job identifiers, Windows/Linux matrix, Python versions and test commands remain the same. `tests/test_ci_workflow.py` guards the intended triggers and check identifiers. The PR must pass the actual four required checks and receive code/security review before owner merge approval.

## P1-03b — PubMed count/translation source-probe review (24 October 2026)

- **Scope:** A single-source PubMed ESearch count-only client, strict parser,
  conservative translation review flags and an optional manually invoked smoke
  command. No network requests run in normal CI, no ID retrieval, no source-run
  status transition, no database-schema changes or new runtime dependencies.
- **Scientific integrity:** provider-reported `count=0` is distinguishable
  from an absent/error count; warnings, changed translations, MeSH and
  unintended AND/NOT semantics are surfaced. Split-group provider counts
  cannot be summed as a deduplicated union.
- **Security:** fixed HTTPS provider endpoint, POST request body (rather than
  URL query secrets), private runtime contact settings, sanitised provider
  failures and no API key in results or logs. Pacing defaults below 3/s.
- **Local evidence:** 38 synthetic fixture tests passed on Python 3.13.5/Linux,
  90% branch-aware coverage of the new probe module. Smoke CLI refuses to make
  any network request without an explicitly configured contact email.
- **Outstanding:** real PubMed API acceptance/translated query validation and
  fully integrated source job state are unverified. Windows/Linux CI and
  code/security review must be checked against this exact feature head before
  a merge recommendation. Previously deferred Windows junction issue #11
  remains unrelated to this source-probe increment.

### Network redirect review remediation — 24 October 2026

Codex identified a genuine P2 issue in the first P1-03b commit: Python's
default urllib opener could follow redirects to external/HTTP locations.
The transport now installs an explicit redirect-rejecting handler. HTTP 3xx
raises a sanitised `PubMedProbeError`; a 302 is not automatically retried.
A deterministic regression fixture asserts no cross-origin, downgrade or
alternate-path redirect can be followed. The transport's fixed official
ESearch URL and no-credential-in-URL policy remain unchanged. Additional
integrated strategy-compiler-to-ESearch tests were added, independent of live
source verification. This is in-scope security remediation, not new
architecture or a change to the scientific specification.
