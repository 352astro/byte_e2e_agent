"""
PlanManager：维护 PlanItem 列表，提供计划重写与推进 API。

核心规则：
- 同时至多存在 1 个「活跃」条目（in_progress 或 failed）
- 当没有活跃条目时，自动将第一个 todo 推进为 in_progress
"""

from agent.tools.plan import PlanItem, State

# ── 状态展示标记 ──────────────────────────────────────────

_STATE_MARK: dict[str, str] = {
    "todo": "[ ]",
    "in_progress": "[>]",
    "done": "[x]",
    "failed": "[!]",
}

_ACTIVE_STATES = {"in_progress", "failed"}

# ── 合法转移表（仅向前，可跳步）──────────────────────────

_VALID_TRANSITIONS: dict[str, list[str]] = {
    "todo": ["in_progress", "done", "failed"],
    "failed": ["in_progress", "done"],
    "in_progress": ["done", "failed"],
    "done": [],
}


class PlanManager:
    """维护一个由 PlanItem 组成的有序计划列表。"""

    def __init__(self) -> None:
        self._items: list[PlanItem] = []

    # ── 查询 ──────────────────────────────────────────────

    def get_plan_string(self) -> str:
        """返回适合注入 LLM prompt 的计划文本。"""
        if not self._items:
            return "(No plan yet — consider using PlanRewrite to create one.)"

        lines: list[str] = []
        for i, item in enumerate(self._items, start=1):
            mark = _STATE_MARK.get(item.state, "[?]")
            lines.append(f"  {i:>2}. {mark} {item.description}")
        return "\n".join(lines)

    # ── 内部：自动推进 ────────────────────────────────────

    def _auto_advance(self) -> str | None:
        """
        若当前无活跃条目（in_progress / failed），
        自动将列表中第一个 todo 推进为 in_progress。
        返回追加到结果消息的文本，或 None。
        """
        active = [it for it in self._items if it.state in _ACTIVE_STATES]
        if active:
            return None

        for item in self._items:
            if item.state == "todo":
                item.state = "in_progress"
                return f"  (auto-started: '{item.description}' -> in_progress)"
        return None

    # ── 重写 ──────────────────────────────────────────────

    def rewrite(self, items: list[PlanItem]) -> str:
        """
        用全新列表覆盖当前计划（无前置条件，始终允许）。
        重写后自动将首个 todo 推进为 in_progress。
        """
        old_count = len(self._items)
        self._items = items

        # 自动开始第一个条目
        suffix = self._auto_advance() or ""

        return (
            f"Plan rewritten: {old_count} -> {len(items)} item(s)."
            f"{suffix}\n{self.get_plan_string()}"
        )

    # ── 推进 ──────────────────────────────────────────────

    def advance(self, new_state: State) -> str:
        """
        将第一个非 done 条目推进到 new_state。

        定位优先级：扫描列表，取第一个 state in
        (in_progress, failed, todo) 的条目。

        约束：同时至多 1 个活跃条目（in_progress + failed ≤ 1）。
        转移成功后若活跃条目归零，自动启动下一个 todo。
        """
        if not self._items:
            return "PlanAdvance failed: plan is empty. Use PlanRewrite to create one."

        # ── 找到第一个可推进的条目 ──
        target_idx: int | None = None
        for i, item in enumerate(self._items):
            if item.state in ("in_progress", "failed", "todo"):
                target_idx = i
                break

        if target_idx is None:
            return "PlanAdvance: all items are already done."

        item = self._items[target_idx]
        old_state = item.state

        # ── 校验转移合法性 ──
        allowed = _VALID_TRANSITIONS.get(old_state, [])
        if new_state not in allowed:
            return (
                f"PlanAdvance rejected: cannot transition "
                f"item #{target_idx + 1} from '{old_state}' to '{new_state}'. "
                f"Allowed: {allowed}"
            )

        # ── 约束：活跃条目 ≤ 1 ──
        if new_state in _ACTIVE_STATES:
            for other in self._items:
                if other is not item and other.state in _ACTIVE_STATES:
                    return (
                        f"PlanAdvance rejected: item "
                        f"'{other.description}' is already {other.state}. "
                        f"Only one active item (in_progress / failed) allowed at a time."
                    )

        # ── 执行转移 ──
        item.state = new_state

        # 若活跃条目归零，自动启动下一个
        suffix = self._auto_advance() or ""

        return (
            f"PlanAdvance: item #{target_idx + 1} "
            f"'{item.description}' {old_state} -> {new_state}.{suffix}"
        )
