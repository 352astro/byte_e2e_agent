"""
终端 ANSI 转义序列 — 用颜色替代 emoji。

用法：
    from agent.utils._term import G, info, success, warn, error, tool, prompt, step, reset

    print(f"{step('[Step 1]')} 正在思考...")
    print(info("正在调用模型..."))
    print(success("完成!"))
"""

# ── 基础 ANSI 码 ────────────────────────────────────────────

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"

# 常规色
_BLACK = "\033[30m"
_RED = "\033[31m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_BLUE = "\033[34m"
_MAGENTA = "\033[35m"
_CYAN = "\033[36m"
_WHITE = "\033[37m"

# 亮色
_BRIGHT_RED = "\033[91m"
_BRIGHT_GREEN = "\033[92m"
_BRIGHT_YELLOW = "\033[93m"
_BRIGHT_BLUE = "\033[94m"
_BRIGHT_MAGENTA = "\033[95m"
_BRIGHT_CYAN = "\033[96m"
_BRIGHT_WHITE = "\033[97m"


def reset() -> str:
    """返回重置码（不常用，因为着色函数会自动重置）。"""
    return _RESET


def G(code: str) -> str:
    """原始 ANSI 码快捷方式。"""
    return code


# ── 语义着色函数 ────────────────────────────────────────────


def info(text: str) -> str:
    """信息级别：青色。"""
    return f"{_CYAN}{text}{_RESET}"


def success(text: str) -> str:
    """成功：绿色加粗。"""
    return f"{_BOLD}{_GREEN}{text}{_RESET}"


def warn(text: str) -> str:
    """警告：黄色。"""
    return f"{_YELLOW}{text}{_RESET}"


def error(text: str) -> str:
    """错误：红色加粗。"""
    return f"{_BOLD}{_RED}{text}{_RESET}"


def tool(text: str) -> str:
    """工具调用：蓝色。"""
    return f"{_BLUE}{text}{_RESET}"


def prompt(text: str) -> str:
    """用户提示符：亮绿色加粗。"""
    return f"{_BOLD}{_BRIGHT_GREEN}{text}{_RESET}"


def step(text: str) -> str:
    """步骤标题：亮青色加粗。"""
    return f"{_BOLD}{_BRIGHT_CYAN}{text}{_RESET}"


def dim(text: str) -> str:
    """次要文字：暗色。"""
    return f"{_DIM}{text}{_RESET}"


def bold(text: str) -> str:
    """粗体。"""
    return f"{_BOLD}{text}{_RESET}"


def magenta(text: str) -> str:
    """品红（用于 Search 等特定工具）。"""
    return f"{_MAGENTA}{text}{_RESET}"
