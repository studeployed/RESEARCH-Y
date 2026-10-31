# RESEARCH-Y handover — 31 October 2026

## Authority and merged baseline

Repository: https://github.com/studeployed/RESEARCH-Y. The approved version-controlled `RESEARCH-Y_SPEC.md` (1.0.0-draft.1) remains authoritative and unchanged. Development is independent and Python-based. Current merged base is **`0fd89c1bdac509513c9c1cf25c83683556472dac`**, PR #26 / P1-04i. The post-merge four Windows/Linux Python 3.12/3.13 checks passed. The owner has authorised in-scope development and opening pull requests directly; **merging still requires explicit owner authorisation**. Substantive specification changes require separate approval.

Existing portable projects, recoverable SQLite migrations, immutable broad OR-only strategies, PubMed All Fields / Web of Science Starter Topic compiler, PubMed counts/partitioning/checkpoints and EFetch metadata foundations remain merged. Deferred Windows junction hardening issue #11 remains open for future untrusted archives/import work.

## PubMed live gate — verified scoped success

[Run #41235232458](https://github.com/studeployed/RESEARCH-Y/actions/runs/41235232458), completed 31 October 2026 at 19:39:57 UTC on the merged base, retrieved **19,483 unique PubMed identifiers**, matching its source count, across **43/43 pages and six disjoint leaf partitions**. The first process paused after one page containing two identifiers; a separate process reopened and fetched the remaining 42 pages. Runtime evidence reports that the original page was unchanged and not requested again.

The downloaded artifact and independent audit were inspected in the project conversation. `docs/evidence/pubmed-41235232458-summary.json` retains exact run/commit, intervals/counts, artifact/evidence/union hashes and limitations. It is explicitly a summary, not a replacement for the full per-page evidence. The original Actions artifact expires 14 November 2026; the full evidence and audit were also supplied as conversation files and should be retained for independent replay.

The scoped AT-07 >10,000-ID live scenario and PubMed identifier-stage AT-09 controlled pause/reopen scenario **passed**. Broader AT-06 terminology, full bibliographic metadata/abstract reconciliation, abrupt failures, multi-day source changes and product-wide acceptance remain partial. `identifiers_reconciled_metadata_pending` and `source_retrieval_verified=false` remain correct. The dated count is not a permanently expected total.

## Current increment — P1-05a, Web of Science Starter source contract

Parent issue #8 and roadmap milestone P1-05. This is the **first incremental portion**, not completion of the entire connector/recovery milestone. Read `docs/WOS_STARTER.md` for the official contract, implementation boundaries and live hypotheses.

- `wos_starter.py`: quoted OR-only Topic requests; strict requested/returned page, size and count checks; accession uniqueness; original source fields retained in memory; unavailable abstracts explicitly marked; no inferred translated query or full-source success.
- `wos_starter_client.py`: fixed HTTPS endpoint, key header only, no redirects, 1.05-second serial pacing, finite request budget, observed quota rather than configured assumptions, safe error categories and Retry-After handling without implicit retries.
- Daily allowance of at least 5,000 must be actually observed before continuing beyond the initial access probe. Missing/invalid quota headers are unverified. The OpenAPI schema does not guarantee the adapter's candidate quota headers; the live check must verify them. No reset time or licence scope is inferred.
- `scripts/wos_source_smoke.py` and manual-only `.github/workflows/wos-starter-live-smoke.yml`: fixed public `TS=("ECMO")`, explicit Core Collection `db=WOS`, one-record access probe then at most two adjacent 50-record pages. Maximum three requests. No automatic credentialled CI calls or licensed source-record content in public artifacts. No project database is modified.
- No dependencies or authoritative requirements changed. Normal tests are synthetic and offline. The new unit tests were run locally; full cross-platform CI and reviews must be checked on the actual PR HEAD.

**Not implemented by P1-05a:** durable SQLite source-page/audit storage, cross-day restart/quota accounting, full-search completion, bounded scheduled retries, source/master linkage, enrichment or GUI. These are P1-05b/acceptance work, not silently deferred release requirements.

## Windows test-reporting incident and correction within PR #27

The owner supplied both Windows logs from run #41239845805 at HEAD `03c6c396f56e7bf5ed67d0ebe0497a6b5c68f2ff`. Both reached 100% of collected test progress around 20:41 UTC, showed `EE` in `test_wos_starter.py`, and began the errors section before a very long `test_invalid_json_and_size[xxxxx...]` setup-error heading appeared around 21:52 UTC. Thus this was not simply an uncompleted retrieval test. The supplied excerpts do not include the underlying exception traceback; no specific Windows exception code is claimed.

The offending parametrization passed `b'x' * (MAX_RESPONSE_BYTES + 1)` without an explicit short ID, so pytest embedded the entire 2,097,153-byte payload in its node identifier. Pytest 9.0.2 sets the node identifier plus execution stage in `PYTEST_CURRENT_TEST`; Windows environment values are limited to 32,767 characters. This is a strong explanation of the platform-specific setup error and oversized error heading. A local Linux collection-only reproduction using the actual parameter lists confirmed a greater-than-two-million-character node identifier, and a simulated Windows environment-length guard rejected it. That simulation is not a substitute for rerunning Windows CI.

Correction: compact explicit IDs for the six malformed/oversized-response cases and six invalid-key cases; a regression assertion checks actual collected Starter node IDs are no longer than 256 characters. The original payloads, parser assertions, 2 MiB response ceiling, key checks and all production source code are unchanged. Normal test jobs now have a 15-minute limit and short traceback formatting. No new dependencies, test skips, licence/credential changes, or live provider calls are introduced.

The owner reports that `RESEARCHY_WOS_STARTER_API_KEY` has been configured. Do not expose or re-enter it to fix these offline test failures. Recheck the new commit's four CI jobs and obtain exact-HEAD reviews; reviews of the previous commit do not clear the amended PR.

References: [pytest current-test environment](https://docs.pytest.org/en/stable/example/simple.html#pytest-current-test-environment-variable); [Windows environment-variable limit](https://learn.microsoft.com/en-us/windows/win32/procthread/environment-variables).

## Next action

Complete exact-HEAD automated tests and independent reviews, then leave the pull request for owner approval; do not merge automatically. Automatic code/security reviews may already be running: inspect summary, individual receipts and findings before requesting anything, and do not duplicate valid reviews. Missing/contradictory evidence is unverified, not passed.

After an approved merge, use the privately configured **`RESEARCHY_WOS_STARTER_API_KEY`** repository secret (the institutional Starter key, not the PubMed key). Run **Web of Science Starter entitlement and paging smoke (manual)** once on the new `main`. Inspect actual quota and page evidence, without treating the sample as full retrieval. **No live Starter access is yet verified.**

Next development portion is P1-05b: transactional durable pages and source records, pause/reopen across quota resets, bounded retry timing, no repeat of committed pages, source drift detection and final reconciliation. The full AT-08/09 gate remains open until those behaviours and live entitlement are demonstrated.
