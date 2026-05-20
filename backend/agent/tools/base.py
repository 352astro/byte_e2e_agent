from pydantic import BaseModel


class BaseTool(BaseModel):
    """
    所有工具的基类。

    子类必须定义 kind 字段（使用 Literal 类型）以支持
    Pydantic 的鉴别联合（discriminated union）自动分发。
    若不定义 kind，将在子类定义时抛出 TypeError。

    execute() 由可执行工具（如 Search）实现；
    Finish 等信号工具不实现 execute，由 react 循环通过 isinstance 特判处理。
    """

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # 注意: __init_subclass__ 在 Pydantic 构建 model_fields 之前调用，
        # 因此这里使用 __annotations__ 来检查字段声明。
        if "kind" not in cls.__annotations__:
            raise TypeError(
                f"{cls.__name__} 必须定义 'kind' 字段（使用 Literal 类型），"
                f"以支持 Pydantic 鉴别联合自动分发。"
            )

    def execute(self) -> str:
        """执行工具逻辑，返回字符串结果。可执行工具必须重写此方法。"""
        raise NotImplementedError(f"{self.__class__.__name__} 未实现 execute() 方法")
