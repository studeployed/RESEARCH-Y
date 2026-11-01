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

## Progression between steps

Owner direction recorded on 1 November 2026:

> at each completion step, begin instituting the next step

During an active working session, verify the completed step against its stated acceptance scope, record its evidence and outstanding limitations, then immediately initiate the next ready task in the approved roadmap. Do not stop merely to ask for another routine "go". In-scope implementation, tests, documentation, issue preparation and pull-request creation may proceed under this direction.

This does not authorise merging, weakening branch protections, treating running checks or reviews as completed, changing the approved specification, or performing a live action without its required consent. A pull request being opened is not a completed implementation milestone. Respect dependency gates; preparatory work on the next increment may proceed while a merge is awaiting owner approval, but dependent work must not assume that merge occurred.

When a required review, owner action or genuine blocker prevents further progress, report the exact current state and next action. Do not claim asynchronous monitoring or future completion when no supported task has been scheduled. The exact-commit code/security review protocol remains mandatory for every pull request, including documentation-only changes.
