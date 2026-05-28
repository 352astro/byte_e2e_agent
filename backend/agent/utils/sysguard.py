"""
内核级沙箱 — 在子进程 exec 前锁死文件/网络权限。

Linux   → Landlock（内核 5.13+, 6.7+ 支持网络限制）
macOS   → Apple Seatbelt（sandbox-exec）
Windows → 暂不支持

调用时机：fork() 之后、exec() 之前（PersistentTerminal._start_unix 的 preexec_fn 中）。
失败策略：子进程写错误信息到 stderr 后退出，父进程 PTY 自然读到错误。
"""

from __future__ import annotations

import os
import sys

# ── 系统只读路径（sh/bash 运行必需的目录）───────────────
_READONLY_PATHS = [
    "/usr",
    "/lib",
    "/lib64",
    "/bin",
    "/sbin",
    "/etc",
    "/dev",
    "/proc",
    "/sys",
]


def apply(workspace: str) -> None:
    """在子进程中施加内核级沙箱。

    调用后当前进程只能读写 workspace，系统路径只读+可执行。
    必须在 os.fork() 之后、os.execve() 之前调用。
    """
    ws = os.path.abspath(workspace)

    if sys.platform == "linux":
        _apply_landlock(ws)
    elif sys.platform == "darwin":
        pass  # macOS 通过 sandbox-exec 外部包装，不在此处 self-apply
    # Windows: silently skip


# ═══════════════════════════════════════════════════════
# Linux: Landlock (porcelain API)
# ═══════════════════════════════════════════════════════


def _landlock_available() -> bool:
    try:
        from landlock.porcelain import Ruleset  # noqa: F401

        return True
    except ImportError:
        return False


def _apply_landlock(workspace: str) -> None:
    if not _landlock_available():
        _fail("Landlock Python 库未安装。运行: uv pip install landlock")

    try:
        from landlock.plumbing import FSAccess
        from landlock.porcelain import Ruleset

        # 工作区：读写 + 执行 + 遍历
        rw = (
            FSAccess.READ_FILE
            | FSAccess.READ_DIR
            | FSAccess.WRITE_FILE
            | FSAccess.EXECUTE
            | FSAccess.REFER
            | FSAccess.MAKE_REG
            | FSAccess.MAKE_DIR
        )
        # 系统路径：只读 + 可执行（bash/ls/cat 等二进制需要 EXECUTE）
        ro = FSAccess.READ_FILE | FSAccess.READ_DIR | FSAccess.EXECUTE | FSAccess.REFER

        r = Ruleset()
        r.allow(workspace, rules=rw)
        r.allow(*_READONLY_PATHS, rules=ro)

        r.apply()
    except Exception as exc:
        _fail(f"Landlock 施加失败: {exc}")


# ═══════════════════════════════════════════════════════
# macOS: Seatbelt (sandbox-exec)
# ═══════════════════════════════════════════════════════


def _build_seatbelt_profile(workspace: str) -> str:
    """生成 Apple Seatbelt profile 文本。"""
    read_only_lines = "\n".join(
        f'    (allow file-read* (subpath "{p}"))' for p in _READONLY_PATHS
    )
    return f"""\
(version 1)
(deny default)
(deny network*)
(allow file-read* (subpath "{workspace}"))
(allow file-write* (subpath "{workspace}"))
{read_only_lines}
(allow process-exec (subpath "/bin"))
(allow process-exec (subpath "/usr/bin"))
(allow process-fork)
(allow sysctl-read)
(allow signal)
"""


def _seatbelt_available() -> bool:
    import shutil

    return shutil.which("sandbox-exec") is not None


# ═══════════════════════════════════════════════════════
# 公共工具
# ═══════════════════════════════════════════════════════


def _fail(message: str) -> None:
    """子进程中的优雅失败：写 stderr 后退出。"""
    try:
        os.write(2, f"[sysguard] {message}\n".encode())
    except Exception:
        pass
    os._exit(126)


def is_available() -> bool:
    """当前平台是否支持内核沙箱。"""
    if sys.platform == "linux":
        return _landlock_available()
    elif sys.platform == "darwin":
        return _seatbelt_available()
    return False


def status() -> str:
    """人类可读的沙箱状态。"""
    if sys.platform == "linux":
        if _landlock_available():
            return "Landlock (Linux kernel 5.13+) — 可用"
        return "Landlock — 不可用 (uv pip install landlock)"
    elif sys.platform == "darwin":
        if _seatbelt_available():
            return "Apple Seatbelt (sandbox-exec) — 可用"
        return "Apple Seatbelt — 不可用 (sandbox-exec 未找到)"
    return f"{sys.platform} — 不支持"
