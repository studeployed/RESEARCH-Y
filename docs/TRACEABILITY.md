# Requirements-to-tests traceability

The authoritative requirement identifiers are in [`RESEARCH-Y_SPEC.md`](../RESEARCH-Y_SPEC.md). A machine-checkable table is in [`requirements-traceability.csv`](requirements-traceability.csv), and `scripts/check_traceability.py` verifies its completeness and uniqueness against the specification.

Statuses in the CSV are one of:
- `planned`: no verified implementation yet.
- `partial`: tested increment contributes but does **not** satisfy complete requirement/acceptance scenario.
- `verified`: the full clause or named scenario has been checked against implementation and test evidence.

`test_reference` identifies the evidence for each status. The [Phase 3 acceptance record](PHASE3_ACCEPTANCE.md) covers all 22 acceptance scenarios and describes their scope. Individual product clauses can require additional behaviour beyond those scenarios. [Initial release issue #163](https://github.com/studeployed/RESEARCH-Y/issues/163) tracks reconciliation of the 115 product clauses marked partial at commit `030a2f8`. See the [roadmap](ROADMAP.md) for milestones and the [handover](../HANDOVER.md) for real execution evidence.
