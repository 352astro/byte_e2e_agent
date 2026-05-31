from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(..., description="Question or task for the agent")
    max_steps: int = Field(default=100, ge=1, le=200, description="Max reasoning steps")


class RespondRequest(BaseModel):
    message_id: str = Field(..., description="Message ID to respond to")
    response: dict = Field(..., description="User response payload")
