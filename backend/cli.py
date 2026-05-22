"""
ReAct 智能体 — 交互式问答 CLI 入口。

用法:
    cd backend
    uv run python cli.py          # uv 用户
    python cli.py                 # venv / pip 用户
"""

import asyncio
import os

from dotenv import load_dotenv

from agent.llm import HelloAgentsLLM
from agent.react import ReActAgent
from agent.sandbox import SandBox
from agent.utils._term import bold, dim, prompt, success, warn

try:
    import readline
except ImportError:
    pass

load_dotenv()

_AGENT_WORKSPACE = os.environ.get("AGENT_WORKSPACE", os.getcwd())


async def async_main() -> None:
    try:
        llm = HelloAgentsLLM()
    except ValueError as e:
        print(warn(f"LLM 配置错误: {e}"))
        print(dim("请检查 backend/.env 文件是否已配置。"))
        return

    sandbox = SandBox(_AGENT_WORKSPACE)
    agent = ReActAgent(llm_client=llm, sandbox=sandbox)

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
            await agent.clear()
            print(f"  {warn('[Clear]')} 上下文已重置。\n")
            continue

        print()
        answer = await agent.run(question, max_steps=50)
        print(f"\n  {success('Answer')}  {answer}\n")

    await sandbox.shutdown()


if __name__ == "__main__":
    asyncio.run(async_main())
