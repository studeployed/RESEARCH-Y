# P1-05b: preserve malformed quota observations

## Requirement and review context

This correction addresses the PR #28 code-review finding on commit
`d14526b0634e101968b80c874accf84099ff88eb`: **Preserve invalid quota state
when revalidating pages** (review comment 4433893639).

It supports existing RESEARCH-Y_SPEC.md requirements SRC-05 (observe, do
not assume entitlement), SRC-08 (truthful incomplete state), RUN-04/06
(durable interruption and resumption) and RUN-07 (retained evidence).
There is no specification, schema, source-query, credential or workflow change.

## Cause and correction

The source quota parser distinguishes malformed headers (`valid=false`)
from absent headers (`valid=true` with unknown numeric fields). Both are
unverified entitlement; neither permits continued retrieval. Reconstructing
an invalid quota as an empty header mapping erased that distinction during
checkpoint validation, raising `inconsistent_page_object` before the known
response could be recorded. The active request/ownership token then required
crash recovery despite a normally returned response.

The local `_quota_headers` adapter now recreates an explicitly invalid
parser input when the stored quota has `valid=false`. This internal marker
is **not an observed provider header and is not persisted as source evidence**.
The original document payload and parsed quota descriptor remain unchanged.
The shared adapter is used both before committing and when reopening retained
observations. All existing body, count, page-identity and checksum comparison
checks remain active.

The normal response transaction can therefore record the known response and
invalid quota, leave the job `incomplete` / `entitlement_unverified`, preserve
previously committed pages and release worker ownership. No implicit retry or
assumed quota is introduced; explicit revalidation with a new source observation
is still required. A known successful transport response does not establish
accepted entitlement or complete retrieval.

## Regression coverage

`tests/test_wos_quota_regressions.py` adds 20 offline cases:

- Eight page/quota round trips: valid, exhausted, absent, partly absent,
  malformed, negative, zero rate and conflicting-case quota headers.
- Two deliberately altered pages remain rejected despite invalid quota.
- Malformed and absent quota responses at each of five request stages:
  initial acquisition, later acquisition, resume probe, verification and final
  probe. These assert durable incomplete status, preserved observations and
  committed records, no unknown request or active worker, safe reopening,
  no automatic retry, and explicit revalidation without repeating committed
  acquisition pages.

The originating code-review example was reproduced with the actual parser
and checkpoint helpers locally. Four malformed-header variants raised before
the change. After the change, eight round trips, eight SQLite observation
reopens and two altered-page rejection checks passed in the isolated harness.
These isolated checks do **not** substitute for the full-repository Linux and
Windows test matrix or independent review on the amended commit. The new
end-to-end cases must pass there before merge acceptance.

No live provider calls or licensed-record exports are part of this correction.
Full live retrieval/recovery acceptance remains a separate post-merge gate.
