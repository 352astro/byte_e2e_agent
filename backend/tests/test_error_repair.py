"""Tests for repair pipeline (agent/errors/repair.py).

Covers:
- _find_unpaired_messages: all branches
- repair_unpaired_tool_calls: pure function semantics
- repair_messages: orchestration + custom stages
"""

from __future__ import annotations

from agent.errors.repair import (
    _find_unpaired_messages,
    repair_messages,
    repair_unpaired_tool_calls,
)
from shared.types import (
    Message,
    MessageRole,
    ToolCall,
    ToolCallFunction,
    ToolExecutionStatus,
)

# ── helpers ──────────────────────────────────────────────


def _assistant_msg(id: str, turn_id: str, *tc_ids: str) -> Message:
    """Create an assistant Message with given tool_call ids."""
    msg = Message.assistant_message(id, turn_id)
    for tcid in tc_ids:
        msg.tool_calls.append(ToolCall(id=tcid, function=ToolCallFunction(name="TestTool")))
    msg.mark_complete()
    return msg


def _tool_msg(id: str, turn_id: str, tool_call_id: str, tool_name: str = "TestTool") -> Message:
    """Create a tool_result Message."""
    return Message.tool_message(
        id=id,
        turn_id=turn_id,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        result="ok",
    )


def _user_msg(id: str, turn_id: str) -> Message:
    return Message.user_message(id, turn_id, "hello")


# ═══════════════════════════════════════════════════════════
# _find_unpaired_messages
# ═══════════════════════════════════════════════════════════


class TestFindUnpairedMessages:
    def test_empty_list_returns_empty(self):
        assert _find_unpaired_messages([]) == []

    def test_no_assistant_returns_empty(self):
        msgs = [
            _user_msg("u1", "t1"),
            _tool_msg("r1", "t1", "tc1"),
        ]
        assert _find_unpaired_messages(msgs) == []

    def test_assistant_no_tool_calls_returns_empty(self):
        msgs = [
            _user_msg("u1", "t1"),
            Message.assistant_message("a1", "t1"),
        ]
        msgs[1].mark_complete()
        assert _find_unpaired_messages(msgs) == []

    def test_assistant_all_tool_calls_paired_returns_empty(self):
        msgs = [
            _user_msg("u1", "t1"),
            _assistant_msg("a1", "t1", "tc1", "tc2"),
            _tool_msg("r1", "t1", "tc1"),
            _tool_msg("r2", "t1", "tc2"),
        ]
        assert _find_unpaired_messages(msgs) == []

    def test_one_unpaired_tool_call_generates_repair(self):
        msgs = [
            _user_msg("u1", "t1"),
            _assistant_msg("a1", "t1", "tc1", "tc2"),
            _tool_msg("r1", "t1", "tc1"),
            # tc2 is unpaired
        ]
        repairs = _find_unpaired_messages(msgs)
        assert len(repairs) == 1
        r = repairs[0]
        assert r.role == MessageRole.TOOL
        assert r.tool_call_id == "tc2"
        assert r.tool_name == "TestTool"
        assert "interrupted" in r.tool_result.lower()
        assert r.tool_status == ToolExecutionStatus.INTERRUPTED.value
        assert r.tool_status_source == "repair"
        assert r.tool_status_reason == "user_interrupted_before_execution"
        assert r.turn_id == "t1"  # inherits from assistant

    def test_multiple_unpaired_tool_calls_generate_repairs(self):
        msgs = [
            _user_msg("u1", "t1"),
            _assistant_msg("a1", "t1", "tc1", "tc2", "tc3"),
            # none paired
        ]
        repairs = _find_unpaired_messages(msgs)
        assert len(repairs) == 3
        ids = {r.tool_call_id for r in repairs}
        assert ids == {"tc1", "tc2", "tc3"}

    def test_only_last_assistant_processed(self):
        """Only the most recent assistant's unpaired calls get repaired."""
        msgs = [
            _user_msg("u1", "t1"),
            _assistant_msg("a1", "t1", "old_tc"),  # older, unpaired
            _tool_msg("r1", "t1", "old_tc"),  # now paired
            _user_msg("u2", "t1"),
            _assistant_msg("a2", "t1", "new_tc"),  # newer, unpaired
        ]
        repairs = _find_unpaired_messages(msgs)
        assert len(repairs) == 1
        assert repairs[0].tool_call_id == "new_tc"

    def test_tool_call_empty_id_skipped(self):
        msgs = [
            _user_msg("u1", "t1"),
            _assistant_msg("a1", "t1", "", "tc2"),  # empty id skipped
        ]
        repairs = _find_unpaired_messages(msgs)
        assert len(repairs) == 1
        assert repairs[0].tool_call_id == "tc2"

    def test_paired_across_multiple_assistants(self):
        """A tool_result pairs with its tool_call regardless of assistant order."""
        msgs = [
            _assistant_msg("a1", "t1", "tc1"),
            _tool_msg("r1", "t1", "tc1"),
            _assistant_msg("a2", "t1", "tc2"),  # only last checked
        ]
        repairs = _find_unpaired_messages(msgs)
        assert len(repairs) == 1
        assert repairs[0].tool_call_id == "tc2"

    def test_tool_msg_without_tool_call_id_not_counted(self):
        """TOOL message without tool_call_id does not mark anything as paired."""
        msgs = [
            _assistant_msg("a1", "t1", "tc1"),
            Message(
                id="r1",
                turn_id="t1",
                role=MessageRole.TOOL,
                status="complete",
                tool_result="orphan result",
                # no tool_call_id set
            ),
        ]
        repairs = _find_unpaired_messages(msgs)
        assert len(repairs) == 1  # tc1 still counted as unpaired

    def test_user_messages_ignored(self):
        msgs = [
            _user_msg("u1", "t1"),
            _user_msg("u2", "t1"),
            _assistant_msg("a1", "t1", "tc1"),  # unpaired
        ]
        repairs = _find_unpaired_messages(msgs)
        assert len(repairs) == 1

    def test_error_assistant_not_matched(self):
        """An error Message (role=ASSISTANT with error) has no tool_calls, ignored."""
        msg = Message.error_message("e1", "t1", "something went wrong")
        msgs = [
            _user_msg("u1", "t1"),
            _assistant_msg("a1", "t1", "tc1"),
            msg,
        ]
        repairs = _find_unpaired_messages(msgs)
        # msg is assistant but has no tool_calls — last assistant with tc is a1
        assert len(repairs) == 1
        assert repairs[0].tool_call_id == "tc1"

    def test_each_repair_has_unique_id(self):
        msgs = [
            _assistant_msg("a1", "t1", "tc1", "tc2", "tc3"),
        ]
        repairs = _find_unpaired_messages(msgs)
        ids = {r.id for r in repairs}
        assert len(ids) == 3  # all unique


# ═══════════════════════════════════════════════════════════
# repair_unpaired_tool_calls
# ═══════════════════════════════════════════════════════════


class TestRepairUnpairedToolCalls:
    def test_no_repairs_needed_returns_copy(self):
        msgs = [
            _user_msg("u1", "t1"),
            _assistant_msg("a1", "t1", "tc1"),
            _tool_msg("r1", "t1", "tc1"),
        ]
        result = repair_unpaired_tool_calls(msgs)
        assert len(result) == 3
        assert result is not msgs  # returns new list

    def test_repairs_needed_appends_repairs(self):
        msgs = [
            _user_msg("u1", "t1"),
            _assistant_msg("a1", "t1", "tc1"),
        ]
        result = repair_unpaired_tool_calls(msgs)
        assert len(result) == 3  # user + assistant + repair
        assert result[2].tool_call_id == "tc1"

    def test_original_list_not_modified(self):
        msgs = [
            _assistant_msg("a1", "t1", "tc1"),
        ]
        original_len = len(msgs)
        repair_unpaired_tool_calls(msgs)
        assert len(msgs) == original_len  # unchanged

    def test_empty_list_returns_empty_list(self):
        result = repair_unpaired_tool_calls([])
        assert result == []


# ═══════════════════════════════════════════════════════════
# repair_messages (orchestrator)
# ═══════════════════════════════════════════════════════════


class TestRepairMessages:
    def test_default_stages_repair_unpaired(self):
        msgs = [
            _assistant_msg("a1", "t1", "tc1"),
        ]
        result = repair_messages(msgs)
        assert len(result) == 2
        assert result[1].tool_call_id == "tc1"

    def test_custom_stage(self):
        msgs = [
            _user_msg("u1", "t1"),
        ]

        def add_error(messages: list[Message]) -> list[Message]:
            return messages + [Message.error_message("err", "t1", "custom error")]

        result = repair_messages(msgs, add_error)
        assert len(result) == 2
        assert result[1].error == "custom error"

    def test_multiple_custom_stages_in_sequence(self):
        msgs: list[Message] = []

        def stage1(ms: list[Message]) -> list[Message]:
            return ms + [_user_msg("u1", "t1")]

        def stage2(ms: list[Message]) -> list[Message]:
            return ms + [_assistant_msg("a1", "t1", "tc1")]

        result = repair_messages(msgs, stage1, stage2)
        assert len(result) == 2
        assert result[0].role == MessageRole.USER
        assert result[1].role == MessageRole.ASSISTANT

    def test_empty_messages_default_stages(self):
        result = repair_messages([])
        assert result == []

    def test_no_stages_uses_default(self):
        """Explicitly passing no stages should use default."""
        msgs = [
            _assistant_msg("a1", "t1", "tc1"),
        ]
        result = repair_messages(msgs)  # no *stages
        assert len(result) == 2  # default repair kicked in

    def test_original_not_modified(self):
        msgs = [
            _assistant_msg("a1", "t1", "tc1"),
        ]
        original_len = len(msgs)
        repair_messages(msgs)
        assert len(msgs) == original_len

    def test_compat_alias_repair_messages(self):
        """Verify the backward-compat alias exists and works."""
        from agent.errors.repair import repair_messages

        msgs = [
            _assistant_msg("a1", "t1", "tc1"),
        ]
        result = repair_messages(msgs)
        assert len(result) == 2


# ═══════════════════════════════════════════════════════════
# Integration: simulate interrupt scenario
# ═══════════════════════════════════════════════════════════


class TestRepairInterruptScenario:
    """End-to-end: simulate a real interrupt mid-turn."""

    def test_interrupt_after_assistant_before_any_tool(self):
        """User interrupted after LLM returned tool_calls but before any executed."""
        msgs = [
            _user_msg("u1", "turn1"),
            _assistant_msg("a1", "turn1", "tc_shell", "tc_read", "tc_write"),
            # interrupt happened here — no tool results
        ]
        repaired = repair_messages(msgs)
        assert len(repaired) == 5  # 2 original + 3 repairs
        tool_repaired = [m for m in repaired if m.role == MessageRole.TOOL]
        assert len(tool_repaired) == 3
        for tr in tool_repaired:
            assert "interrupted" in tr.tool_result.lower()

    def test_interrupt_after_one_tool_done(self):
        """Interrupt after Shell executed but before Read and Write."""
        msgs = [
            _user_msg("u1", "turn1"),
            _assistant_msg("a1", "turn1", "tc_shell", "tc_read", "tc_write"),
            _tool_msg("r1", "turn1", "tc_shell"),
            # interrupt here — tc_read and tc_write unpaired
        ]
        repaired = repair_messages(msgs)
        assert len(repaired) == 5  # 3 original + 2 repairs
        tool_repaired = [m for m in repaired if m.role == MessageRole.TOOL]
        assert len(tool_repaired) == 3  # 1 real + 2 repair
        repair_tcids = {
            m.tool_call_id
            for m in repaired
            if m.role == MessageRole.TOOL and "interrupted" in m.tool_result
        }
        assert repair_tcids == {"tc_read", "tc_write"}

    def test_interrupt_multi_turn_only_last(self):
        """Only the last assistant's unpaired calls are repaired."""
        msgs = [
            # Turn 1: complete
            _user_msg("u1", "turn1"),
            _assistant_msg("a1", "turn1", "tc1"),
            _tool_msg("r1", "turn1", "tc1"),
            # Turn 2: interrupted
            _user_msg("u2", "turn2"),
            _assistant_msg("a2", "turn2", "tc2", "tc3"),
            # interrupt — only tc2, tc3 unpaired
        ]
        repaired = repair_messages(msgs)
        # tc1 was paired in turn1, tc2+tc3 from turn2 get repairs
        repair_tcids = {
            m.tool_call_id
            for m in repaired
            if m.role == MessageRole.TOOL and "interrupted" in m.tool_result
        }
        assert repair_tcids == {"tc2", "tc3"}
        # tc1's tool_result is the real one
        real_results = [
            m for m in repaired if m.role == MessageRole.TOOL and m.tool_call_id == "tc1"
        ]
        assert len(real_results) == 1
        assert real_results[0].tool_result == "ok"

    def test_repairs_preserve_turn_id(self):
        """Repair Messages inherit the turn_id of their assistant."""
        msgs = [
            _user_msg("u1", "turn_abc"),
            _assistant_msg("a1", "turn_abc", "tc1"),
        ]
        repaired = repair_messages(msgs)
        repair = repaired[-1]
        assert repair.turn_id == "turn_abc"
