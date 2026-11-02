# Graphical feasibility evaluation — approval and dependency gate

Date: 2 November 2026. Issue #43 under #41 / #9. Baseline:
`aaaa533e74a0b2e3b0315ee9878910ac4a354662`, owner-merged pull request #44.
All four baseline post-merge configurations passed in run #41409722418.

## Approval decision

The project owner approved **NiceGUI 3.18.0 and pywebview 6.2.1 for an isolated,
version-pinned feasibility experiment** on 2 November 2026. The approval is
recorded in issue #43, comment #6572367860. This supersedes earlier statements
that prototype approval was outstanding in the dated
`GUI_DEPENDENCY_PROPOSAL.md` and earlier handover/comments.

Approval is not production adoption or merge authorization. No new scientific
scope, hosted service, graphical testing/packaging tool, model or credential
access is authorized here. Framework-required transitive Python packages are
resolved only within disposable evaluation environments; they are not added to
`pyproject.toml` or the core development requirements. The repository
`RESEARCH-Y_SPEC.md` remains unchanged. Relevant requirements: ARCH-01–04,
PROJ-01/07, UI-01/05/06/10, SEC-01–05 and AT-21/22.

## First executable gate

The separate **Graphical dependency feasibility** workflow creates a fresh
virtual environment on Windows/Linux with Python 3.12/3.13. It does not install
RESEARCH-Y or access project databases or provider credentials. The existing
four required core tests and their workflow remain unchanged.

1. Resolve exactly `nicegui[native]==3.18.0` and `pywebview==6.2.1` from the
   public Python Package Index (PyPI) using a pip installation report and
   `--dry-run --ignore-installed`. No automatic upgrade/substitution of the
   approved top-level candidates is permitted.
2. Validate the report version, target platform, top-level candidates, unique
   package identities, official archive origin and SHA-256 archive digests.
   Collect declared Python licences, dependency requirements and source-build
   flags. The initial resolution selects transitive versions; they are observed,
   not invented or claimed to have been pre-approved individually.
3. Check every selected archive against its exact PyPI release metadata and
   collect that release's vulnerability list. Missing/failed/malformed responses,
   yanked artifacts, mismatched hashes or reported findings block installation.
   The feed is release-specific, not the latest-version endpoint. Requests have
   finite timeouts, at most four concurrent lookups and no redirect/proxy fallback.
4. Generate a per-platform candidate requirements lock with exact versions and
   the observed archive hashes. Install using `--require-hashes` into the same
   isolated environment, run `pip check`, and compare installation coordinates,
   archive URLs/digests and installed package metadata to the resolution.
5. Import `nicegui` and `webview` without explicitly starting a web server or
   native window. Preserve evidence even when a later stage fails. Do not treat
   an earlier `ready_for_isolated_install` artifact as an installation pass.

The workflow uploads only dependency metadata, reports and the candidate text
lock. No wheels, source archives, fonts, licensed literature, research projects,
user environment dump or credentials are uploaded. Its permissions are read-only;
checkout credentials are not persisted. It has a 20-minute bound and fails rather
than ignoring a failing stage. The 256-package/16-MiB diagnostic input guards are
explicit refusal bounds for this developer probe, **not literature limits**.

## Meaning of a green result

`dependency_probe_passed_pending_review` establishes only this runner's observed
runtime artifact resolution, release-feed checks, matching installation and
imports. It explicitly leaves `gui_acceptance`, `production_adoption_approved`,
`complete_security_audit` and `complete_license_review` false.

Important open work:

- Source distributions may execute build-backend code during metadata resolution
  and installation. Their archive hashes are recorded, but separate build-time
  dependencies and resulting built-wheel reproducibility are **not** covered by
  the runtime lock. No claim of a fully locked supply chain is made.
- Declared licences are not a licence/legal approval. Embedded frontend bundles,
  native libraries, WebView2/.NET prerequisites and their licences/advisories need
  separate inventory and review. Empty vulnerability feeds do not prove safety.
- Resolver bootstrap tooling is the fresh interpreter's bundled pip, whose
  version is recorded. Repeated first-resolution runs can select different
  transitive versions. Review and retain the actual resulting platform locks
  before proposing production dependencies.
- Imports do not test rendering, local-only assets, origin/session authorization,
  browser actions, native file dialogs, responsiveness, shutdown or packaging.

## Next bounded experiment

After inspecting the actual four-platform dependency evidence, build the small
synthetic local graphical prototype under the approval above. It must test
explicit loopback binding, safe text, authenticated host/origin/session/request
boundaries, no broad file-serving routes, and Windows launch/close/worker cleanup.
Do not add another approval gate merely to start that already-approved prototype.
Report any genuinely new dependency or substantive design change separately.

Use the merged supervised worker and existing services rather than duplicating
count/export logic. Only after feasibility evidence supports it should the actual
new/open → explicit run selection → strategy/counts → workbook save/observe/recover
adapter be proposed for production adoption in a separately reviewed change.
Keep #43/#41 and broader product acceptance open. No automatic merge.

## Validation scope

The new offline tests exercise the probe with synthetic pip reports and release
responses: wrong pins, package collisions, unsafe origins, missing hashes,
withdrawn artifacts, unknown feeds, reported findings, exact installation
matching, source-build disclosures, command-line isolation and workflow policy.
They make no network requests and import neither graphical framework. Their
success is not a live dependency or native Windows result.

The local analysis container could not resolve github.com or pypi.org, so no
local installed-framework claim is made. The dedicated runner workflow supplies
that missing platform-specific evidence. Current commit checks and both exact-
commit independent reviews are required before any merge recommendation.

## Primary implementation references

- https://pip.pypa.io/en/stable/reference/installation-report/
- https://pip.pypa.io/en/stable/topics/secure-installs/
- https://docs.pypi.org/api/json/
- https://pywebview.flowrl.com/guide/security.html

A pip report is not itself a lock file. Hash checking binds archive bytes but does
not approve their safety or licences. Keep these qualifications with the evidence.
