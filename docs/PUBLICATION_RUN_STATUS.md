# P1-06a review correction — parent-run status evidence

This addendum updates the first P1-06a verification checkpoint in
`PUBLICATION_IDENTITY.md` and `HANDOVER.md`. The original 62 cases are retained;
there are now **73 local passing cases**, including 11 new run-status regressions.
The two production modules retain **92% combined branch-aware coverage** in the
same Linux Python 3.13.5 / SQLite 3.46.1 targeted workspace. This is not full-repository
or Windows acceptance; the amended commit requires fresh checks and reviews.

## Finding and correction

PR #32 review of `276338f0a139dab2047bf351194f9e63a1ec0076` identified that publication
snapshots included query status but omitted parent search-run status. A parent
run changing from incomplete to failed left the review token unchanged. The
11 new cases all failed against that commit before the correction.

Each retrieval now exposes its actual `run_status`, including retrievals without
query memberships. Each query membership retains `status` (the source-query
status) and a distinct `run_status` (the parent search-run status). Both enter the
publication revision evidence. Parent status changes invalidate stale association,
field-choice, field-clear and reversal review tokens; fresh explicit review may
proceed without changing the underlying source or run statuses.

Dynamic run status is deliberately excluded from `source_sha256`, which remains
the checksum of the original stored retrieval row. Changing a run status is not
source corruption and must not make the original source/audit link unreadable.
No schema, source-query status, reported count, automatic matching rule, dependency,
workflow or approved requirement changed. Existing idempotent retries still perform
no mutation; they return current evidence rather than apply a second decision.

## Regression coverage and traceability

`tests/test_publication_run_status.py` covers distinct run/query evidence; stale
source and target tokens on separate runs with failed/cancelled/warning states;
stale field select/clear and reversal; queryless retrievals; unchanged source
checksums, source-query rows and identity state after rejected operations; and
successful fresh-review operations preserving their incomplete-source boundary.

Relevant requirements: DATA-01/04, RUN-02/03, COUNT-05, AUDIT-03 and scoped
AT-10/17/19. This extends the partial identity/provenance mappings already listed
in `requirements-traceability.csv`; it does not close the broader criteria.

The independent next-step preparation is issue #33, P1-06b conservative match
candidates and explicit decision receipts. That work is scoped, not implemented.
No new live provider requests or licensed datasets are needed for this correction.
