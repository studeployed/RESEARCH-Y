# Official society directory and manual guidance capture

Use `python -m scripts.society_review PROJECT directory` to inspect the
project directory. The commands below each take a local JSON file and
`--confirm`. Generate a fresh UUID for each new entry or request. Reuse the
same request and input to recover a lost reply.

- `save-society` takes `society_id`, `name`, `official_url` and `actor`.
  An edit also needs the `expected_revision` from the directory.
- `record-visit` takes `request_id`, `society_id`, directory `revision`,
  `actor`, `method` (`manual_browse` or `site_search`), `terms`, `pages`,
  `outcome` and `limitations`. Each page has its actual `url` and an ISO
  `examined_on` date. Outcomes are `guidance_found`, `none_seen`,
  `unavailable` or `review_needed`. Inspect prior receipts with
  `visits SOCIETY_ID`. Each receipt preserves the directory revision and
  records the time of entry in UTC.
- `import-guidance` takes `request_id`, existing `run_id`, `visit_event_id`,
  `actor`, `record` and `roles`. The record needs a title, document types and
  an observed official landing URL. Optional source fields include authors,
  edition, issue date, update statement, direct document URL, journal
  citation, supplement and DOI. Omit unavailable fields. Each supplied
  role lists the corresponding project society IDs. At least one issuing
  society is required. Collaborating and endorsing organisations must be
  identified explicitly from the source.

These manual actions run offline. An unavailable website leaves a documented
task. An admitted document receives an original source record and a provisional
publication identity, independent of primary database query counts. Different
editions are distinct until a researcher reviews their relationship.
Use `suggest TERM [TERM ...]` for editable suggested libraries drawn from
the official [ELSO](https://www.elso.org/ecmo-resources/elso-ecmo-guidelines.aspx),
[SCCM](https://www.sccm.org/clinical-resources/guidelines) and
[ATS](https://site.thoracic.org/about-us/news/official-ats-documents) sites.
Saving a suggestion still requires researcher confirmation. Other societies
can be entered directly.

`relate` records a direction such as “this publication supersedes that
publication” or “this publication is a companion to that publication”. Its
JSON fields are `request_id`, `publication_id`, `other_publication_id`,
`relation` (`supersedes` or `companion_to`), `expected_revision`,
`other_revision`, `actor` and `rationale`. Supersession cycles are refused.

Use `attach-journal` only after comparing the source evidence for a matching
edition. Supply `society_publication_id`, `journal_retrieval_id`,
`society_revision`, `journal_revision`, `actor` and `rationale` and pass
`--confirm`. This operation reuses the existing reversible identity decision
and retains the society roles and journal source. Other editions keep their
own publication IDs. Desktop integration is tracked in [P2-03](https://github.com/studeployed/RESEARCH-Y/issues/129).
