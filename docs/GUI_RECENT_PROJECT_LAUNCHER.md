# P1-06e2j — Recent Projects: local, explicit and verified reopening

Date: 2 November 2026. Parent issues #43 / #41 / #9. Baseline:
owner-merged pull request #53 at commit
`c167f280bd98a94618029fbfaa250d9d0e791741`.

This is a **bounded, isolated graphical feasibility increment** against the
authoritative repository `RESEARCH-Y_SPEC.md`. Requirements PROJ-01,
PROJ-03/04/06/07, UI-01/10, ARCH-01/02/04, SEC-04/05 and AT-19/21 apply.
NiceGUI 3.18.0 and pywebview 6.2.1 remain isolated experimental dependencies,
**not approved production dependencies**. No scientific search logic, provider
access, credential handling, research schema or specification change is
authorised or introduced.

## What is implemented

- The local launcher now offers a **Recent Projects** list in authenticated
  local browser and Windows native-window modes. Each item shows the
  researcher's stored project name and location, with an **Open recent**
  control. It does not auto-open a prior project or implicitly select its
  latest search run or export. A separate refresh control re-reads the private
  index without searching the filesystem.
- Successful real project creation or opening registers the canonical
  project universally unique identifier (UUID), display name and currently
  verified path in a private, bounded **launcher metadata index** outside
  research project directories. Reopening a moved project through the trusted
  native folder selector updates its single UUID-keyed entry rather than
  creating duplicates. The list retains at most 12 recently selected
  projects. An item is an **advisory location**, not proof of availability.
- Index persistence uses Python's built-in SQLite transaction and
  `BEGIN IMMEDIATE` writer serialisation. It is **not** a second research
  data store: no source records, queries, abstract contents, search results,
  export bytes, passwords or tokens are stored. The authoritative project
  SQLite database remains unchanged and self-contained. On Windows the
  experimental default index is under the user's local application-data
  directory, and the disposable graphical test runner instead supplies a
  private temporary parent shared between its restarted GUI instances.
- A browser click supplies **only the UUID of a currently stored item**.
  The trusted host independently retrieves its path from the private index,
  rechecks the complete directory chain against junctions, symbolic links
  and reparse points, calls the real `open_project` service, compares the
  actual immutable UUID, then performs a supervised candidate inspection
  before switching active project state. Neither arbitrary browser paths nor
  a forged UUID can redirect the host to a different project.
- Missing, relocated, tampered, malformed, incompatible or unopenable
  entries produce static negative results. The active project, run, export,
  retained report and research data remain unchanged. The researcher can
  reselect the moved directory with the native picker. **No automatic
  filesystem scan or destructive cleanup** takes place.
- A corrupt, wrong-version, linked or otherwise unsafe launcher index is
  reported as unavailable, not silently reset. Valid research project
  operations remain usable independently, while the index error remains
  visible. Recent selections never report the scientific search as
  complete or a workbook as verified without independent observation.

## Boundaries, security and acceptance

The private index stores **local absolute project paths**, so it is
sensitive launcher metadata. Keep it in a private user-controlled local
directory; it is not uploaded as a test artifact, embedded in `.researchy`
archives, transmitted to providers or exposed through an arbitrary
download/API path. Authenticated UI labels may display paths to the local
researcher. Catalog format/version, file type, size and path are checked
before use, but hostile processes running as the same local operating-system
user are outside the application sandbox threat model.

Disk-backed tests verify empty and initial indexes, explicit restart
selection, moved-project re-registration, wrong identity, forged UUID,
corrupted index retention, linked database rejection, unknown index version,
bounded capacity and concurrent writer serialisation. The graphical
lifecycle matrix also exercises a **fresh real GUI process** which cannot
open its intentionally nonexistent launcher-selected root; the only way to
reopen the original project/run and independently observe its already
audited workbook is through the Recent Projects button and the preserved
host-only UUID entry. This is tested on authenticated Linux local transport
and on real Windows native-window button interactions with Python 3.12 and
3.13, retaining every preceding worker-death and workbook-recovery case.

The physical Windows native *folder picker* is still not operated by these
automated tests; that is a distinct manual test target. A bundled installer,
native prerequisites on clean Windows hosts, recent-project management
(rename/remove/pin), archive import, external workbook destination
selection and reconfirmation, multi-user collaboration, full project
launcher acceptance, source retrieval and 100,000-record GUI performance
are also outside this increment. No full product acceptance is claimed.

## Required merge gate

Before a merge recommendation obtain the **current PR HEAD SHA**, all four
Python regression jobs, four graphical dependency jobs, and four graphical
lifecycle jobs, with the actual real-project scenario outcomes and negative
cases. Require definitive completed exact-HEAD Codex code review and security
review, completion timestamps, individual matching receipts and disposition
of every substantive finding. Recheck after any new commit. **Never merge
without explicit project-owner authorisation.**
