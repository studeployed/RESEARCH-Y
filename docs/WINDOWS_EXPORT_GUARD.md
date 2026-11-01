# Windows export-directory guard correction

## Observed failure and cause

Pull request #40 at `9a60dfe3a5fb80c8f1e2e98daea8a491a650f5cc`, continuous
integration (CI) run #41350002509, failed the native Windows directory-rename
assertion in both Python configurations. This was a real guard failure, not a
timeout or a reason to skip the test. The Python 3.13 run recorded one failed,
1,080 passed and two explicitly skipped tests.

`CreateFileW` was called with desired access zero. That supports metadata queries
but does not participate in the sharing-access checks needed to prevent another
handle being opened for deletion/rename. Omitting `FILE_SHARE_DELETE` is therefore
insufficient with that zero-access handle.

The guard now requests `FILE_LIST_DIRECTORY` (`0x0001`, the directory equivalent
of `FILE_READ_DATA`), while preserving read/write sharing without delete sharing,
`OPEN_EXISTING`, `FILE_FLAG_BACKUP_SEMANTICS` and `FILE_FLAG_OPEN_REPARSE_POINT`.
Opened handles must still identify ordinary, non-reparse directories. All held
ancestor handles are closed on normal exit or failure. If directory-read access
is denied, export fails closed: there is no fallback to a zero-access handle.

Official implementation references, checked 1 November 2026:
- [Microsoft sharing-access algorithm](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-fsa/8c0e3f4f-0729-49f4-a14d-7f7add593819)
- [Microsoft CreateFileW contract](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)

## Regression scope

The original `test_windows_directory_lock_or_posix_anchoring` remains unchanged.
`tests/test_export_windows_guard.py` adds seven portable call-contract/lifetime
cases and six native Windows cases. Portable cases check the exact access/share
flags, refusal after a denied open with no weaker retry, and closure on body
errors, interruption, inspection failure and unacceptable handle attributes.
They use a fake Windows interface and do not establish native lock behavior.

Native cases check leaf and ancestor rename attempts from another process,
empty-directory deletion, successful rename/delete after guard release, and
ancestor-handle cleanup following body interruption or failed descendant opening.
The native cases explicitly skip on Linux; their Windows results remain a
separate acceptance gate. The existing Windows junction cases remain mandatory.

Targeted local Linux validation: 33 passed, six native Windows cases skipped,
with `ResourceWarning` treated as an error. Two new portable cases fail against
the original zero-access code and pass with the correction. The production
module and original filesystem test were reconstructed and verified against
repository Git blob hashes before modification. This is not a full local
checkout, full application test, or local Windows execution claim.

## Requirement mapping and limits

This correction supplies scoped path-guard evidence for SEC-04, PROJ-04,
EXPORT-03/04 and AT-18/21. It does not complete those broad acceptance criteria
or close the separate archive/junction release issue #11. It changes no source
counts, credentials, schema, dependencies, workflow settings or specification.
No original test is removed or relaxed. The full four-configuration suite and
exact-current-commit code/security reviews must be revalidated before merge.

This remains a trusted local-project export service, not a sandbox against a
hostile same-account process or a guarantee of hardware power-loss durability.
Directory-read permission is now explicitly required for guarded ancestors.
Unsupported permissions or filesystems are refused, not bypassed.
