"""
工作目录管理：所有文件 / 命令工具共享的工作根目录。
"""

import os
from pathlib import Path

# 默认工作根目录：进程当前目录
_workspace_root: str = os.getcwd()


def set_workspace_root(path: str | Path) -> None:
    """设置所有工具的工作根目录。Read / Write / Bash 将在此目录内操作。"""
    global _workspace_root
    p = Path(path).resolve()
    if not p.is_dir():
        raise ValueError(f"工作目录不存在: {p}")
    _workspace_root = str(p)


def get_workspace_root() -> str:
    """返回当前工作根目录的绝对路径。"""
    return _workspace_root
