"""Kernel-level sandbox helpers for child processes.

Linux uses Landlock in the child process before exec. macOS uses
``sandbox-exec`` by wrapping the target command.
"""

from __future__ import annotations

import os
import shutil
import sys

from landlock.plumbing import FSAccess
from landlock.porcelain import Ruleset

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
    """Apply the platform sandbox to the current child process."""
    ws = os.path.abspath(workspace)
    if sys.platform == "linux":
        _apply_landlock(ws)
    elif sys.platform == "darwin":
        # macOS is handled by wrapping the command with sandbox-exec.
        return


def _apply_landlock(workspace: str) -> None:
    try:
        rw = (
            FSAccess.READ_FILE
            | FSAccess.READ_DIR
            | FSAccess.WRITE_FILE
            | FSAccess.EXECUTE
            | FSAccess.REFER
            | FSAccess.MAKE_REG
            | FSAccess.MAKE_DIR
        )
        ro = FSAccess.READ_FILE | FSAccess.READ_DIR | FSAccess.EXECUTE | FSAccess.REFER

        ruleset = Ruleset()
        ruleset.allow(workspace, rules=rw)
        existing_ro_paths = [path for path in _READONLY_PATHS if os.path.exists(path)]
        if existing_ro_paths:
            ruleset.allow(*existing_ro_paths, rules=ro)
        ruleset.apply()
    except Exception as exc:
        _fail(f"Landlock failed: {exc}")


def build_seatbelt_profile(workspace: str) -> str:
    """Build an Apple Seatbelt profile that allows writes only in workspace."""
    ws = os.path.abspath(workspace)
    read_only_lines = "\n".join(
        f'    (allow file-read* (subpath "{path}"))'
        for path in _READONLY_PATHS
        if os.path.exists(path)
    )
    return f"""\
(version 1)
(deny default)
(deny network*)
(allow file-read* (subpath "{ws}"))
(allow file-write* (subpath "{ws}"))
{read_only_lines}
(allow process-exec (subpath "/bin"))
(allow process-exec (subpath "/usr/bin"))
(allow process-fork)
(allow sysctl-read)
(allow signal)
"""


def seatbelt_available() -> bool:
    return shutil.which("sandbox-exec") is not None


def is_available() -> bool:
    if sys.platform == "linux":
        return True
    if sys.platform == "darwin":
        return seatbelt_available()
    return False


def status() -> str:
    if sys.platform == "linux":
        return "Landlock configured"
    if sys.platform == "darwin":
        return "Seatbelt available" if seatbelt_available() else "Seatbelt unavailable"
    return f"{sys.platform} unsupported"


def _fail(message: str) -> None:
    try:
        os.write(2, f"[sysguard] {message}\n".encode("utf-8"))
    except Exception:
        pass
    os._exit(126)
