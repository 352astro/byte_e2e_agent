"""AskUser tool — request structured input from the user."""

from __future__ import annotations

import json
from typing import Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, model_validator


class AskOption(BaseModel):
    id: str = Field(..., description="Stable option id.")
    label: str = Field(..., description="Short option label shown to the user.")
    description: str = Field(default="", description="Optional explanation of this option.")


class AskQuestion(BaseModel):
    id: str = Field(..., description="Stable answer field id.")
    label: str = Field(..., description="Question label shown to the user.")
    type: Literal["text", "textarea"] = Field(default="text", description="Input control type.")
    required: bool = Field(default=True, description="Whether an answer is required.")
    placeholder: str = Field(default="", description="Optional input placeholder.")


class AskUserInput(BaseModel):
    """AskUser input parameters."""

    title: str = Field(..., description="Short title for the user prompt.")
    description: str = Field(default="", description="Optional prompt details.")
    choices: list[AskOption] = Field(
        default_factory=list,
        description="Optional choices shown to the user.",
    )
    questions: list[AskQuestion] = Field(
        default_factory=list,
        description="Optional text questions shown to the user.",
    )
    choice_required: bool = Field(
        default=True,
        description="Require selecting a choice when choices are present.",
    )
    multiple: bool = Field(
        default=False,
        description="Allow selecting multiple choices.",
    )
    allow_custom: bool = Field(
        default=False,
        description="Allow an optional custom text response.",
    )

    @model_validator(mode="after")
    def validate_shape(self) -> AskUserInput:
        if not self.choices and not self.questions:
            raise ValueError("AskUser requires at least one choice or question")
        return self


def _dump_items(items) -> list[dict]:
    result = []
    for item in items or []:
        if hasattr(item, "model_dump"):
            result.append(item.model_dump())
        elif isinstance(item, dict):
            result.append(dict(item))
    return result


async def ask_user_handler(
    title: str,
    description: str = "",
    choices: list[dict] | None = None,
    questions: list[dict] | None = None,
    choice_required: bool = True,
    multiple: bool = False,
    allow_custom: bool = False,
    *,
    session_id: str = "",
    interrupt_event=None,
    human_input_requester=None,
) -> str:
    """Ask the user for structured input and wait for their response."""
    if human_input_requester is None:
        return json.dumps(
            {
                "status": "error",
                "reason": "AskUser is unavailable in this runtime.",
            },
            ensure_ascii=False,
        )
    response = await human_input_requester(
        {
            "title": title,
            "description": description,
            "choices": _dump_items(choices),
            "questions": _dump_items(questions),
            "choice_required": choice_required,
            "multiple": multiple,
            "allow_custom": allow_custom,
            "session_id": session_id,
        },
        interrupt_event=interrupt_event,
    )
    return json.dumps(
        {
            "status": "ignored" if (response or {}).get("ignored") else "answered",
            **(
                {"message": "The user ignored this request and did not want to answer."}
                if (response or {}).get("ignored")
                else {}
            ),
            **(response or {}),
        },
        ensure_ascii=False,
    )


ask_user_tool = StructuredTool.from_function(
    coroutine=ask_user_handler,
    name="AskUser",
    description=(
        "Ask the user for structured input. Provide choices, questions, or "
        "both. Use questions for free-text input."
    ),
    args_schema=AskUserInput,
)
