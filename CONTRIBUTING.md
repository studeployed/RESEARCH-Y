# Development workflow

1. Read `RESEARCH-Y_SPEC.md` and `HANDOVER.md`; identify requirement identifiers before coding.
2. Choose a single issue and define expected behaviour, representative fixtures and failure/recovery tests.
3. Work in a feature branch. Make small commits; do not develop directly on `main` for substantive features.
4. Run unit/integration tests, traceability validation and (for applicable changes) real-source smoke tests. Distinguish fixture success from source verification.
5. Open a pull request referencing the issue, requirement IDs, tests and documented limitations.
6. Perform a **code-quality review** (correctness, performance, maintainability, schema/data-model integrity, failure cases) and an independent **security review** (credentials, licence, untrusted data, recovery, dependencies).
7. Record evidence and update `HANDOVER.md` at meaningful milestones.
8. **Do not merge any pull request without explicit approval by the project owner.**

Substantive amendments to the approved specification, paid services, material new dependencies, publishing or deployment also require explicit approval. Avoid introducing RESEARCH-X code or dependencies.
