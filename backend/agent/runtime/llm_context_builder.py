"""LLM context assembly helpers for AgentRuntime."""

from __future__ import annotations

from agent.core.workspace import Workspace
from agent.tools.skill import get_skill


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
    session_id: str,
    workspace: Workspace,
) -> list[dict]:
    """Return the OpenAI-compatible message context for one model step.

    All context is now stored as append-only messages in the session JSONL.
    This function simply loads the session and returns its LLM projection.
    """
    from agent.session import load_session

    session = load_session(session_id, workspace=workspace)
    return session.get_llm_context()
