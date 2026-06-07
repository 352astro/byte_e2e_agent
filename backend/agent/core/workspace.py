"""Workspace — 工作区路径管理 + 纯 I/O 代理。

── 职责 ──
- 定义工作区根目录
- 管理系统内部目录（PROJECT_ROOT/.agent/workspaces/{uuid}/）
- Session 独享目录和文件路径
- 安全路径解析（防越界）
- Shell 执行（临时子进程）
- 文件读写

── 目录结构 ──
    PROJECT_ROOT/
      .agent/
        workspaces/{uuid}/
          sessions/{session_id}/
            session.db / config.json / tasks.json / messages.jsonl
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import signal
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from agent.core.config import SessionConfig

SESSION_ID_PATTERN = r"^[a-z0-9][a-z0-9-]*$"
_SESSION_ID_RE = re.compile(SESSION_ID_PATTERN)


def is_valid_session_id(session_id: str) -> bool:
    return bool(_SESSION_ID_RE.fullmatch(session_id))


def validate_session_id(session_id: str) -> None:
    if not is_valid_session_id(session_id):
        raise ValueError(
            f"Invalid session_id: {session_id!r}. "
            "Only lowercase letters, digits, and hyphens are allowed; "
            "the first character must be lowercase alphanumeric."
        )


# ═══════════════════════════════════════════════════════════
# Workspace
# ═══════════════════════════════════════════════════════════


class Workspace:
    """工作区 = 路径管理 + 纯 I/O 执行。无状态、不持终端、不做安全检查。"""

    def __init__(self, root: str | Path, workspace_uuid: str) -> None:
        self.root = Path(root).expanduser().resolve()
        self.uuid = workspace_uuid
        os.makedirs(self.root, exist_ok=True)

    # ═══════════════════════════════════════════════════════
    # 路径管理
    # ═══════════════════════════════════════════════════════

    def agent_dir(self) -> Path:
        from agent.paths import workspace_data_dir

        return workspace_data_dir(self.uuid)

    def sessions_dir(self) -> Path:
        return self.agent_dir() / "sessions"

    def session_dir(self, session_id: str) -> Path:
        validate_session_id(session_id)
        return self.sessions_dir() / session_id

    def session_db_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "session.db"

    def session_config_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "config.json"

    def tasks_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "tasks.json"

    def messages_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "messages.jsonl"

    def ensure_dirs(self, session_id: str) -> Path:
        d = self.session_dir(session_id)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save_session_config(self, session_id: str, config: SessionConfig) -> None:
        from dataclasses import asdict

        self.ensure_dirs(session_id)
        path = self.session_config_path(session_id)
        data = asdict(config)
        data["tool_set_preset"] = config.tool_set_preset.value
        access = data["access"]
        access["visibility"] = config.access.visibility.value
        access["invoke_permission"] = config.access.invoke_permission.value
        access["lifecycle"] = config.access.lifecycle.value
        access["owner"] = {
            "kind": config.access.owner.kind,
            "session_id": config.access.owner.session_id,
        }
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def load_session_config(self, session_id: str) -> dict | None:
        path = self.session_config_path(session_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError, OSError:
            return None

    def list_session_ids(self) -> list[str]:
        d = self.sessions_dir()
        if not d.exists():
            return []
        return sorted(
            e.name for e in d.iterdir() if e.is_dir() and _SESSION_ID_RE.fullmatch(e.name)
        )

    # ═══════════════════════════════════════════════════════
    # 路径安全
    # ═══════════════════════════════════════════════════════

    def resolve(
        self,
        relpath: str,
        *,
        external_mode: Literal["readonly", "readwrite"] | None = None,
    ) -> Path:
        """安全解析，防越界。"""
        resolved = (self.root / relpath).resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError:
            if external_mode is not None:
                from agent.utils import sandbox

                if sandbox.is_path_allowed(
                    str(resolved),
                    external_mode,
                    workspace_uuid=self.uuid,
                ):
                    return resolved
            raise PermissionError(
                "Path is outside workspace and not allowed by shell sandbox "
                f"settings: input={relpath!r}, resolved={resolved}, "
                f"workspace={self.root}"
            ) from None
        return resolved

    def resolve_path(self, relpath: str) -> str:
        return str(self.resolve(relpath))

    def is_safe_path(self, path: str | Path) -> bool:
        try:
            Path(path).resolve().relative_to(self.root)
            return True
        except ValueError:
            return False

    # ═══════════════════════════════════════════════════════
    # Shell 执行（临时子进程，无持久终端）
    # ═══════════════════════════════════════════════════════

    async def run_shell(
        self,
        command: str,
        timeout_ms: int = 30000,
        interrupt_event: asyncio.Event | None = None,
    ) -> str:
        """执行 shell 命令，返回 stdout+stderr。超时发送 SIGKILL。"""
        proc = None
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(self.root),
                start_new_session=True,
            )
            communicate_task = asyncio.create_task(proc.communicate())
            wait_tasks = {communicate_task}
            interrupt_task = None
            if interrupt_event is not None:
                interrupt_task = asyncio.create_task(interrupt_event.wait())
                wait_tasks.add(interrupt_task)

            done, pending = await asyncio.wait(
                wait_tasks,
                timeout=timeout_ms / 1000.0,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if interrupt_task is not None and interrupt_task in done:
                self._kill_process_group(proc)
                await proc.wait()
                communicate_task.cancel()
                return "[Command interrupted]"
            if communicate_task not in done:
                self._kill_process_group(proc)
                await proc.wait()
                communicate_task.cancel()
                return f"[Command timed out after {timeout_ms}ms]"
            if interrupt_task is not None:
                interrupt_task.cancel()
            for task in pending:
                task.cancel()

            stdout, _ = communicate_task.result()
            output = stdout.decode("utf-8", errors="replace") if stdout else ""
            parts = []
            if output.strip():
                parts.append(output.rstrip())
            if proc.returncode and proc.returncode != 0:
                parts.append(f"[exit code: {proc.returncode}]")
            return "\n".join(parts) if parts else "(no output)"
        except TimeoutError:
            try:
                if proc is not None:
                    self._kill_process_group(proc)
                    await proc.wait()
            except Exception:
                pass
            return f"[Command timed out after {timeout_ms}ms]"
        except Exception as exc:
            return f"Error: {exc}"

    # ═══════════════════════════════════════════════════════
    # 文件 I/O
    # ═══════════════════════════════════════════════════════

    async def read_file(self, path: str) -> str:
        try:
            safe = self.resolve(path, external_mode="readonly")
        except PermissionError as exc:
            return f"Error: {exc}"
        try:
            content = safe.read_text(encoding="utf-8")
            return content if content else "(empty)"
        except FileNotFoundError:
            return f"Error: file not found '{path}'"
        except IsADirectoryError:
            return f"Error: '{path}' is a directory, not a file"
        except PermissionError:
            return f"Error: permission denied reading '{path}'"
        except UnicodeDecodeError:
            try:
                raw = safe.read_bytes()
                return f"[binary file, {len(raw)} bytes, preview]\n{raw[:200]!r}"
            except Exception as exc:
                return f"Error: cannot read binary file '{path}': {exc}"
        except Exception as exc:
            return f"Error: {exc}"

    async def write_file(self, path: str, content: str) -> str:
        try:
            safe = self.resolve(path, external_mode="readwrite")
        except PermissionError as exc:
            return f"Error: {exc}"
        try:
            safe.parent.mkdir(parents=True, exist_ok=True)
            safe.write_text(content, encoding="utf-8")
            return f"Successfully wrote {path} ({len(content)} characters)"
        except PermissionError:
            return f"Error: permission denied writing '{path}'"
        except IsADirectoryError:
            return f"Error: '{path}' is an existing directory, cannot write as file"
        except Exception as exc:
            return f"Error: {exc}"

    async def edit_file(self, path: str, edits: list[dict]) -> str:
        from agent.tools.edit import _fuzzy_replace, _snippet_around

        try:
            safe = self.resolve(path, external_mode="readwrite")
        except PermissionError as exc:
            return f"Error: {exc}"
        try:
            content = safe.read_text(encoding="utf-8")
        except FileNotFoundError:
            return f"Error: file not found '{path}'. Use Write to create a new file first."
        except IsADirectoryError:
            return f"Error: '{path}' is a directory, not a file"
        except PermissionError:
            return f"Error: permission denied reading '{path}'"
        except UnicodeDecodeError:
            return f"Error: '{path}' appears to be a binary file; cannot edit"
        except Exception as exc:
            return f"Error: {exc}"

        original = content
        for i, op in enumerate(edits):
            new_content, found = _fuzzy_replace(content, op["old_text"], op["new_text"])
            if not found:
                snippet = _snippet_around(original, op["old_text"])
                return (
                    f"Error: edit #{i + 1} failed -- cannot find old_text in '{path}'.\n"
                    f"--- old_text ---\n{op['old_text']}\n"
                    f"--- file excerpt ---\n{snippet}\n"
                    f"Hint: re-Read the file to get the exact current content."
                )
            content = new_content
        try:
            safe.write_text(content, encoding="utf-8")
        except PermissionError:
            return f"Error: permission denied writing '{path}'"
        except Exception as exc:
            return f"Error: {exc}"
        return f"Successfully applied {len(edits)} edit(s) to {path}."

    # ═══════════════════════════════════════════════════════
    # 内部
    # ═══════════════════════════════════════════════════════

    @staticmethod
    def _validate_session_id(session_id: str) -> None:
        validate_session_id(session_id)

    @staticmethod
    def _kill_process_group(proc) -> None:
        """Send SIGKILL to a single subprocess, NOT the process group.

        Uses os.kill instead of os.killpg. killpg is dangerous: if the
        child exits and its PID gets reused for a process-group-leader
        (e.g. a shell session), killpg would wipe out that entire group.
        """
        try:
            os.kill(proc.pid, signal.SIGKILL)
        except Exception:
            with contextlib.suppress(Exception):
                proc.kill()

    def __repr__(self) -> str:
        return f"Workspace({self.root}, uuid={self.uuid})"
