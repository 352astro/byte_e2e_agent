import json
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agent.llm import HelloAgentsLLM
from agent.react import ReActAgent
from agent.tools.workspace import set_workspace_root

# ── 加载 .env ──────────────────────────────────────────
load_dotenv()

# ── 工作目录沙箱 ───────────────────────────────────────
_AGENT_WORKSPACE = os.path.join(os.path.dirname(__file__), "agent_workspace")
os.makedirs(_AGENT_WORKSPACE, exist_ok=True)
set_workspace_root(_AGENT_WORKSPACE)

# ── FastAPI app ────────────────────────────────────────

app = FastAPI(title="Byte E2E Agent Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Hello World from FastAPI!"}


@app.get("/api/hello")
def hello() -> dict[str, str]:
    return {"message": "Hello World from FastAPI!", "status": "ok"}


# ── Agent SSE 流式端点 ─────────────────────────────────


class AgentStreamRequest(BaseModel):
    question: str = Field(..., description="Question or task for the agent")
    max_steps: int = Field(default=50, ge=1, le=200, description="Max reasoning steps")


@app.post("/api/agent/stream")
def agent_stream(req: AgentStreamRequest):
    """Run the ReAct agent and stream events via Server-Sent Events."""

    def event_generator():
        try:
            llm = HelloAgentsLLM()
        except ValueError as e:
            yield f"data: {json.dumps({'type': 'error', 'message': f'LLM not configured: {e}'})}\n\n"
            return

        agent = ReActAgent(llm_client=llm)
        for event in agent.run_stream(req.question, max_steps=req.max_steps):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
