"""LLM context assembly helpers for AgentRuntime."""

from __future__ import annotations

from agent.core.prompts import SYSTEM_PROMPT
from agent.core.workspace import Workspace
from agent.session.entry import SessionEntry
from agent.tools.shell import get_platform_hint
from agent.tools.skill import get_skill, skill_context_message
from agent.tools.task import task_context_message
from app.core.config import AGENT_DATA_DIR


def build_preloaded_skills_context(with_skills: list[str]) -> str:
    if not with_skills:
        return ""

    parts: list[str] = []
    for skill_name in with_skills:
        skill = get_skill(skill_name)
        if skill is None:
            continue
        parts.append(
            f"[SKILL: {skill_name}]\n\n"
            "The following skill methodology is pre-loaded into your context. "
            "Follow it exactly.\n\n"
            f"{skill.read()}"
        )
    return "\n\n".join(parts)


def build_llm_messages(
    *,
    entry: SessionEntry,
    workspace: Workspace,
    session_id: str,
    injected_context: list[dict] | None = None,
) -> list[dict]:
    """Build the OpenAI-compatible message context for one model step."""
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": f"## Platform\n{get_platform_hint()}"},
        {
            "role": "system",
            "content": (
                f"## System Directory\n"
                f"The `{AGENT_DATA_DIR}/` directory at the project root is managed by "
                f"the system for internal storage. "
                f"Do NOT read, edit, create, or delete files under `{AGENT_DATA_DIR}`."
            ),
        },
        skill_context_message(),
        task_context_message(workspace, session_id=session_id),
    ]

    preloaded_skill_context = build_preloaded_skills_context(
        entry.config.preloaded_skills
    )
    if preloaded_skill_context:
        messages.append({"role": "system", "content": preloaded_skill_context})
    if entry.config.preamble:
        messages.append({"role": "system", "content": entry.config.preamble})
    if entry.config.rules:
        messages.append(
            {
                "role": "system",
                "content": "## Session Rules\n"
                + "\n".join(f"- {rule}" for rule in entry.config.rules),
            }
        )

    from agent.session import load_session

    session = load_session(session_id, ws=workspace)
    messages.extend(session.get_llm_context())

    if injected_context:
        messages.extend(injected_context)
    return messages
