# Byte E2E Agent

ReAct coding agent with a FastAPI backend and React/Vite frontend. The backend keeps the prompt flow append-only: durable context is persisted as messages, and runtime components assemble model input from the persisted transcript without injecting temporary dynamic context outside the transcript.

## Layout

```text
byte_e2e_agent/
├── backend/
│   ├── main.py                  # FastAPI entrypoint
│   ├── cli.py                   # CLI entrypoint
│   ├── app/
│   │   ├── api/                 # routes and SSE responses
│   │   ├── core/                # configuration
│   │   ├── schemas/             # request/response models
│   │   └── services/            # workspace, chat, session, metrics services
│   ├── agent/
│   │   ├── llm_streaming.py     # streamed model calls
│   │   ├── tool_execution.py    # tool-call dispatch
│   │   ├── shadow_repo.py       # Dulwich snapshot/restore repo
│   │   ├── core/                # Workspace, SessionConfig, prompts
│   │   ├── hook/                # SSE, persistence, metrics, memory hooks
│   │   ├── memory/              # long-term memory store and hook
│   │   ├── runtime/             # AgentRuntime and turn execution
│   │   ├── session/             # RuntimeSession and SessionTranscript
│   │   └── tools/               # shell, files, browser, search, task, skills
│   └── tests/
└── frontend/
    ├── src/
    │   ├── components/
    │   ├── hooks/
    │   ├── types.ts
    │   └── types.generated.ts
    └── package.json
```

## Requirements

| Tool | Notes |
| --- | --- |
| Python 3.14+ | backend runtime and tests |
| uv | Python dependency management |
| Node.js 20+ / npm 10+ | frontend tooling |
| Chromium | installed through Playwright |
| bubblewrap | optional Linux shell sandbox dependency |

Install browser assets:

```bash
cd backend
uv sync
uv run playwright install chromium
```

## Configuration

Create backend environment config:

```bash
cp backend/.env.example backend/.env
```

Required model variables:

```text
LLM_API_KEY=...
LLM_BASE_URL=...
LLM_MODEL_ID=...
```

Useful optional variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `AGENT_WORKSPACE` | current directory | default workspace path |
| `LLM_TIMEOUT` | `60` | model request timeout in seconds |
| `LLM_MAX_RETRIES` | `3` | streamed model retry count |
| `MEMORY_ENABLED` | `0` | enable long-term memory |
| `SIDE_LLM_API_KEY` | `LLM_API_KEY` | side-query model key for memory |
| `SIDE_LLM_BASE_URL` | `LLM_BASE_URL` | side-query endpoint |
| `SIDE_LLM_MODEL_ID` | `LLM_MODEL_ID` | side-query model |
| `SUBAGENT_LLM_API_KEY` | `LLM_API_KEY` | subagent model key |
| `SUBAGENT_LLM_BASE_URL` | `LLM_BASE_URL` | subagent endpoint |
| `SUBAGENT_LLM_MODEL_ID` | `LLM_MODEL_ID` | subagent model |
| `BROWSER_HEADLESS` | `1` | set `0` for headed browser mode |
| `SERPAPI_KEY` | unset | web search tool |

## Run

Start both services:

```bash
./start.sh
```

Start separately:

```bash
cd backend
uv sync
uv run uvicorn main:app --reload --port 8000
```

```bash
cd frontend
npm install
npm run dev
```

Frontend runs at `http://localhost:5173`; API docs run at `http://localhost:8000/docs`.

CLI:

```bash
./start-cli.sh
./start-cli.sh "summarize this repository"
```

## Validation

Backend:

```bash
cd backend
uv run ruff check .
uv run ruff format .
uv run pytest tests/ -q
```

Frontend:

```bash
cd frontend
npm run lint
npm run test
npm run build
```

## Architecture

```text
React frontend
  <-> REST + SSE
FastAPI routes
  -> WorkspaceContext
       -> AgentRuntime
       -> RuntimeSession
            -> SessionTranscript
       -> HookManager
            -> StreamDriverHook
            -> PersistenceHook
            -> MetricsHook
            -> ShadowCommitHook
            -> MemoryHook
       -> ShadowRepo
```

Core responsibilities:

- `WorkspaceContext` owns the active workspace-level services: runtime, hooks, shadow repo, memory, and stream driver.
- `AgentRuntime` manages active turns and session execution state.
- `RuntimeSession` is the runtime session object; it holds a `Workspace`, `SessionConfig`, and `SessionTranscript`.
- `SessionTranscript` is the append-only persisted message transcript.
- `SessionLocation` and `SessionLocator` resolve session ids across registered workspaces.
- `llm_context_builder.build_llm_messages` converts the transcript into model input.
- `turn_context_updates.plan_context_updates` decides which durable context-update messages should be appended.
- `llm_streaming.stream_model_call` performs streamed model calls.
- `tool_execution.execute_tool_calls` dispatches tool calls. Tool handlers receive `workspace=`.

## Prompt Flow

The prompt flow is intentionally append-only.

1. A session starts with persisted prefix messages from config, rules, preloaded skills, and initial context.
2. User input is appended to `SessionTranscript`.
3. Context updates are appended as system messages when needed.
4. The model input is assembled from the persisted transcript.
5. Assistant messages, tool calls, tool results, interruptions, and recoverable partial messages are appended.

No temporary dynamic context is inserted outside the transcript. This keeps cache prefixes predictable and makes history recovery inspectable.

## Persistence

Agent data is stored under the repository-level data root:

```text
PROJECT_ROOT/.agent/
  workspaces.json
  workspaces/{workspace_uuid}/
    sessions/{session_id}/
      config.json
      messages.jsonl
      tasks.json
    .shadow-vcs/
    memory.db
```

The workspace path itself remains the user project directory. Internal session data is keyed by workspace uuid under `PROJECT_ROOT/.agent/workspaces/`.

## API Surface

Common endpoints:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/workspace` | current workspace |
| `POST` | `/api/workspace/set` | switch workspace |
| `POST` | `/api/session` | create session |
| `GET` | `/api/sessions` | list sessions in current workspace |
| `GET` | `/api/sessions/all` | list sessions across registered workspaces |
| `DELETE` | `/api/session/{sid}` | delete session |
| `GET` | `/api/session/{sid}/history` | persisted message history |
| `POST` | `/api/session/{sid}/chat` | start a chat turn and stream SSE |
| `GET` | `/api/session/{sid}/stream` | reconnect SSE stream |
| `GET` | `/api/session/{sid}/recover` | recover messages and runtime state |
| `POST` | `/api/session/{sid}/respond` | answer pending human input |
| `POST` | `/api/session/{sid}/interrupt` | interrupt active run |
| `GET` | `/api/session/{sid}/commits` | shadow commit list |
| `GET` | `/api/session/{sid}/commits/{sha}` | shadow commit details |
| `POST` | `/api/session/{sid}/checkout` | restore workspace to a commit |
| `GET` | `/api/metrics/llm/calls` | LLM call rows |
| `GET` | `/api/metrics/llm/summary` | LLM summary |
| `GET` | `/api/metrics/llm/dashboard` | LLM dashboard |
