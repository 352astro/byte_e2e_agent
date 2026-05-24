"""安全校验工具：路径防穿越 + 危险指令拦截。"""

import os
import re

# ============================================================
# 路径安全检查
# ============================================================


def safe_resolve_path(path: str, workspace_root: str) -> str:
    """
    将相对路径解析为绝对路径，并确保不超出 workspace_root。

    返回安全的绝对路径；若路径试图穿越工作目录则抛出 ValueError。
    """
    # 拼接后解析符号链接与相对路径
    abs_path = os.path.realpath(os.path.join(workspace_root, path))
    real_root = os.path.realpath(workspace_root)

    if abs_path != real_root and not abs_path.startswith(real_root + os.sep):
        raise ValueError(
            f"Path safety check failed: '{path}' attempts to escape the workspace"
        )

    return abs_path


# ============================================================
# 危险指令拦截
# ============================================================

_DANGEROUS_PATTERNS: list[tuple[str, str]] = [
    # (regex, description)
    (r"\bsudo\b", "sudo privilege escalation"),
    (r"\bsu\b", "su user switch"),
    (r"\bchmod\b.*[/\s]7", "chmod 777 type operation"),
    (r"\bchown\b.*\b(root|/\*)", "chown on system files"),
    (r"\bmkfs\b", "mkfs filesystem format"),
    (r"\bdd\b.*of\s*=\s*/dev/", "dd write to device"),
    (r">\s*/dev/sd", "redirect overwrite disk device"),
    (
        r"rm\s+-[a-zA-Z]*[rR][a-zA-Z]*[fF][a-zA-Z]*\s+/(\*|\s|$)",
        "rm -rf / or rm -rf /*",
    ),
    (
        r"rm\s+-[a-zA-Z]*[fF][a-zA-Z]*[rR][a-zA-Z]*\s+/(\*|\s|$)",
        "rm -fr / or rm -fr /*",
    ),
    (r"rm\s+-[a-zA-Z]*[rR][a-zA-Z]*[fF][a-zA-Z]*\s+~/", "rm -rf ~/"),
    (r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\};", "fork bomb"),
    (r"\bshutdown\b", "shutdown system"),
    (r"\breboot\b", "reboot system"),
    (r"\bpoweroff\b", "poweroff system"),
]


def check_command_safety(command: str) -> None:
    """
    检查命令是否包含危险操作。

    若命中危险模式则抛出 ValueError；否则静默通过。
    """
    command_lower = command.lower()
    for pattern, description in _DANGEROUS_PATTERNS:
        if re.search(pattern, command_lower):
            raise ValueError(
                f"Dangerous command blocked ({description}): matched pattern '{pattern}'"
            )
