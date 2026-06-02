"""核心配置类型 — Agent 和 Session 的不可变配置。

── 对标 ──
- Rust: session/config.rs (SessionConfig, ToolSet, AccessPolicy)
- Rust: agent.rs (AgentConfig)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# ═══════════════════════════════════════════════════════════
# AgentConfig — LLM 调用配置
# ═══════════════════════════════════════════════════════════


@dataclass(frozen=True)
class AgentConfig:
    """一次 LLM 调用的配置（对标 Rust AgentConfig）。"""

    model_id: str = ""
    temperature: float = 0.0
    max_tokens: int | None = None

    def with_model(self, model_id: str) -> "AgentConfig":
        """返回使用指定模型的新配置。"""
        return AgentConfig(
            model_id=model_id,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )


# ═══════════════════════════════════════════════════════════
# ToolSet 预设 — 对标 Rust ToolSet enum
# ═══════════════════════════════════════════════════════════


class ToolSetPreset(str, Enum):
    """可用工具集预设。

    对标 Rust ToolSet enum:
    - ALL: 全部工具
    - MINIMAL: read_file, write, glob, grep
    - CODE_ONLY: read_file, write, edit, glob, grep, shell
    - REVIEW_ONLY: read_file, glob, grep
    - CUSTOM: 用户指定
    """

    ALL = "all"
    MINIMAL = "minimal"
    CODE_ONLY = "code_only"
    REVIEW_ONLY = "review_only"
    CUSTOM = "custom"

    def tool_names(self) -> list[str]:
        """返回该预设包含的工具名称列表。"""
        mapping: dict[ToolSetPreset, list[str]] = {
            ToolSetPreset.ALL: [
                "WebSearch",
                "WebFetch",
                "Grep",
                "Glob",
                "PyRepl",
                "Shell",
                "Read",
                "Write",
                "Edit",
                "LoadSkill",
                "SubAgent",
                "BrowserInspect",
                "TaskList",
                "TaskRewrite",
                "TaskUpdate",
            ],
            ToolSetPreset.MINIMAL: ["Read", "Write", "Glob", "Grep"],
            ToolSetPreset.CODE_ONLY: [
                "Read",
                "Write",
                "Edit",
                "Glob",
                "Grep",
                "Shell",
            ],
            ToolSetPreset.REVIEW_ONLY: ["Read", "Glob", "Grep"],
            ToolSetPreset.CUSTOM: [],
        }
        return mapping.get(self, [])


# ═══════════════════════════════════════════════════════════
# AccessPolicy — 对标 Rust AccessPolicy
# ═══════════════════════════════════════════════════════════


class Owner:
    """Session 的所有者。"""

    def __init__(self, kind: str, session_id: str | None = None):
        self.kind = kind  # "user" | "session"
        self.session_id = session_id

    @classmethod
    def user(cls) -> "Owner":
        return cls(kind="user")

    @classmethod
    def session(cls, session_id: str) -> "Owner":
        return cls(kind="session", session_id=session_id)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Owner):
            return False
        return self.kind == other.kind and self.session_id == other.session_id

    def __hash__(self) -> int:
        return hash((self.kind, self.session_id))


class Visibility(str, Enum):
    """Session 可见性。"""

    PRIVATE = "private"
    WHITELIST = "whitelist"
    PUBLIC = "public"


class InvokePermission(str, Enum):
    """谁可以 invoke 这个 Session。"""

    OWNER_ONLY = "owner_only"
    WHITELIST = "whitelist"
    ANY_AGENT = "any_agent"


class Lifecycle(str, Enum):
    """Session 生命周期。"""

    PERSISTENT = "persistent"
    EPHEMERAL = "ephemeral"
    TTL = "ttl"


@dataclass
class AccessPolicy:
    """Session 的访问控制策略。

    对标 Rust AccessPolicy。
    """

    owner: Owner = field(default_factory=Owner.user)
    visibility: Visibility = Visibility.PRIVATE
    invoke_permission: InvokePermission = InvokePermission.OWNER_ONLY
    lifecycle: Lifecycle = Lifecycle.PERSISTENT
    # 白名单列表（visibility/invoke_permission 为 whitelist 时使用）
    whitelist_ids: list[str] = field(default_factory=list)
    # TTL 空闲轮次（lifecycle 为 ttl 时使用）
    idle_turns: int = 5

    def can_invoke(self, caller_id: str | None) -> bool:
        """检查 caller 是否可以 invoke 此 Session。"""
        if self.invoke_permission == InvokePermission.ANY_AGENT:
            return True
        if self.invoke_permission == InvokePermission.OWNER_ONLY:
            if self.owner.kind == "user":
                return caller_id is None
            return caller_id == self.owner.session_id
        if self.invoke_permission == InvokePermission.WHITELIST:
            if caller_id is None:
                return False
            return caller_id in self.whitelist_ids
        return False

    def is_visible_to(self, seeker_id: str | None) -> bool:
        """检查 seeker 是否可以看到此 Session。"""
        if self.visibility == Visibility.PUBLIC:
            return True
        if self.visibility == Visibility.PRIVATE:
            if self.owner.kind == "user":
                return seeker_id is None
            return seeker_id == self.owner.session_id
        if self.visibility == Visibility.WHITELIST:
            if seeker_id is None:
                return False
            return seeker_id in self.whitelist_ids
        return False

    @classmethod
    def user_default(cls) -> "AccessPolicy":
        """用户主 Session 的默认访问策略。"""
        return cls(
            owner=Owner.user(),
            visibility=Visibility.PRIVATE,
            invoke_permission=InvokePermission.OWNER_ONLY,
            lifecycle=Lifecycle.PERSISTENT,
        )

    @classmethod
    def subagent(cls, parent_id: str) -> "AccessPolicy":
        """子 Agent 的默认访问策略。"""
        return cls(
            owner=Owner.session(parent_id),
            visibility=Visibility.PRIVATE,
            invoke_permission=InvokePermission.WHITELIST,
            whitelist_ids=[parent_id],
            lifecycle=Lifecycle.EPHEMERAL,
        )


# ═══════════════════════════════════════════════════════════
# SessionConfig — 对标 Rust SessionConfig
# ═══════════════════════════════════════════════════════════


@dataclass(frozen=True)
class SessionConfig:
    """Session 的不可变配置（创建时确定，对标 Rust SessionConfig）。

    对标 Rust session/config.rs。
    """

    name: str = ""
    model_id: str = ""
    preamble: str = ""
    tool_set_preset: ToolSetPreset = ToolSetPreset.ALL
    custom_tools: list[str] = field(default_factory=list)
    preloaded_skills: list[str] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)
    access: AccessPolicy = field(default_factory=AccessPolicy.user_default)

    def tool_names(self) -> list[str]:
        """返回实际工具名称列表。"""
        if self.tool_set_preset == ToolSetPreset.CUSTOM:
            return list(self.custom_tools)
        return self.tool_set_preset.tool_names()

    @classmethod
    def user_main(
        cls,
        name: str,
        model_id: str,
        preamble: str = "",
        preloaded_skills: list[str] | None = None,
        rules: list[str] | None = None,
    ) -> "SessionConfig":
        """用户主 Session 的工厂方法。"""
        return cls(
            name=name,
            model_id=model_id,
            preamble=preamble,
            tool_set_preset=ToolSetPreset.ALL,
            preloaded_skills=list(preloaded_skills or []),
            rules=list(rules or []),
            access=AccessPolicy.user_default(),
        )

    @classmethod
    def subagent(
        cls,
        parent_id: str,
        name: str,
        task: str,
        model_id: str,
        preamble: str = "",
        tool_set_preset: ToolSetPreset = ToolSetPreset.ALL,
    ) -> "SessionConfig":
        """子 Agent Session 的工厂方法。"""
        return cls(
            name=name,
            model_id=model_id,
            preamble=preamble,
            tool_set_preset=tool_set_preset,
            rules=[task],
            access=AccessPolicy.subagent(parent_id),
        )
