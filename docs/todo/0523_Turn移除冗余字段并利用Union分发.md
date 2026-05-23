0523_Turn移除冗余字段并利用Union分发
```python
@dataclass
class Turn:
    role: Literal["user", "assistant"]
    # user
    question: str = ""
    # assistant
    reasoning: str = ""
    content: str = ""
    tool_calls: list[ToolStep] = field(default_factory=list)
    finish_answer: str | None = None

```

## 当前字段冗余，后续改成pydantic.BaseModel, 内部使用 `Union[不同Turn类型]` 进行分发
