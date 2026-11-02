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

## Follow-up: isolate the native handle-count measurement

The preceding evidence describes the initial correction. On its amended HEAD
`0dfed8a82eeea5566186f74b3949c7ad4aefb3fb`, run #41362272834 passed both Linux
configurations and Windows/Python 3.13. Windows/Python 3.12 job #125014986924
finished with **1,318 passed, two skipped and one failed**. Both original shutdown
failures and all real-project worker integration cases passed. The remaining
failure was the new handle-count assertion: **189 handles versus a baseline of
186 plus an allowance of two**. All twelve child shutdowns had succeeded.

`GetProcessHandleCount` measures the entire calling process, not worker ownership.
The original measurement included pytest, its plugins and all earlier tests,
and retained the final worker variable while comparing its count with an earlier
baseline. The log does not identify which objects owned the three extra handles;
this amendment does **not** attribute them to a particular plugin or declare a
native leak absent merely because shutdown succeeded.

The amended test runs in a fresh disposable Python host without starting pytest
or its plugins. It warms both normal completion and bootstrap interruption, and
initialises the native counter before taking the baseline. Each measured worker
is scoped to a helper; weak references verify that the worker and supervisor
objects are gone before sampling. Samples follow 4, 8 and 12 genuine child deaths
before argument unpickling. **Every sample retains the original baseline + 2
ceiling.** There is no extra tolerance, retry-until-pass loop or ignored failure.

A second isolated native test deliberately restores the original standard pipe
reducer only in its disposable host. It must detect at least one leaked parent
writer per interrupted child and exceed the same two-handle ceiling. This is a
positive leak-detection control using actual handles, not fabricated counts.
Normal process exit then releases those deliberately leaked control handles.

The file now contains 15 cases: the eleven unchanged portable cases, two new
portable harness checks, and two native-Windows cases. One new portable check
uses a real child and weak references; the other checks sample ordering and
hook restoration with substituted helpers/counter. The focused local Linux run
passed all 13 portable cases; both native cases were skipped, not counted as
passes. Broader local combined runs were interrupted at execution limits and do
not establish a complete local regression result. Fresh full-repository CI and
matching code/security reviews must establish the amended commit's acceptance.

Only this test file and this explanatory document change. Production worker
code, existing completion/domain tests, shutdown deadlines, workflow timeouts,
dependencies and the approved specification are unchanged.

Counter reference:
https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesshandlecount
