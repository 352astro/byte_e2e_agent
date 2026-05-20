from typing import Literal

from pydantic import Field

from agent.tools.base import BaseTool


class Finish(BaseTool):
    """
    结束行动：表示已获得最终答案，不再调用工具。

    作为 Tool 联合类型的一员，但不实现 execute()。
    ReAct 循环通过 isinstance(action, Finish) 特判退出。
    """

    kind: Literal["Finish"] = "Finish"
    answer: str = Field(..., description="The final answer text to return to the user")
