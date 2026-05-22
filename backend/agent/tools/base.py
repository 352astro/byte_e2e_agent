import re

from pydantic import BaseModel


class BaseTool(BaseModel):
    """所有工具的基类。子类需实现 async execute(sandbox)。"""

    @classmethod
    def function_name(cls) -> str:
        """OpenAI function 名称（默认由类名转换：Shell→Shell, PlanRewrite→PlanRewrite）。"""
        return cls.__name__

    async def execute(self, sandbox=None) -> str:
        raise NotImplementedError(f"{cls.__name__} 未实现 execute() 方法")
