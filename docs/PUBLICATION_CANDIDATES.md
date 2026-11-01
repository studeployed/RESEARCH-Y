# P1-06b — Bounded candidate evidence and explicit decision receipts

## Authority and scope

Built on merged PR #32, commit `87f6d087b6273ccaf2377179113380664e2a2568`.
The approved `RESEARCH-Y_SPEC.md` is unchanged. Parent issues #33 and #9.
Requirements DATA-01/02/04/05/06, DUP-01–05, COUNT-01/05, AUDIT-02/03,
PROJ-04 and scoped AT-01/02/09/10/11/17/19/21 remain partial.

This is a bounded review engine, not exhaustive duplicate discovery or validated
automatic matching. No source call, credential, dependency, schema migration,
workflow change or source-completeness promotion is introduced.

## Read-only comparison

`read_candidate(project, left_retrieval_id, right_retrieval_id)` requires two
already materialised source retrievals. It reads both current publications in one
SQLite transaction. The pair order is canonical; repeated/reversed inputs give
identical evidence and no writes. It preserves source/group/query/run context,
query counts/status and parent-run status, without duplicating source records.

Explicit PubMed and Web of Science Starter paths supply title, digital object
identifier (DOI), PubMed identifier (PMID), accession, authors, publication year,
journal, pagination and document-type comparison inputs. Source values and paths
remain visible. Missing, not supplied, malformed and multiple-valued inputs are
not agreement. PubMed history dates are not publication dates. Ambiguous years
and incomplete author representations remain non-comparable. Alternative source
values, missingness and rights are still preserved in the original retrieval.

Only case/outer whitespace and documented DOI prefixes are normalised. DOI
punctuation and percent encoding are not removed. Structural identifier syntax
is NOT verification of registration, publication scope or bibliographic identity.
DOI scope remains explicitly unverified; an identifier attached to an abstract
or supplement may belong to its container. Differences are review evidence,
not proof that publications differ. No inferred language/species exclusion is added.

`find_candidates` accepts an explicit batch of 2–32 distinct retrievals. It
returns pairs with exact normalised title/identifier agreement or prior decisions.
A larger/invalid batch raises before processing; it is never silently truncated.
The bound applies only to this review helper, not source acquisition. It does not
claim to find every duplicate, search a whole project, perform fuzzy matching,
or establish the 100,000-record AT-22 performance requirement. Receipts currently
use a linear audit scan; indexed discovery/history access is follow-on work.

## Decisions and transaction boundaries

`decide_candidate` requires the current internally reconstructed review revision,
an explicit `confirmed_match` or `rejected_match`, actor, evidence, explicit
confirmation and acknowledgement of every displayed warning. A supplied snapshot
dictionary is never trusted; original database evidence is read again under
`BEGIN IMMEDIATE`. A changed source/target publication, field choice, query or
parent-run status, rule version or relevant decision history requires fresh review.

Confirmation moves ONE specified retrieval onto the other record's current
publication. It calls the existing association logic through a shared transaction
helper, preserving stale-review, chosen-field and specialist-annotation guards.
The public association function remains compatible. The identity event, link
change and candidate receipt share one commit/rollback boundary. A failure or
abrupt exit cannot leave a committed match without its receipt.

Rejection changes no source/association. Rejecting an already combined pair is
refused: reverse the existing association first, then review the refreshed pair.
Explicit reconsideration appends a superseding receipt; it does not edit history.
An exact retry of the still-current decision is a no-op. Changed context, a later
relevant receipt or reversal prevents replay of an obsolete request.

Receipts use the existing immutable `audit_events` table and retain comparison
outcomes, field paths/value hashes, original source-row hashes, rule version,
reviewed source/query/run context, actor/evidence, prior decision and associated
identity-event reference. No titles or abstracts are copied into generated receipt
fields. Actor/evidence are user assertions, not authenticated identity or external
verification; users must not enter credentials there. Selecting or comparing a
source value never grants redistribution permission.

## Previous runs and incomplete work

Receipts for the same namespaced source-record pair remain visible in later runs,
including earlier rejection and contradictory evidence. A Web of Science database
namespace is part of that identity. Old decisions are NOT automatically propagated.
A fresh comparison and researcher decision are required; changed evidence never
silently reverses an earlier decision. `automatic_high_confidence` is disabled.

Annotation-aware publication-wide merge/split, validated automatic rules, indexed
project-wide discovery, general rerun propagation, final deduplicated counts,
exports and the interface remain follow-on tasks. The source-acceptance gaps in
issues #7/#8 and deferred Windows junction issue #11 remain open.

## Verification

81 new disk-backed local cases passed with Python 3.13.5, SQLite 3.46.1 and pytest
9.0.2, treating ResourceWarning as errors. Combined branch-aware coverage of the
two new modules is 97% (rounded). Tests cover comparison ambiguity, shared
supplements, abstract/full-paper distinctions, preserved source denominators,
reopening/relocation, prior runs, explicit reconsideration, reversal/stale tokens,
concurrent identical decisions, audit/link rollback and an actual child process
terminated after dirty-page spill between the identity event and receipt.

Four intentional negative mutations were detected: omitted fresh-review guard,
omitted explicit confirmation, bypassed existing move guard, and treating a
malformed parent object as a valid identifier field. The originals were restored
and the full targeted suite rerun. Seven baseline package/project/schema/identity
modules were reconstructed and checked against Git blob hashes. This is a targeted
local workspace, NOT a full checkout, a Windows run or live-source validation.

All four full repository Windows/Linux Python 3.12/3.13 checks and exact-HEAD code
and security review evidence remain mandatory. No merge is authorised by this note.

## Source mapping references checked on 1 November 2026

PubMed mappings follow `src/research_y/pubmed_metadata.py` and
`pubmed_metadata_store.py` at the baseline. Starter raw retention follows
`wos_checkpoint_store.py` and `wos_starter.py`; optional fields were cross-checked
against Clarivate's official client models (not a live provider test):

- https://github.com/clarivate/wosstarter_python_client/blob/master/docs/Document.md
- https://github.com/clarivate/wosstarter_python_client/blob/master/docs/DocumentIdentifiers.md
- https://github.com/clarivate/wosstarter_python_client/blob/master/docs/DocumentSource.md
- https://github.com/clarivate/wosstarter_python_client/blob/master/docs/DocumentSourcePages.md
- https://github.com/clarivate/wosstarter_python_client/blob/master/docs/AuthorName.md

Unknown layouts fail to produce comparable fields, not fabricated fallback values.
