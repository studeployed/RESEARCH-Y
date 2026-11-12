# P1-06l2 — Full original 100,000-record provisional workbook evidence

**Authority:** unchanged version-controlled `RESEARCH-Y_SPEC.md`; owner-merged pull request (PR) #95 at `main` commit `3b843d9453ddc654f69b43f003c1ee6f911df00a` on 12 November 2026. Increment P1-06l2 is **only an internal export/scale test**, contributing partial evidence to original source-integrity, EXPORT-01/03/04 and acceptance tests AT-10/18/19/21/22. No source-coverage claim, deduplication certification or end-user Excel export is established.

## Purpose and fixed original workload

The approved specification calls for reproducible, truthful Excel results covering every original retrieved record and group membership, and eventual performance on a representative 100,000-record project. PR #95 introduced a read-only, unlicensed-text-free **provisional provenance manifest** with four sheets: `Evidence & Limits`, `Provisional Identities`, `Original Source Links`, and `Query Memberships`. It deliberately did *not* create the authoritative completed `Master Results` worksheet, a final unique-publication verdict, rights-cleared citation/abstract content, a graphical control, or an audited export request.

The new bounded `scripts/benchmark_provisional_manifest.py` uses the *existing real versioned SQLite scale-fixture seeder*, original `source_retrievals`, `query_retrievals`, original immutable identity event receipts and the existing fixture-only bulk materialisation helper. The **same synthetic project and run** is examined twice:

1. **Unmaterialised majority:** 100,000 original source records and **100,000 original query/group memberships**, of which only **128** have independent fixture-audited provisional identity links; **99,872 unmaterialised** originals must remain explicitly visible in the workbook.
2. **All independently provisional:** The fixture-only test helper commits separate source/audit/identity records for the remaining 99,872 original sources, then opens the project again. The workbook must retain **100,000 provisional identity rows, 100,000 original source link rows and 100,000 distinct original query/group membership rows**. This is *not* approved production materialisation and does *not* imply 100,000 scientifically unique papers.

The benchmark independently reads original SQLite counts and table identities, including the original source and membership SHA-256 hashes and original database byte digest. It validates `PRAGMA integrity_check` and `foreign_key_check`, links each workbook source row to its original retrieval/publication/provisional status, links each exported group membership to the *exact* retained source/query/group/source/run statuses, and confirms every provisional publication ID appears exactly once. Counts, identities, memberships, completeness warnings, no unapproved formulas, and the four expected sheet names must all agree.

It opens the generated **actual Excel bytes** in read-only mode and independently inspects the decompressed worksheet XML in **bounded chunks** for synthetic DOI, original provider title and abstract markers, avoiding the false reassurance of scanning compressed ZIP bytes. The workbook is discarded after validation and never copied to a retained artifact or published destination. It verifies that the original SQLite bytes, source hashes and membership hashes are identical before and after each render; only the synthetic fixture-only materialisation step changes the publication/audit tables between scenarios.

## Real Windows and Linux test execution

The new `.github/workflows/manifest-100k.yml` runs one **Windows** and one **Linux** Python 3.12 job with the already approved optional, pinned `openpyxl==3.1.5` and `et-xmlfile==2.0.0` dependency versions. Each job builds the full original 100,000-row fixture, runs both workbook scenarios, parses every source/membership row again, records fixture-seeding duration, per-scenario rendering and **separate verification elapsed time**, output size and **parent-process peak resident memory**, and then independently verifies an aggregate-only JSON evidence file.

The only uploaded artifact is that aggregate JSON. It contains record totals, Boolean integrity/rights/coverage flags and measured times/byte sizes; **no source titles, abstracts, DOI/PMID/accession values, unlicensed record payloads, project path, workbook bytes, original SQLite or credentials** are retained or uploaded. Failures return a **static unverified status**, not a misleading partial success. There are no provider network calls.

A small 512-original fixture follows the **same code path on all four regular Python test platforms** (Linux/Windows Python 3.12/3.13); it verifies both the 128/512 identity states, every source/link/group row, absence of original document text, unchanged original project, and truthful `INCOMPLETE` scientific status. Inputs outside the explicit 512–100,000 synthetic source range are rejected; there is no researcher-facing parameter or new application command.

## Acceptance boundary and next development decision

This work tests the original PR #95 internal renderer *at realistic scale* and records whether it succeeds on both target platforms. It does **not** change the renderer or final publication model, implement deduplication, approve metadata redistribution, classify study designs, export licensed abstracts, demonstrate 100,000-row responsive GUI interaction, prove 100,000 unique publications, or fulfil the complete primary EXPORT-01 / AT-18 / AT-22 acceptance. No total duration target beyond the existing finite **55-minute CI job limit** is asserted or tuned to pass.

The evidence must guide the next bounded decision: fix a genuine performance, memory, correctness or recovery blocker first, or separately propose an audited, explicitly authorised integration of the provisional workbook only after source-rights and publication-recovery constraints are satisfied.

**Merge protocol:** validate the exact current PR HEAD, all four Python jobs and two new native-platform 100,000-original-row jobs, review actual retained aggregate artifacts, require a definitive completed Codex **code review first**, then a completed same-commit **security review** with individual review receipts/finding disposition. Do not recommend merging if any gate is unverified, and never merge without the project owner's authorisation.
