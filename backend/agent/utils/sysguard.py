"""Kernel-level sandbox helpers for child processes.

Linux uses Landlock in the child process before exec. macOS uses
``sandbox-exec`` by wrapping the target command.
"""

from __future__ import annotations

import os
import shutil
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

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

_READWRITE_DEVICE_PATHS = [
    "/dev/null",
    "/dev/zero",
    "/dev/urandom",
    "/dev/random",
    "/dev/tty",
    "/dev/ptmx",
]

_HOME_TOOLCHAIN_MARKERS = {
    ".bun",
    ".cargo",
    ".deno",
    ".local",
    ".nvm",
    ".pyenv",
    ".rustup",
    ".rye",
    ".volta",
}


@dataclass(frozen=True)
class SysguardRule:
    id: str
    label: str
    path: str
    mode: Literal["readonly", "readonly_exec", "readwrite"] = "readonly_exec"
    source: Literal["builtin", "global", "workspace"] = "builtin"
    enabled: bool = True
    description: str = ""


_BUILTIN_RULE_SPECS = [
    {
        "id": "cargo",
        "label": "Rust Cargo",
        "markers": [".cargo", ".rustup"],
        "description": "Allow Rust cargo/rustup toolchains as read-only executables.",
    },
    {
        "id": "node-local",
        "label": "Local Node Tools",
        "markers": [".nvm", ".volta", ".bun", ".deno"],
        "description": "Allow common user-local JavaScript toolchains.",
    },
    {
        "id": "python-local",
        "label": "Local Python Tools",
        "markers": [".pyenv", ".rye"],
        "description": "Allow common user-local Python toolchains.",
    },
    {
        "id": "local-bin",
        "label": "User Local Bin",
        "markers": [".local"],
        "description": "Allow ~/.local tools as read-only executables.",
    },
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
            | FSAccess.TRUNCATE
            | FSAccess.EXECUTE
            | FSAccess.REFER
            | FSAccess.MAKE_REG
            | FSAccess.MAKE_DIR
            | FSAccess.MAKE_SYM
            | FSAccess.MAKE_FIFO
            | FSAccess.MAKE_SOCK
            | FSAccess.REMOVE_FILE
            | FSAccess.REMOVE_DIR
        )
        ro = FSAccess.READ_FILE | FSAccess.READ_DIR | FSAccess.REFER
        ro_exec = ro | FSAccess.EXECUTE
        external_rw = (
            FSAccess.READ_FILE
            | FSAccess.READ_DIR
            | FSAccess.WRITE_FILE
            | FSAccess.TRUNCATE
            | FSAccess.REFER
            | FSAccess.MAKE_REG
            | FSAccess.MAKE_DIR
            | FSAccess.MAKE_SYM
            | FSAccess.MAKE_FIFO
            | FSAccess.MAKE_SOCK
            | FSAccess.REMOVE_FILE
            | FSAccess.REMOVE_DIR
        )
        rw_device = FSAccess.READ_FILE | FSAccess.WRITE_FILE

        ruleset = Ruleset()
        ruleset.allow(workspace, rules=rw)
        readonly_paths = _rule_paths_from_environment("readonly")
        readonly_exec_paths = _rule_paths_from_environment("readonly_exec")
        readwrite_paths = _rule_paths_from_environment("readwrite")
        if readonly_paths:
            ruleset.allow(*readonly_paths, rules=ro)
        if readonly_exec_paths:
            ruleset.allow(*readonly_exec_paths, rules=ro_exec)
        if readwrite_paths:
            ruleset.allow(*readwrite_paths, rules=external_rw)
        existing_rw_devices = _existing_paths(_READWRITE_DEVICE_PATHS)
        if existing_rw_devices:
            ruleset.allow(*existing_rw_devices, rules=rw_device)
        ruleset.apply()
    except Exception as exc:
        _fail(f"Landlock failed: {exc}")


def build_seatbelt_profile(workspace: str, workspace_uuid: str | None = None) -> str:
    """Build an Apple Seatbelt profile that allows writes only in workspace."""
    ws = os.path.abspath(workspace)
    read_only_lines = "\n".join(
        f'    (allow file-read* (subpath "{path}"))'
        for path in _rule_paths_from_environment("readonly", workspace_uuid)
    )
    read_only_exec_lines = "\n".join(
        "\n".join(
            [
                f'    (allow file-read* (subpath "{path}"))',
                f'    (allow process-exec (subpath "{path}"))',
            ]
        )
        for path in _rule_paths_from_environment("readonly_exec", workspace_uuid)
    )
    readwrite_lines = "\n".join(
        f'    (allow file-read* file-write* (subpath "{path}"))'
        for path in _rule_paths_from_environment("readwrite", workspace_uuid)
    )
    readwrite_device_lines = "\n".join(
        f'    (allow file-read* file-write* (literal "{path}"))'
        for path in _existing_paths(_READWRITE_DEVICE_PATHS)
    )
    return f"""\
(version 1)
(deny default)
(deny network*)
(allow file-read* (subpath "{ws}"))
(allow file-write* (subpath "{ws}"))
{read_only_lines}
{read_only_exec_lines}
{readwrite_lines}
{readwrite_device_lines}
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


def list_builtin_rules() -> list[SysguardRule]:
    rules: list[SysguardRule] = []
    for spec in _BUILTIN_RULE_SPECS:
        for marker in spec["markers"]:
            path = Path.home() / marker
            if not path.exists():
                continue
            rules.append(
                SysguardRule(
                    id=f"builtin:{spec['id']}:{marker}",
                    label=f"{spec['label']} ({marker})",
                    path=str(path.resolve()),
                    source="builtin",
                    description=str(spec["description"]),
                )
            )
    return rules


def detect_command_rule(command: str) -> SysguardRule | None:
    """Return a trusted read-only executable rule for the command entrypoint."""
    try:
        parts = shlex.split(command, posix=(os.name != "nt"))
    except ValueError:
        return None
    executable = _first_executable_token(parts)
    if not executable:
        return None
    resolved = shutil.which(executable, path=os.environ.get("PATH", ""))
    if not resolved:
        return None
    path = Path(resolved)
    root = _home_toolchain_root(path)
    if root is None:
        return None
    if _overlaps_project_root(root):
        return None
    return SysguardRule(
        id=f"detected:{root.name}",
        label=f"{root.name} toolchain",
        path=str(root),
        source="builtin",
        description=f"Detected command entrypoint: {resolved}",
    )


_MODE_LEVEL = {
    "readonly": 1,
    "readonly_exec": 2,
    "readwrite": 3,
}


def is_path_allowed(
    path: str,
    required_mode: Literal["readonly", "readonly_exec", "readwrite"] = "readonly_exec",
    workspace_uuid: str | None = None,
) -> bool:
    try:
        target = Path(path).expanduser().resolve()
    except OSError:
        return False
    required_level = _MODE_LEVEL[required_mode]
    for mode in ("readonly", "readonly_exec", "readwrite"):
        if _MODE_LEVEL[mode] < required_level:
            continue
        for allowed in _rule_paths_from_environment(mode, workspace_uuid):
            try:
                target.relative_to(Path(allowed))
                return True
            except ValueError:
                continue
    return False


def external_path_mode_for_rule(
    path: str,
    workspace_uuid: str | None = None,
) -> Literal["readonly", "readonly_exec", "readwrite"] | None:
    try:
        target = Path(path).expanduser().resolve()
    except OSError:
        return None
    best: Literal["readonly", "readonly_exec", "readwrite"] | None = None
    for mode in ("readonly", "readonly_exec", "readwrite"):
        for allowed in _rule_paths_from_environment(mode, workspace_uuid):
            try:
                target.relative_to(Path(allowed))
            except ValueError:
                continue
            if best is None or _MODE_LEVEL[mode] > _MODE_LEVEL[best]:
                best = mode
    return best


def _fail(message: str) -> None:
    try:
        os.write(2, f"[sysguard] {message}\n".encode("utf-8"))
    except Exception:
        pass
    os._exit(126)


def _rule_paths_from_environment(
    mode: Literal["readonly", "readonly_exec", "readwrite"],
    workspace_uuid: str | None = None,
) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()

    def add(path: str | Path) -> None:
        try:
            resolved = Path(path).expanduser().resolve()
        except OSError:
            return
        if not resolved.exists():
            return
        value = str(resolved)
        if value not in seen:
            seen.add(value)
            paths.append(value)

    if mode == "readonly_exec":
        for path in _READONLY_PATHS:
            add(path)

        for rule in list_builtin_rules():
            if rule.enabled:
                add(rule.path)

        for raw_part in os.environ.get("PATH", "").split(os.pathsep):
            if not raw_part:
                continue
            part = Path(raw_part).expanduser()
            _add_home_toolchain_root(part, add)

    for rule in _load_custom_rules(workspace_uuid):
        if rule.enabled and rule.mode == mode:
            add(rule.path)

    return paths


def _load_custom_rules(workspace_uuid: str | None = None) -> list[SysguardRule]:
    try:
        from app.services.settings_service import load_sysguard_rules

        data = load_sysguard_rules(workspace_uuid or os.environ.get("AGENT_WORKSPACE_UUID"))
        rules = [*data.get("global", []), *data.get("workspace", [])]
        return [
            SysguardRule(
                id=rule["id"],
                label=rule["label"],
                path=rule["path"],
                mode=rule.get("mode", "readonly_exec"),
                source=rule.get("source", "global"),
                enabled=bool(rule.get("enabled", True)),
                description=rule.get("description", ""),
            )
            for rule in rules
            if isinstance(rule, dict)
        ]
    except Exception:
        return []


def _existing_paths(paths: list[str]) -> list[str]:
    existing: list[str] = []
    for path in paths:
        try:
            resolved = Path(path).resolve()
        except OSError:
            continue
        if resolved.exists():
            existing.append(str(resolved))
    return existing


def _add_home_toolchain_root(path: Path, add) -> None:
    root = _home_toolchain_root(path)
    if root is None:
        return
    add(root)
    if root.name == ".cargo":
        add(Path.home() / ".rustup")


def _home_toolchain_root(path: Path) -> Path | None:
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        return None
    home = Path.home().resolve()
    try:
        relative = resolved.relative_to(home)
    except ValueError:
        return None

    for index, part in enumerate(relative.parts):
        if part not in _HOME_TOOLCHAIN_MARKERS:
            continue
        return home.joinpath(*relative.parts[: index + 1])
    return None


def _overlaps_project_root(path: Path) -> bool:
    try:
        from app.core.config import PROJECT_ROOT
    except Exception:
        return False
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        return False
    project_root = PROJECT_ROOT.resolve()
    try:
        resolved.relative_to(project_root)
        return True
    except ValueError:
        pass
    try:
        project_root.relative_to(resolved)
        return True
    except ValueError:
        return False


def _first_executable_token(parts: list[str]) -> str:
    if not parts:
        return ""
    skip_next = False
    for token in parts:
        if skip_next:
            skip_next = False
            continue
        if token in {"env", "/usr/bin/env"}:
            continue
        if token in {"sudo", "command", "exec", "time", "nohup"}:
            continue
        if token in {"cd", "export", "source", ".", "ulimit"}:
            return ""
        if token.startswith("-"):
            continue
        if "=" in token and not token.startswith("/") and token.split("=", 1)[0]:
            continue
        return token
    return ""
