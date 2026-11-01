# PR #44 — Windows worker startup/shutdown correction

This amends P1-06e2a under issues #43/#41. The approved repository
`RESEARCH-Y_SPEC.md` is unchanged. Relevant requirements are ARCH-02 (responsive
interface work separation), RUN-06 (close/reopen recovery), and RUN-02 (honest
states). Read this addendum with `APPLICATION_WORKER.md` and HANDOVER.

## Observed failure

On HEAD `a266002a770252d94fbbcaff73aee1f9d61abb98`, run #41360372113 failed on
both Windows/Python 3.12 and 3.13, in the same two existing tests:

- `test_close_during_startup_is_reaped_or_explicitly_unconfirmed`
- `test_concurrent_submits_coalesce_identical_and_refuse_conflict`

Both reached `shutdown_unconfirmed`; these were assertion/operation failures,
not workflow timeouts. The Windows/Python 3.12 job #125009306266 reported two
failed, 1,305 passed and two skipped. The existing domain integration and prior
terminal-readiness regression tests passed. Linux success did not establish
Windows acceptance.

## Mechanism and correction

The supervisor previously blocked directly in `recv_bytes`, treating pipe EOF
as its only way to discover a child that exited without a response. The CPython
Windows PipeConnection reducer duplicates the writer in the parent, for the
child to steal while unpickling. Death before that handoff can retain the parent
writer: the supervisor then receives neither a response nor EOF.

The correction has two parts:

1. Wait for pipe readiness **and** the child's exit sentinel, checking explicit
   shutdown between bounded waits. Child exit without a response is interrupted,
   not successful; a complete response already buffered before a normal exit is
   retained. A stop request takes precedence over a late response.
2. On Windows only, use the active spawn transport's `duplicate_for_child` to
   transfer the writer directly into the child's process. Its operating-system
   lifetime then belongs to the child even before Python argument unpickling.
   The parent's own sender is still closed after successful start. There is no
   fallback to the original parent-side steal-on-unpickle duplication.

`_WindowsSpawnSender` isolates the internal CPython 3.12/3.13 spawn boundary.
`_rebuild_windows_sender` reconstructs only the trusted, write-only child endpoint.
This is not a general deserialisation interface or browser-accessible endpoint.
An unsupported or failed transfer fails rather than silently selecting another
transport. Future Python-version support must revalidate this boundary.

No new queue, receiver thread, network listener, external dependency, or persistent
state is added. The existing shutdown timeouts, termination/reaping checks,
`shutdown_unconfirmed` failure, response-size bound, response validation, and
terminal-status/readiness correction remain in force. This does not claim a
sandbox against hostile native code in the same account. Search/export success
is still determined by production receipts and observations, never worker exit.

## Evidence

`tests/test_application_worker_shutdown.py` adds 12 cases: 11 portable cases and
one native-Windows case. Three real-process reproductions deliberately retain a
writer after normal/abrupt child exit or shutdown between process creation and
registration. The old implementation hangs or raises `shutdown_unconfirmed`;
the correction completes without needing pipe EOF. Other cases protect buffered
responses, stop precedence, wait timeouts, direct-child ownership and fail-closed
transfer. The Windows case kills 12 real children **before argument unpickling**
and checks both shutdown and process-handle counts.

Local Linux/Python 3.13.5 validation uses the exact current command module and
existing worker/completion test files (Git blob hashes verified). It runs real
spawn processes, not simulated process lifetimes, but substitutes synthetic
service work. Seventy cases passed; the one native-Windows case is not executable
on Linux. Worker branch-aware coverage is 92% rounded. Full repository cloning
was unavailable due to name resolution, so no complete local integration or
Windows pass is claimed. The full four-configuration continuous integration (CI)
run, including unchanged real-project integration tests, and new exact-commit
code/security reviews remain mandatory. Existing tests/workflows are unchanged.

## Primary implementation references

- https://docs.python.org/3.13/library/multiprocessing.html#multiprocessing.Process.sentinel
- https://docs.python.org/3.13/library/multiprocessing.html#multiprocessing.connection.wait
- https://github.com/python/cpython/blob/3.13/Lib/multiprocessing/connection.py
  (`reduce_pipe_connection` / `rebuild_pipe_connection`)
- https://github.com/python/cpython/blob/3.13/Lib/multiprocessing/reduction.py
  (`DupHandle`)
- https://github.com/python/cpython/blob/3.13/Lib/multiprocessing/popen_spawn_win32.py
  (`duplicate_for_child`)

This records a correction and test plan, not merge clearance or completed GUI
acceptance. Check current-HEAD execution and review records before merge advice.
