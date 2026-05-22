"""会话管理器 — UUID 到 Agent 实例的映射。

支持启动时从 workspace/.tmp/sessions.json 恢复会话，
以及结束时持久化（过渡方案，不修改 agent 内部逻辑）。
"""

import json
import uuid
from dataclasses import asdict
from pathlib import Path

from agent.llm import HelloAgentsLLM
from agent.react import ReActAgent
from agent.sandbox import SandBox
from agent.turn import ToolStep, Turn


class SessionManager:
    def __init__(self, workspace: str) -> None:
        self._workspace = workspace
        self._sessions: dict[str, ReActAgent] = {}
        # shared LLM client across sessions (stateless)
        self._llm: HelloAgentsLLM | None = None
        self._save_path = Path(workspace) / ".tmp" / "sessions.json"
        self._load()

    @property
    def llm(self) -> HelloAgentsLLM:
        if self._llm is None:
            self._llm = HelloAgentsLLM()
        return self._llm

    def create(self) -> str:
        sid = uuid.uuid4().hex[:12]
        sandbox = SandBox(self._workspace)
        agent = ReActAgent(llm_client=self.llm, sandbox=sandbox)
        self._sessions[sid] = agent
        return sid

    def list_ids(self) -> list[str]:
        return list(self._sessions.keys())

    def get(self, sid: str) -> ReActAgent:
        if sid not in self._sessions:
            raise KeyError(f"Session not found: {sid}")
        return self._sessions[sid]

    def get_history(self, sid: str) -> list[dict]:
        return self.get(sid).get_history()

    # ── persistence ──────────────────────────────────

    def save(self) -> None:
        """公开保存入口——持久化所有会话到 workspace/.tmp/sessions.json。"""
        self._save()

    def _save(self) -> None:
        data: dict[str, dict] = {}
        for sid, agent in self._sessions.items():
            data[sid] = {
                "system_msg": agent._system_msg,
                "messages": agent._messages,
                "turns": [asdict(t) for t in agent._turns],
            }
        self._save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._save_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load(self) -> None:
        if not self._save_path.exists():
            return
        try:
            with open(self._save_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return

        for sid, sdata in data.items():
            sandbox = SandBox(self._workspace)
            agent = ReActAgent(llm_client=self.llm, sandbox=sandbox)
            agent._system_msg = sdata.get("system_msg")
            agent._messages = sdata.get("messages", [])
            agent._turns = [
                Turn(
                    role=t["role"],
                    question=t.get("question", ""),
                    reasoning=t.get("reasoning", ""),
                    content=t.get("content", ""),
                    tool_calls=[
                        ToolStep(
                            name=tc["name"],
                            arguments=tc["arguments"],
                            result=tc.get("result"),
                        )
                        for tc in t.get("tool_calls", [])
                    ],
                    finish_answer=t.get("finish_answer"),
                )
                for t in sdata.get("turns", [])
            ]
            self._sessions[sid] = agent

    async def delete(self, sid: str) -> None:
        agent = self._sessions.pop(sid, None)
        if agent is not None:
            await agent.clear()
        self._save()
