# ⚠️ CAUTION — AGENT TESTING RULES

## DO NOT run full-suite tests.

Each test file in this directory targets a **single architectural chain** (链路).
Tests are designed to be run **individually, per chain**.

## Rules for AI Agents

1. **Targeted Testing Only**: Run only the specific test file(s) directly related to
   the current code modifications. NEVER run `pytest` without a file filter.

2. **Before Running Any Test**:
   ```bash
   # ✅ Correct: target the specific chain
   pytest tests/test_hook_system.py -v

   # ❌ Wrong: full-suite
   pytest tests/ -v
   ```

3. **Mock-First**: All tests use mocks for external dependencies (LLM, filesystem,
   network). Real LLM integration tests are opt-in and marked with `@pytest.mark.integration`.

4. **Isolated Chains**: Each test file tests exactly one architectural chain from the
   diagram. No test file depends on another test file's side effects.

## Test File → Chain Mapping

| Test File | Chain Tested |
|-----------|-------------|
| `test_api_chat_flow.py` | API → Project → AgentRuntime → SSE streaming (端到端) |
| `test_hook_system.py` | BaseHook + HookManager + StreamDriverHook + MetricsHook + LoggingHook |
| `test_runtime_core.py` | AgentRuntime._execute_turn() ReAct 主循环 |
| `test_llm_streaming.py` | LangChain model_call + astream + chunk 组装 |
| `test_session_workspace.py` | Session 生命周期 + Workspace 路径管理 |
| `test_tools.py` | ToolSet + 各个 Tool 的 function definition / parse / execute |
| `test_sandbox.py` | Sandbox + PersistentTerminal (timeout/interrupt/recovery) |
| `test_persistence.py` | Database + SQLiteLLMMetricsStore + Schema |
| `test_error_repair.py` | ToolMismatchError + InterruptedError + repair_transcripts |
| `test_shadow_repo.py` | ShadowRepo snapshot / restore / commit list |
