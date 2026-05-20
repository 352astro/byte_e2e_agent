"""
ReAct 智能体 — 交互式问答 CLI 入口。

run() 不会在每次调用时清空 history，
因此多轮对话自动继承上下文。

用法:
    cd backend
    uv run python cli.py          # uv 用户
    python cli.py                 # venv / pip 用户（需先激活环境）
"""

import os

from dotenv import load_dotenv

from agent._term import bold, dim, prompt, success, warn
from agent.llm import HelloAgentsLLM
from agent.react import ReActAgent
from agent.tools.workspace import set_workspace_root

try:
    import readline  # 启用行编辑和历史记录（Unix）
except ImportError:
    pass

# ── 加载 .env ──────────────────────────────────────────
load_dotenv()

# ── 工作目录沙箱：agent 所有文件操作限定在此目录下 ────
_AGENT_WORKSPACE = os.path.join(os.path.dirname(__file__), "agent_workspace")
os.makedirs(_AGENT_WORKSPACE, exist_ok=True)
set_workspace_root(_AGENT_WORKSPACE)


def main() -> None:
    # 1. 创建 LLM 客户端（从 .env 读取配置）
    try:
        llm = HelloAgentsLLM()
    except ValueError as e:
        print(warn(f"LLM 配置错误: {e}"))
        print(dim("请检查 backend/.env 文件是否已配置。"))
        return

    # 2. 创建 ReAct 智能体（单例，history 跨轮持久）
    agent = ReActAgent(llm_client=llm)

    print(bold("=" * 50))
    print(bold("  ReAct Agent  --  Interactive Q&A"))
    print(bold("=" * 50))
    print(dim("  Commands:"))
    print(dim("    /clear    清空对话上下文"))
    print(dim("    /exit     退出"))
    print(dim("    Ctrl+C    退出"))
    print(bold("=" * 50))
    print()

    while True:
        try:
            question = input(f"{prompt('>>> ')} ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n\n  {warn('Goodbye.')}")
            break

        if not question:
            continue

        if question.lower() in ("/exit", "/quit", "exit", "quit"):
            print(f"  {warn('Goodbye.')}")
            break

        if question.lower() in ("/clear", "clear"):
            agent.history = []
            print(f"  {warn('[Clear]')} 上下文已重置。\n")
            continue

        print()
        answer = agent.run(question, max_steps=50)
        print(f"\n  {success('Answer')}  {answer}\n")


if __name__ == "__main__":
    main()
