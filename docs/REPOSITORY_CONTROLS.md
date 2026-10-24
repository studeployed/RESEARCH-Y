# Public GitHub repository controls — RESEARCH-Y

Verified 24 October 2026 via GitHub repository and ruleset metadata. This page records **observed settings**, not a claim that all recommended controls are already active.

## Current effective setup

- Visibility: **public**. Public users can browse code, historical commits, pull requests and issues. Public visibility is not write permission.
- Default branch: `main`. It is protected by active ruleset **RESEARCH-Y - Protect main**, ID `25788555`, targeting the default branch only.
- Bypass list: empty.
- Rules enabled: restrict deletions, prevent non-fast-forward/force pushes, require pull requests before merging, require review-thread resolution.
- Human approving-review requirement: zero, enabling the sole project owner to authorise merges without a second human reviewer.
- **Required checks enabled:** strict (up-to-date) status checks from GitHub Actions, all four Windows/Linux × Python 3.12/3.13 jobs.
- GitHub Actions external-contributor approval setting: reported configured by the repository owner; the connector cannot inspect this account setting.

## Required checks and continuous integration

The active ruleset requires four checks from GitHub Actions:
- `Test ubuntu-latest / Python 3.12`
- `Test ubuntu-latest / Python 3.13`
- `Test windows-latest / Python 3.12`
- `Test windows-latest / Python 3.13`

Strict mode requires the pull-request branch to be current with `main` before merging. The workflow optimisation proposed in PR #16 retains this exact matrix and expected check names; it changes only the event triggers to run on pull requests targeting `main`, pushes to `main`, and manual dispatch, **not** extra feature-branch pushes.

**Approval policy:** GitHub's green checks do not replace the project owner's explicit merge approval. Neither ChatGPT nor automated apps may merge without the owner's authorisation.

## Native milestones

GitHub milestone objects should be maintained for:
- M0: Phase 0 foundation — issues #1–#3
- M1: Phase 1 durable end-to-end core — issues #4–#9
- M2: specialist processing
- M3: release verification

The authoritative acceptance criteria remain in `RESEARCH-Y_SPEC.md`.

## Privacy and credentials

The repository's Git history is public and cannot reliably be retracted. Commit only source code, approved public documentation and controlled synthetic test fixtures. Never put secrets or private research data in commits, issues, test logs, pull-request discussions or external fork CI. New credential-bearing integrations must be implemented with secure local storage and source-specific terms in mind.
