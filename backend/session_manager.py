"""会话管理器 — UUID 到 Agent 实例的映射。

每个会话持久化在 workspace/.tmp/{session_id}/：
- {session_id}.json  保存 session 元信息
- messages.jsonl     追加保存上下文消息和前端 history turn
"""

import shutil
import uuid
from pathlib import Path

from agent.llm import HelloAgentsLLM
from agent.react import ReActAgent
from agent.sandbox import SandBox
from agent.session_memory import SessionMemory


class SessionManager:
    def __init__(self, workspace: str) -> None:
        self._workspace = workspace
        self._sessions: dict[str, ReActAgent] = {}
        # shared LLM client across sessions (stateless)
        self._llm: HelloAgentsLLM | None = None
        self._tmp_dir = Path(workspace) / ".tmp"

    @property
    def llm(self) -> HelloAgentsLLM:
        if self._llm is None:
            self._llm = HelloAgentsLLM()
        return self._llm

    def create(self) -> str:
        sid = uuid.uuid4().hex[:12]
        memory = SessionMemory(self._workspace, sid)
        memory.ensure()
        self._sessions[sid] = self._new_agent(sid)
        return sid

    def list_ids(self) -> list[str]:
        ids = set(self._sessions.keys())
        ids.update(self._list_persisted_ids())
        return sorted(ids)

    def get(self, sid: str) -> ReActAgent:
        if sid not in self._sessions:
            if sid not in self._list_persisted_ids():
                raise KeyError(f"Session not found: {sid}")
            self._sessions[sid] = self._new_agent(sid)
        return self._sessions[sid]

    def get_history(self, sid: str) -> list[dict]:
        return self.get(sid).get_history()

    def _new_agent(self, sid: str) -> ReActAgent:
        sandbox = SandBox(self._workspace, session_id=sid)
        return ReActAgent(llm_client=self.llm, sandbox=sandbox, session_id=sid)

    def _list_persisted_ids(self) -> list[str]:
        if not self._tmp_dir.is_dir():
            return []
        result: list[str] = []
        for entry in self._tmp_dir.iterdir():
            if not entry.is_dir():
                continue
            sid = entry.name
            if (entry / f"{sid}.json").is_file():
                result.append(sid)
        return sorted(result)

    async def delete(self, sid: str) -> None:
        agent = self._sessions.pop(sid, None)
        if agent is not None:
            await agent.clear()
        session_dir = self._tmp_dir / sid
        if session_dir.is_dir():
            shutil.rmtree(session_dir)
