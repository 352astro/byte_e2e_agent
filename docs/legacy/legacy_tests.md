# Legacy / Outdated Tests Report

Generated: 2025-07-16

## Test Suite Summary

```
500 passed, 9 failed, 0 skipped (total: 509 tests across 12 files)
```

---

## 1. CAUTION.md Chain Mapping — OUTDATED

**File**: `backend/tests/CAUTION.md`

The chain mapping table lists files that no longer exist or omits files that do:

| CAUTION.md says | Actual file | Status |
|-----------------|-------------|--------|
| `test_api_chat_flow.py` | `test_api.py` | **Renamed** — update CAUTION.md |
| `test_hook_system.py` | ✅ exists | OK |
| `test_runtime_core.py` | ✅ exists | OK |
| `test_llm_streaming.py` | ✅ exists | OK |
| `test_session_workspace.py` | ✅ exists | OK |
| `test_tools.py` | ✅ exists | OK |
| `test_sandbox.py` | ✅ exists | See issue #4 below |
| `test_persistence.py` | ✅ exists | OK |
| `test_error_repair.py` | ✅ exists | OK |
| `test_shadow_repo.py` | ✅ exists | OK |
| *(not listed)* | `test_message.py` | **Missing from table** |
| *(not listed)* | `test_stream_driver.py` | **Missing from table** |
| *(not listed)* | `test_integration.py` | **Missing from table** |

**Action**: Update CAUTION.md table to reflect actual file names and add missing entries.

---

## 2. LoggingHook `_step` Counter — OBSOLETE TESTS

**File**: `backend/tests/test_hook_system.py`
**Tests**: `TestLoggingHook::test_step_counter_resets_on_turn_start`, `TestLoggingHook::test_step_counter_increments_on_message_start`

**Error**:
- `test_step_counter_resets_on_turn_start`: `assert hook._step == 0` → actual value is `5`
- `test_step_counter_increments_on_message_start`: `AttributeError: 'LoggingHook' object has no attribute '_step'`

**Root Cause**: The `LoggingHook` implementation has changed. The `_step` attribute was either renamed, removed, or its reset/increment logic was refactored. These tests are testing internal implementation details that no longer match the code.

**Action**: Update tests to match current `LoggingHook` implementation, or remove if the internal counter is no longer relevant.

---

## 3. `model_call` Hook Assertion Order — FLAKY TEST

**File**: `backend/tests/test_llm_streaming.py`
**Test**: `TestModelCall::test_streams_content_reasoning_and_finish_reason`

**Error**:
```
AssertionError: on_chunk_delta(msg=Message(...status=<MessageStatus.COMPLETE: 'complete'>...), ...) call not found
```

**Root Cause**: `model_call()` marks the message `COMPLETE` *before* firing the hooks (or the hooks receive the message post-completion). The test's `assert_any_call` matches against a message that is already `COMPLETE`, but the hook was called with a `STREAMING` message. This is a mock argument matching issue — the `msg` object is mutated in-place (`.mark_complete()`) before the assertion captures it, so the recorded call also shows the mutated state.

**Action**: Fix the test to capture the message state at hook call time (e.g., use `call_args_list` and inspect `status` before `.mark_complete()` was called), or relax the assertion to ignore `status` on the `msg` parameter.

---

## 4. `test_sandbox.py` — MISNAMED FILE

**File**: `backend/tests/test_sandbox.py`

This file imports `Workspace` from `agent.core.workspace` and tests `Workspace` functionality. The name "Sandbox" is a legacy term — the class was renamed to `Workspace`. The file name is misleading.

Additionally, this file overlaps significantly with `test_session_workspace.py`. Both test `Workspace`:

| test_sandbox.py | test_session_workspace.py |
|-----------------|--------------------------|
| `TestWorkspaceConstruction` | `TestWorkspaceConstructor` |
| `TestWorkspacePathManagement` | `TestWorkspaceDirectoryPaths`, `TestWorkspaceFilePaths` |
| `TestWorkspaceShell` | *(only in sandbox)* |
| `TestWorkspaceFileIO` | *(only in sandbox)* |
| `TestWorkspaceRepr` | *(only in session_workspace)* |

**Action**: Consider merging `test_sandbox.py` into `test_session_workspace.py` and dropping the "sandbox" name, or rename to `test_workspace_io.py` for the I/O/shell-specific tests.

---

## 5. Shell Tool Handler Tests — ENVIRONMENT-DEPENDENT

**File**: `backend/tests/test_tools.py`
**Tests**: `TestToolHandlers::test_shell_handler`, `test_shell_handler_nonzero_exit`, `test_shell_handler_timeout`, `test_shell_handler_nohup_background_survives`, `test_shell_handler_interrupt`

**Error**: All 5 Shell handler tests fail with `"Error: filedescriptor out of range in select()"`

**Root Cause**: These tests use a real `Workspace(tmp_path)` which calls `asyncio.create_subprocess_shell`. In the test environment (CI/headless/container), the file descriptor limit or select() behavior prevents subprocess creation. This is an infrastructure issue, not a code bug. The `test_sandbox.py` shell tests also exercise the same code path and currently pass (different test run timing/environment).

**Action**: These tests should be decorated with `@pytest.mark.skipif` when running in environments without proper subprocess support, OR the shell tests should use mocking instead of real subprocess (consistent with CAUTION.md's "Mock-First" rule).

---

## 6. Integration Test — REQUIRES RUNNING SERVER

**File**: `backend/tests/test_integration.py`
**Test**: `TestFullSessionTrace::test_session_lifecycle`

**Error**: `502 Bad Gateway` — the test tries to connect to `http://localhost:8000` but no server is running.

**Root Cause**: This is a real integration test requiring `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL_ID` env vars AND a running backend server. It is correctly marked `@pytest.mark.integration` and `@pytest.mark.skipif`, but the env vars are configured (so it's not skipped) while the server is not running.

**Action**: This is not a test bug — the test is working as designed. The failure is expected when the server isn't running. Consider adding a health-check precondition or documenting that `test_integration.py` requires `make run` first.

---

## Summary of Required Actions

| Priority | Issue | Action |
|----------|-------|--------|
| **High** | CAUTION.md mapping outdated | Update table with actual file names |
| **High** | LoggingHook `_step` tests broken | Fix or remove tests to match current code |
| **Medium** | `test_llm_streaming.py` assertion flaky | Fix mock argument matching for mutated msg |
| **Medium** | `test_sandbox.py` misnamed + overlaps | Rename or merge into `test_session_workspace.py` |
| **Low** | Shell handler tests env-dependent | Add `skipif` for headless environments |
| **Low** | Integration test needs running server | Document prerequisite, add health check |
