# P1-04i — Context-bound PubMed Create Date translation compatibility

**Status:** Proposed implementation; not merged and not yet validated by a new live retrieval.

## Evidence and requirement boundary

The 31 October 2026 [count-only diagnostic run #41216318046](https://github.com/studeployed/RESEARCH-Y/actions/runs/41216318046), at repository commit `cccb6b4d37ce0c5df02c9a545fd6c38b58188098`, returned **19,483** for both the unrestricted query and its whole-interval Create Date partition. The source returned no warnings and no transport error, but the existing comparator rejected these source strings:

Submitted:

```text
(("ECMO"[All Fields])) AND (1900/01/01:2026/11/01[crdt])
```

Accepted by PubMed:

```text
"ECMO"[All Fields] AND 1900/01/01:2026/11/01[Date - Create]
```

This is recorded provider behaviour, not a hypothetical change or a successful identifier retrieval. The National Library of Medicine documents CRDT and Date - Create as the same indexed date field. Matching counts alone are **not** evidence that arbitrary query rewrites are equivalent.

The unchanged approved specification requires broad OR-only concepts (SEARCH-06/07/10), explicit and count-reconciled retrieval partitions (SRC-02/03), original source provenance (RUN-07), and no false completeness claim (RUN-05). No new user date filter, AND operator, source field, dependency or schema migration is introduced here.

## Deliberately restricted equivalence rule

`pubmed_date_translation.internal_create_date_equivalent` tokenises and validates a small grammar rather than replacing strings globally:

```text
(quoted All Fields literal OR ... OR quoted All Fields literal)
AND
(one exact YYYY/MM/DD:YYYY/MM/DD Create Date interval)
```

Only a caller explicitly supplying `allow_crdt_partition=True` can use this rule. Root probes keep the existing strict comparison and AND/NOT review rule. Checkpoint writes and reopen checks derive internal context from the **validated immutable partition plan**, never from the accepted source text or a page's claimed clean-review flag.

The rule requires the same ordered literal terms, including case, punctuation, internal spaces and duplicates; the same All Fields tags; exactly one administrative AND; identical valid calendar-date boundaries; and exactly one date interval. The submitted generator's tag must be `[crdt]`. Its response may retain `[crdt]` or use the observed `[Date - Create]`. Balanced wrappers and OR-only grouping may differ without changing the union. An ungrouped mixture of OR and AND is refused rather than guessing provider precedence.

Additional AND/NOT, changed or missing concepts, reordering, altered date bounds, publication/entry-date substitutions, unknown field tags, wildcard or escape syntax, malformed parentheses, invalid dates and control characters fail closed. Operators and date-tag text **inside a quoted literal are preserved**, not interpreted or rewritten. Source warnings remain independently review-required even when the expressions match. Parsing uses iterative stacks rather than recursive descent, including for deeply nested wrappers.

## Consistent integration and provenance

- ESearch count probes pass their explicit internal context into both translation review and the equivalence flag.
- Identifier-page parsing already shares translation review, so it uses the same rule without changes to source requests or pagination.
- Checkpoint restart recounts retain internal/root context.
- Page commit and saved-page validation obtain context from the immutable plan and independently verify the exact submitted/accepted pair.
- Submitted queries, accepted source translations, counts, date partitions, response digests and original page checksums remain unchanged in storage. Existing exact-text checkpoints remain valid; old pages are not rewritten during recovery.

No network transport, credentials, quotas, request budgets, job schedules, binary date partitioning or completion-status rules change. No new workflow is needed.

## Regression coverage

`tests/test_pubmed_date_translation.py` exercises the observed source pair, harmless wrappers, quoted syntax, ordered OR terms and duplicates, field/date/operator mutations, malformed input and deep nesting. The focused parser suite was executed locally with **55 passing cases** before submission.

`tests/test_pubmed_date_translation_integration.py` exercises the actual count/page parsers and transactional checkpoint code with synthetic source responses using the observed canonical date tag. It covers **10,005** synthetic identifiers across disjoint dates, first-page pause, reopen/resume, no refetch of committed pages, preservation of raw source translations and old checkpoints, count drift, changed source interpretation, forged clean review flags and a semantically corrupted saved page with a recomputed checksum. Ordinary continuous integration remains offline. Results must be taken from the exact commit's test run, not assumed from this test list.

Requirement mapping: SEARCH-07; SRC-02/03; RUN-05/06/07; partial AT-06/07/09/19. The formal traceability rows remain **partial**. This correction alone does not establish live source completeness, full metadata acquisition, or recovery against an evolving provider snapshot.

## After review and owner-authorised merge

Run the existing **PubMed live >10k identifier checkpoint validation (manual)** on the new `main` commit, using the existing private secrets and workload safeguards. Inspect actual source counts, every partition/page, the identifier union and restart evidence. The earlier **19,483** is a dated observation, not a fixed expected current total. Any new source warning or materially different translation must remain incomplete/review-required rather than be silently accepted.

The already merged two-request diagnostic remains available for investigation, but this increment does not require another diagnostic-only pull request before attempting the existing controlled identifier validation. Web of Science Starter (P1-05) remains next after the PubMed evidence gate.

## Primary references

- [NLM: MEDLINE Data Changes—2018, Create Date search-tag aliases](https://www.nlm.nih.gov/pubs/techbull/nd17/nd17_medline_data_changes_2018.html).
- [NCBI: Entrez Direct Examples, indexed date field abbreviations and full names](https://www.ncbi.nlm.nih.gov/sites/books/NBK565821/).
- [PubMed Help: Create Date and date-range searching](https://pubmed.ncbi.nlm.nih.gov/help/).
- [Actual project source diagnostic #41216318046](https://github.com/studeployed/RESEARCH-Y/actions/runs/41216318046).
