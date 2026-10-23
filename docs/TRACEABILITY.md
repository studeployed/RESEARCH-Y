# Requirements-to-tests traceability

The authoritative requirement identifiers are in [`RESEARCH-Y_SPEC.md`](../RESEARCH-Y_SPEC.md). A machine-checkable table is in [`requirements-traceability.csv`](requirements-traceability.csv), and `scripts/check_traceability.py` verifies its completeness and uniqueness against the specification.

Statuses in the CSV are one of:
- `planned`: no verified implementation yet.
- `partial`: tested increment contributes but does **not** satisfy complete requirement/acceptance scenario.
- `verified`: complete and verified against relevant mandatory acceptance criteria (none initially).

`test_reference` names a real test when present; `planned` otherwise. Fixture verification is not represented as real-source validation. The master acceptance suite AT-01 to AT-22 remains outstanding until every scenario is verified. See [`ROADMAP.md`](ROADMAP.md) for issue/milestone allocation and [`HANDOVER.md`](../HANDOVER.md) for real execution evidence.
