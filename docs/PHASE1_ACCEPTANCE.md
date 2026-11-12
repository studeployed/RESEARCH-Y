# Phase 1 durable foundation

The phase gate in section 20 of `RESEARCH-Y_SPEC.md` is core retrieval and
recovery. [Issue #105](https://github.com/studeployed/RESEARCH-Y/issues/105)
tracks the six roadmap units. The source observations below have different
denominators. PubMed identifiers, retained metadata, Starter source records,
group memberships and reviewed publications are counted separately.

**Current gate:** the Windows shell, reviewed master, workbook and PubMed
recovery are on main. The authorized live Starter cross-day sample remains
outstanding.

| Roadmap unit | Verified observation | Evidence |
|---|---|---|
| P1-01 Project and launcher | The installed Windows application starts with no project selected. Two separate processes create, open, select, save and reopen a relocated synthetic project. They verify the same workbook and publication receipt. The test supplies the Windows folder picker's answer. | [Native Windows 3.12 and 3.13](https://github.com/studeployed/RESEARCH-Y/actions/runs/43304859715), [launcher merge](https://github.com/studeployed/RESEARCH-Y/pull/114) |
| P1-02 Storage and migration | The versioned SQLite project preserves approved strategy versions, source records, query/group memberships and audit receipts. Recovery tests cover transactional rollback and reopening mixed-source data. | [Storage closeout](https://github.com/studeployed/RESEARCH-Y/issues/5#issuecomment-6833173579), [mixed-source reopen](https://github.com/studeployed/RESEARCH-Y/pull/107) |
| P1-03 Strategy and compilers | Two-provider compilation preserves the approved OR groups and exact stored expressions. The live PubMed sample accepted the ECMO synonym and phrase expression through the translation check. Starter accepted the fixed Topic query under institutional entitlement. Missing an approved query keeps run-wide coverage unknown. | [Compiler closeout](https://github.com/studeployed/RESEARCH-Y/issues/6#issuecomment-6835708603), [frozen query coverage](https://github.com/studeployed/RESEARCH-Y/pull/106) |
| P1-04 PubMed | On 31 October, 19,483 unique PMIDs reconciled across 43 pages and six leaf partitions after a controlled restart. On 12 November, a separate sample returned two IDs and both metadata records in ten requests. The first record persisted unchanged and the fresh process fetched only the missing one. Offline fixtures exercise damaged evidence and provider-requested waits across ESearch and EFetch. | [Large identifier run](https://github.com/studeployed/RESEARCH-Y/actions/runs/41235232458), [metadata restart](https://github.com/studeployed/RESEARCH-Y/actions/runs/43300410950), [retained EFetch evidence](https://github.com/studeployed/RESEARCH-Y/pull/112), [backoff](https://github.com/studeployed/RESEARCH-Y/pull/115) |
| P1-05 Web of Science Starter | The 1 November run observed 19,584 source records, 392 acquisition pages and 392 independent verification pages. A separate process resumed on the same runner. The bounded cross-day observation is pending. | [Observed enumeration](https://github.com/studeployed/RESEARCH-Y/actions/runs/41306953908), [source limits and quota evidence](WOS_LIVE_ACCEPTANCE.md) |
| P1-06 Master results and Excel | Three retained sources across two groups produced two reviewed master rows, a group-count sum of four and all six source memberships. The explicitly selected workbook preserved the supporting review receipts, safe internal links and filters. A reversed match withdrew the current count. Two distinct retained abstracts sharing a supplement DOI remained separate. | [Cross-run review](https://github.com/studeployed/RESEARCH-Y/pull/110), [workbook saving](https://github.com/studeployed/RESEARCH-Y/pull/111), [reviewed master merge](https://github.com/studeployed/RESEARCH-Y/pull/116), `tests/test_phase1_acceptance.py` |

The 12 workflows for the reviewed master commit passed, including both
individual Codex reviews and the four Windows/Linux Python jobs. The local
Windows suite passed 2,360 tests with five platform-dependent skips. One
Windows 100,000-original-source native test initially reported an unavailable
button in the lost-reply case. Its identical-commit retry passed; both the
failure artifact and the retry are recorded in the [PR observation](https://github.com/studeployed/RESEARCH-Y/pull/116#issuecomment-6837061044).

## Evidence boundaries

The large PubMed sample verified identifiers. The smaller PubMed sample
verified metadata recovery. Starter's independent pass compared the observed
identifier sequence and rechecked the reported count. A live provider can
change its collection between observations. The checked-in summaries give
the run identifiers and artifact digests.

The bounded PubMed metadata and Starter cross-day workflows publish aggregate
evidence. They keep credentials and source bibliographic records off the
public artifact. A quota observation
from a different UTC date establishes a different day; an increase in the
observed remaining allowance establishes replenishment. Actual exhaustion
requires its own observation.

The native workbench uses the exact project and worker services tested on
Windows and Linux. The installed native tests run on Windows. The broad
release scenarios for specialist extraction, validated automatic scientific
thresholds, full exports, a bundled installer and comprehensive AT-01–22
acceptance retain their own roadmap gates.
