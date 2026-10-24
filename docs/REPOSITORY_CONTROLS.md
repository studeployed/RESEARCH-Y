# Public GitHub repository controls — RESEARCH-Y

Verified 24 October 2026 via GitHub repository and ruleset metadata. This page records **observed settings**, not a claim that all recommended controls are already active.

## Current effective setup

- Visibility: **public**. Public users can browse code, historical commits, pull requests and issues. Public visibility is not write permission.
- Default branch: `main`. It is protected by active ruleset **RESEARCH-Y - Protect main**, ID `25788555`, targeting the default branch only.
- Bypass list: empty.
- Rules enabled: restrict deletions, prevent non-fast-forward/force pushes, require pull requests before merging, require review-thread resolution.
- Human approving-review requirement: zero, enabling the sole project owner to authorise merges without a second human reviewer.
- **Not enabled yet:** required automated status checks. This is the remaining protection setting to configure.
- GitHub Actions external-contributor approval setting: reported configured by the repository owner; the connector cannot inspect this account setting.

## Complete the required checks

In [repository ruleset settings](https://github.com/studeployed/RESEARCH-Y/settings/rules), edit ruleset `RESEARCH-Y - Protect main` and tick **Require status checks to pass**. Choose **GitHub Actions** when specifying the expected source, and require the following four checks:

- `Test ubuntu-latest / Python 3.12`
- `Test ubuntu-latest / Python 3.13`
- `Test windows-latest / Python 3.12`
- `Test windows-latest / Python 3.13`

Enable checking that the pull-request branch is up-to-date before merging when appropriate. Save the ruleset and verify that all four checks appear in its `required_status_checks` rule. Do not enable **Restrict updates** on `main`: without a bypass, it can interfere with legitimate pull-request merges.

**Approval policy:** GitHub's green checks are a necessary verification signal, not the project owner's permission to merge. ChatGPT must never merge a pull request without the owner's explicit authorisation.

## Native milestones

GitHub milestone objects should be maintained for:
- M0: Phase 0 foundation — issues #1–#3
- M1: Phase 1 durable end-to-end core — issues #4–#9
- M2: specialist processing
- M3: release verification

The authoritative acceptance criteria remain in `RESEARCH-Y_SPEC.md`.

## Privacy and credentials

The repository's Git history is public and cannot reliably be retracted. Commit only source code, approved public documentation and controlled synthetic test fixtures. Never put secrets or private research data in commits, issues, test logs, pull-request discussions or external fork CI. New credential-bearing integrations must be implemented with secure local storage and source-specific terms in mind.
