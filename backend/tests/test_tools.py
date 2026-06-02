"""Unit tests for tool registration and ToolSet (new StructuredTool architecture).

Tests cover:
- ToolRegistry: register, get, get_all, openai_tools
- ToolSet: construction from registry, parse, without, openai_tools
- StructuredTool handler smoke tests
"""

from __future__ import annotations

import json
import asyncio

import pytest

from agent.tools import tool_registry
from agent.tools.registry import ToolRegistry
from agent.tools.toolset import ToolSet

# ═══════════════════════════════════════════════════════════════
#  ToolRegistry tests
# ═══════════════════════════════════════════════════════════════


class TestToolRegistry:
    def test_register_and_get(self):
        reg = ToolRegistry()
        tool = tool_registry.get("Shell")
        assert tool is not None
        reg.register(tool)
        assert reg.get("Shell") is tool

    def test_get_unknown_returns_none(self):
        reg = ToolRegistry()
        assert reg.get("Nonexistent") is None

    def test_contains(self):
        reg = ToolRegistry()
        reg.register(tool_registry.get("Shell"))
        assert "Shell" in reg
        assert "Read" not in reg

    def test_tool_names(self):
        reg = ToolRegistry()
        reg.register(tool_registry.get("Shell"))
        reg.register(tool_registry.get("Read"))
        assert set(reg.tool_names) == {"Shell", "Read"}

    def test_openai_tools_returns_list_of_dicts(self):
        reg = ToolRegistry()
        reg.register(tool_registry.get("Shell"))
        reg.register(tool_registry.get("Read"))
        tools = reg.openai_tools()
        assert isinstance(tools, list)
        assert len(tools) == 2
        for item in tools:
            assert item["type"] == "function"
            assert "function" in item
            assert "name" in item["function"]
            assert "parameters" in item["function"]

    def test_global_registry_has_all_tools(self):
        tools = tool_registry.get_all()
        assert len(tools) >= 14
        names = {t.name for t in tools}
        assert "Shell" in names
        assert "ListDir" in names
        assert "Read" in names
        assert "Write" in names
        assert "Grep" in names
        assert "SubAgent" in names


# ═══════════════════════════════════════════════════════════════
#  ToolSet tests
# ═══════════════════════════════════════════════════════════════


class TestToolSetConstruction:
    def test_construction_with_registry_succeeds(self):
        ts = ToolSet(tool_registry)
        assert ts is not None
        assert len(ts.tools) > 0

    def test_construction_with_specific_names(self):
        ts = ToolSet(tool_registry, "Shell", "Read", "Write")
        assert len(ts.tools) == 3
        names = {t.name for t in ts.tools}
        assert names == {"Shell", "Read", "Write"}

    def test_construction_with_unknown_name_raises(self):
        with pytest.raises(KeyError, match="Unknown tool"):
            ToolSet(tool_registry, "NonexistentTool")

    def test_empty_registry_raises(self):
        empty = ToolRegistry()
        with pytest.raises(ValueError, match="at least one tool"):
            ToolSet(empty)


class TestToolSetOpenaiTools:
    def test_returns_list_of_dicts(self):
        ts = ToolSet(tool_registry, "Shell", "Read")
        tools = ts.openai_tools
        assert isinstance(tools, list)
        assert len(tools) == 2
        for item in tools:
            assert isinstance(item, dict)

    def test_each_tool_has_type_function(self):
        ts = ToolSet(tool_registry, "Shell", "Read", "Write")
        for tool_def in ts.openai_tools:
            assert tool_def["type"] == "function"

    def test_each_tool_has_function_key(self):
        ts = ToolSet(tool_registry, "Shell", "Read", "Write")
        for tool_def in ts.openai_tools:
            assert "function" in tool_def

    def test_each_function_has_name(self):
        ts = ToolSet(tool_registry)
        for tool_def in ts.openai_tools:
            assert "name" in tool_def["function"]
            assert isinstance(tool_def["function"]["name"], str)
            assert len(tool_def["function"]["name"]) > 0

    def test_each_function_has_parameters(self):
        ts = ToolSet(tool_registry)
        for tool_def in ts.openai_tools:
            assert "parameters" in tool_def["function"]
            params = tool_def["function"]["parameters"]
            assert isinstance(params, dict)
            assert params.get("type") == "object"

    def test_shell_definition_has_command_required(self):
        ts = ToolSet(tool_registry, "Shell")
        params = ts.openai_tools[0]["function"]["parameters"]
        assert "command" in params.get("required", [])
        assert "command" in params.get("properties", {})

    def test_all_tools_have_non_empty_name(self):
        ts = ToolSet(tool_registry)
        for tool_def in ts.openai_tools:
            assert len(tool_def["function"]["name"]) > 0


class TestToolSetParse:
    def test_parse_returns_tool_and_args(self):
        ts = ToolSet(tool_registry, "Shell", "Read")
        tool, args = ts.parse("Shell", json.dumps({"command": "echo hello"}))
        assert tool.name == "Shell"
        assert args == {"command": "echo hello"}

    def test_parse_read_with_path(self):
        ts = ToolSet(tool_registry, "Read")
        tool, args = ts.parse("Read", json.dumps({"path": "test.py"}))
        assert tool.name == "Read"
        assert args == {"path": "test.py"}

    def test_parse_write_with_path_and_content(self):
        ts = ToolSet(tool_registry, "Write")
        tool, args = ts.parse("Write", json.dumps({"path": "f.py", "content": "hello"}))
        assert tool.name == "Write"
        assert args == {"path": "f.py", "content": "hello"}

    def test_parse_with_unknown_name_raises_key_error(self):
        ts = ToolSet(tool_registry, "Shell")
        with pytest.raises(KeyError, match="Unknown tool"):
            ts.parse("Nonexistent", "{}")

    def test_parse_with_invalid_json_raises(self):
        ts = ToolSet(tool_registry, "Shell")
        with pytest.raises(ValueError, match="Invalid JSON"):
            ts.parse("Shell", "not json")

    def test_parse_shell_defaults_timeout_ms(self):
        ts = ToolSet(tool_registry, "Shell")
        tool, args = ts.parse("Shell", json.dumps({"command": "ls"}))
        assert args == {"command": "ls"}


class TestToolSetWithout:
    def test_without_removes_specified_tool(self):
        ts = ToolSet(tool_registry, "Shell", "Read", "Write")
        ts2 = ts.without("Shell")
        assert len(ts2.tools) == 2
        names = {t.name for t in ts2.tools}
        assert names == {"Read", "Write"}

    def test_without_multiple_tools(self):
        ts = ToolSet(tool_registry, "Shell", "Read", "Write", "Grep")
        ts2 = ts.without("Shell", "Read")
        names = {t.name for t in ts2.tools}
        assert names == {"Write", "Grep"}

    def test_without_preserves_openai_tools_structure(self):
        ts = ToolSet(tool_registry, "Shell", "Read")
        ts2 = ts.without("Shell")
        tools = ts2.openai_tools
        assert len(tools) == 1
        assert tools[0]["type"] == "function"

    def test_without_all_tools_raises(self):
        ts = ToolSet(tool_registry, "Shell")
        with pytest.raises(ValueError, match="would be empty"):
            ts.without("Shell")


class TestToolSetContains:
    def test_contains_returns_true_for_member(self):
        ts = ToolSet(tool_registry, "Shell", "Read")
        assert "Shell" in ts

    def test_contains_returns_false_for_non_member(self):
        ts = ToolSet(tool_registry, "Shell")
        assert "Read" not in ts

    def test_contains_after_without(self):
        ts = ToolSet(tool_registry, "Shell", "Read")
        ts2 = ts.without("Shell")
        assert "Shell" not in ts2
        assert "Read" in ts2


class TestToolSetRepr:
    def test_repr_includes_tool_names(self):
        ts = ToolSet(tool_registry, "Shell", "Read")
        r = repr(ts)
        assert "ToolSet" in r
        assert "Shell" in r
        assert "Read" in r


# ═══════════════════════════════════════════════════════════════
#  StructuredTool handler smoke tests
# ═══════════════════════════════════════════════════════════════


class TestToolHandlers:
    """Smoke tests: verify tool handlers execute without errors."""

    @pytest.mark.asyncio
    async def test_shell_handler(self, tmp_path):
        from agent.core.workspace import Workspace

        ws = Workspace(tmp_path)
        tool = tool_registry.get("Shell")
        result = await tool.coroutine(command="echo hi", ws=ws)
        assert "hi" in result

    @pytest.mark.asyncio
    async def test_shell_handler_nonzero_exit(self, tmp_path):
        from agent.core.workspace import Workspace

        ws = Workspace(tmp_path)
        tool = tool_registry.get("Shell")
        result = await tool.coroutine(command="exit 7", ws=ws)
        assert "exit code: 7" in result

    @pytest.mark.asyncio
    async def test_shell_handler_timeout(self, tmp_path):
        from agent.core.workspace import Workspace

        ws = Workspace(tmp_path)
        tool = tool_registry.get("Shell")
        result = await tool.coroutine(command="sleep 2", timeout_ms=1000, ws=ws)
        assert "timed out" in result.lower()

    @pytest.mark.asyncio
    async def test_shell_handler_cwd(self, tmp_path):
        from agent.core.workspace import Workspace

        (tmp_path / "sub").mkdir()
        ws = Workspace(tmp_path)
        tool = tool_registry.get("Shell")
        result = await tool.coroutine(command="pwd", cwd="sub", ws=ws)
        assert str(tmp_path / "sub") in result

    @pytest.mark.asyncio
    async def test_shell_handler_truncates_output(self, tmp_path):
        from agent.core.workspace import Workspace

        ws = Workspace(tmp_path)
        tool = tool_registry.get("Shell")
        result = await tool.coroutine(
            command="printf 1234567890",
            max_output_bytes=5,
            ws=ws,
        )
        assert result.startswith("12345")
        assert "output truncated" in result

    @pytest.mark.asyncio
    async def test_shell_handler_nohup_background_survives(self, tmp_path):
        from agent.core.workspace import Workspace

        ws = Workspace(tmp_path)
        tool = tool_registry.get("Shell")
        result = await tool.coroutine(
            command="nohup sh -c 'sleep 0.2; echo done > nohup.out' >/dev/null 2>&1 &",
            timeout_ms=1000,
            ws=ws,
        )
        await asyncio.sleep(0.5)
        assert "timed out" not in result.lower()
        assert (tmp_path / "nohup.out").read_text().strip() == "done"

    @pytest.mark.asyncio
    async def test_shell_handler_interrupt(self, tmp_path):
        from agent.core.workspace import Workspace

        ws = Workspace(tmp_path)
        tool = tool_registry.get("Shell")
        interrupt_event = asyncio.Event()

        async def trigger_interrupt():
            await asyncio.sleep(0.1)
            interrupt_event.set()

        task = asyncio.create_task(trigger_interrupt())
        result = await tool.coroutine(
            command="sleep 5",
            timeout_ms=5000,
            ws=ws,
            interrupt_event=interrupt_event,
        )
        await task
        assert "interrupted" in result.lower()

    @pytest.mark.asyncio
    async def test_read_handler(self):
        from unittest.mock import AsyncMock

        ws = AsyncMock()
        ws.read_file.return_value = "line1\nline2\nline3"
        tool = tool_registry.get("Read")
        result = await tool.coroutine(path="test.py", ws=ws)
        assert "line1" in result

    @pytest.mark.asyncio
    async def test_listdir_handler(self, tmp_path):
        from agent.core.workspace import Workspace

        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("print('hi')", encoding="utf-8")
        (tmp_path / ".hidden").write_text("secret", encoding="utf-8")

        ws = Workspace(tmp_path)
        tool = tool_registry.get("ListDir")
        result = await tool.coroutine(path=".", recursive=True, ws=ws)

        assert "src/" in result
        assert "app.py" in result
        assert ".hidden" not in result

    @pytest.mark.asyncio
    async def test_write_handler(self):
        from unittest.mock import AsyncMock

        ws = AsyncMock()
        ws.write_file.return_value = "Successfully wrote test.py"
        tool = tool_registry.get("Write")
        result = await tool.coroutine(path="test.py", content="data", ws=ws)
        assert "Successfully" in result

    @pytest.mark.asyncio
    async def test_subagent_handler_returns_error(self):
        tool = tool_registry.get("SubAgent")
        result = await tool.coroutine()
        assert "must be dispatched" in result

    @pytest.mark.asyncio
    async def test_browser_inspect_handler_returns_error(self):
        tool = tool_registry.get("BrowserInspect")
        result = await tool.coroutine()
        assert "must be dispatched" in result


# ═══════════════════════════════════════════════════════════════
#  Integration
# ═══════════════════════════════════════════════════════════════


class TestIntegration:
    def test_full_roundtrip(self):
        ts = ToolSet(tool_registry)
        tools = ts.openai_tools
        for tool_def in tools[:5]:
            name = tool_def["function"]["name"]
            tool, _args = ts.parse(name, "{}")
            assert tool.name == name

    def test_openai_tools_no_duplicate_names(self):
        ts = ToolSet(tool_registry)
        names = [t["function"]["name"] for t in ts.openai_tools]
        assert len(names) == len(set(names))

    def test_without_chained(self):
        ts = ToolSet(tool_registry, "Shell", "Read", "Write", "Grep")
        ts2 = ts.without("Shell").without("Grep")
        names = {t.name for t in ts2.tools}
        assert names == {"Read", "Write"}
