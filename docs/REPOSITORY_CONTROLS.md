# GitHub repository controls (manual configuration)

This private repository is set up for issue-led pull-request development. The connected GitHub integration currently supports branches, commits, issues, reviews and workflow inspection, **but not** creating native milestone objects or configuring branch-protection rules. These are recommendations, not claims of configured controls.

## Native milestones

In GitHub **Issues → Milestones → New milestone**, create:

- **M0 — Foundation** (Phase 0): link issues #1, #2, #3.
- **M1 — Durable end-to-end core** (Phase 1): link issues #4–#9.
- **M2 — Specialist processing** (Phase 2): see `docs/ROADMAP.md`.
- **M3 — Workflow and release verification** (Phase 3): see `docs/ROADMAP.md`.

The scope and acceptance gates stay authoritative in `RESEARCH-Y_SPEC.md`.

## Main branch protection

In GitHub **Settings → Rules → Rulesets** or **Settings → Branches** (interface and plan permitting), require a pull request to modify `main`, require successful relevant Windows and Linux checks, and prohibit force pushes and branch deletion. Consider requiring review approval and dismissing stale reviews on change. Restrict bypass rights where available. Document any settings that are unavailable on the repository's plan.

**Non-technical approval gate:** GitHub approval alone does not replace the project owner's instruction. Do **not merge any pull request without explicit approval from the project owner**, even if all automated checks pass.

## Credentials

Use repository secrets only for controlled live-source tests when approved. Ordinary fixture tests require no external credentials. Never check credentials or research project data into Git.
