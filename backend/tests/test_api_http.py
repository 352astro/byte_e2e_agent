"""
HTTP 集成测试 — 启动完整 uvicorn 实例，通过真实 HTTP 请求验证 API。

不依赖 TestClient / ASGI 内存调用，而是 subprocess 拉起独立进程，
再用 httpx 对 localhost 发请求并断言响应。

范围：不依赖 LLM 的快速回归基线。chat / checkout 成功路径、409 并发冲突、
respond pending 等需真实 agent 运行的场景留作手工验收。
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_server(
    base_url: str, proc: subprocess.Popen[str], timeout: float = 30.0
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            output = proc.stdout.read() if proc.stdout else ""
            raise RuntimeError(
                f"Server exited early (code={proc.returncode}):\n{output}"
            )
        try:
            resp = httpx.get(f"{base_url}/api/hello", timeout=1.0)
            if resp.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise RuntimeError(f"Server at {base_url} did not become ready within {timeout}s")


def _make_client(base_url: str, timeout: float = 30.0) -> httpx.Client:
    return httpx.Client(
        base_url=base_url,
        timeout=timeout,
        limits=httpx.Limits(max_keepalive_connections=0),
    )


def _read_sse(
    client: httpx.Client,
    method: str,
    path: str,
    **kwargs,
) -> tuple[int, list[str]]:
    lines: list[str] = []
    timeout = kwargs.pop("timeout", 30.0)
    with client.stream(method, path, timeout=timeout, **kwargs) as resp:
        status = resp.status_code
        for line in resp.iter_lines():
            if line:
                lines.append(line)
    return status, lines


def _parse_sse_data(lines: list[str]) -> list[dict]:
    events: list[dict] = []
    for line in lines:
        if line.startswith("data:"):
            events.append(json.loads(line.removeprefix("data:").strip()))
    return events


@pytest.fixture(scope="module")
def api_server() -> str:
    """启动独立 uvicorn 进程，返回 base URL。"""
    port = _find_free_port()
    workspace = tempfile.mkdtemp(prefix="byte_e2e_api_test_")
    env = os.environ.copy()
    env["AGENT_WORKSPACE"] = workspace
    env["LLM_METRICS_DB_PATH"] = str(Path(workspace) / ".agent" / "metrics.db")

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=str(BACKEND_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        _wait_for_server(base_url, proc)
        yield base_url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        shutil.rmtree(workspace, ignore_errors=True)


@pytest.fixture
def client(api_server: str) -> httpx.Client:
    with _make_client(api_server) as http:
        yield http


@pytest.mark.integration
class TestHealthEndpoints:
    def test_root(self, client: httpx.Client) -> None:
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.json() == {"message": "Hello World from FastAPI!"}

    def test_hello(self, client: httpx.Client) -> None:
        resp = client.get("/api/hello")
        assert resp.status_code == 200
        assert resp.json() == {"message": "Hello World from FastAPI!", "status": "ok"}


@pytest.mark.integration
class TestWorkspaceEndpoints:
    def test_get_workspace(self, client: httpx.Client) -> None:
        resp = client.get("/api/workspace")
        assert resp.status_code == 200
        body = resp.json()
        assert "workspace" in body
        assert Path(body["workspace"]).is_dir()

    def test_set_workspace_valid(self, client: httpx.Client) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resp = client.post("/api/workspace/set", json={"path": tmp})
            assert resp.status_code == 200
            assert resp.json()["workspace"] == str(Path(tmp).resolve())

    def test_set_workspace_invalid(self, client: httpx.Client) -> None:
        resp = client.post(
            "/api/workspace/set",
            json={"path": "/this/path/does/not/exist/byte_e2e_test"},
        )
        assert resp.status_code == 400
        assert "detail" in resp.json()


@pytest.mark.integration
class TestSessionEndpoints:
    def test_session_lifecycle(self, client: httpx.Client) -> None:
        create = client.post(
            "/api/session",
            json={"name": "", "preamble": "", "rules": [], "preloaded_skills": []},
        )
        assert create.status_code == 200
        created = create.json()
        assert "session_id" in created
        assert "workspace" in created
        sid = created["session_id"]

        listed = client.get("/api/sessions")
        assert listed.status_code == 200
        sessions = listed.json()
        assert sessions["workspace"] == created["workspace"]

        listed_all = client.get("/api/sessions/all")
        assert listed_all.status_code == 200
        all_body = listed_all.json()
        assert created["workspace"] in all_body["workspaces"]
        all_ids = [item["session_id"] for item in all_body["sessions"]]
        assert sid in all_ids
        assert any(
            item["session_id"] == sid and item["workspace"] == created["workspace"]
            for item in all_body["sessions"]
        )
        assert any(s["session_id"] == sid for s in sessions["sessions"])

        history = client.get(f"/api/session/{sid}/history")
        assert history.status_code == 200
        history_body = history.json()
        assert history_body["session"]["session_id"] == sid
        assert isinstance(history_body["history"], list)

        status = client.get(f"/api/session/{sid}/status")
        assert status.status_code == 200
        status_body = status.json()
        assert status_body["session_running"] is False
        assert status_body["runtime_busy"] is False

        recover = client.get(f"/api/session/{sid}/recover")
        assert recover.status_code == 200
        recover_body = recover.json()
        assert recover_body["session_running"] is False
        assert recover_body["runtime_busy"] is False
        assert isinstance(recover_body["messages"], list)

        commits = client.get(f"/api/session/{sid}/commits")
        assert commits.status_code == 200
        assert isinstance(commits.json()["commits"], list)

        interrupt = client.post(f"/api/session/{sid}/interrupt")
        assert interrupt.status_code == 200
        assert interrupt.json() == {"ok": False}

        deleted = client.delete(f"/api/session/{sid}")
        assert deleted.status_code == 200
        assert deleted.json() == {"ok": True}

        missing = client.get(f"/api/session/{sid}/history")
        assert missing.status_code == 404

    def test_session_not_found(self, client: httpx.Client) -> None:
        sid = "nonexistent123"
        for method, path in [
            ("GET", f"/api/session/{sid}/history"),
            ("GET", f"/api/session/{sid}/status"),
            ("GET", f"/api/session/{sid}/recover"),
            ("GET", f"/api/session/{sid}/commits"),
            ("GET", f"/api/session/{sid}/commits/deadbeef"),
            ("POST", f"/api/session/{sid}/checkout"),
            ("POST", f"/api/session/{sid}/chat"),
        ]:
            kwargs: dict = {}
            if method == "POST" and path.endswith("/checkout"):
                kwargs["json"] = {}
            elif method == "POST" and path.endswith("/chat"):
                kwargs["json"] = {"question": "hello", "max_steps": 1}
            resp = client.request(method, path, **kwargs)
            assert resp.status_code == 404, f"{method} {path} expected 404"

        status, _ = _read_sse(client, "GET", f"/api/session/{sid}/stream")
        assert status == 404

        # DELETE 是幂等的：不存在的 session 也返回 200
        delete_resp = client.delete(f"/api/session/{sid}")
        assert delete_resp.status_code == 200
        assert delete_resp.json() == {"ok": True}


@pytest.mark.integration
class TestInterruptEndpoints:
    def test_global_interrupt(self, client: httpx.Client) -> None:
        resp = client.post("/api/interrupt")
        assert resp.status_code == 200
        assert resp.json() == {"ok": False}


@pytest.mark.integration
class TestMetricsEndpoints:
    def test_metrics_empty(self, client: httpx.Client) -> None:
        calls = client.get("/api/metrics/llm/calls")
        assert calls.status_code == 200
        calls_body = calls.json()
        assert calls_body["items"] == []
        assert calls_body["pagination"]["total"] == 0

        summary = client.get("/api/metrics/llm/summary")
        assert summary.status_code == 200
        summary_body = summary.json()
        assert summary_body["total_calls"] == 0

        dashboard = client.get("/api/metrics/llm/dashboard")
        assert dashboard.status_code == 200
        dashboard_body = dashboard.json()
        assert dashboard_body["summary"]["total_calls"] == 0
        assert dashboard_body["recent_calls"] == []

    def test_metrics_query_params(self, client: httpx.Client) -> None:
        create = client.post(
            "/api/session",
            json={"name": "", "preamble": "", "rules": [], "preloaded_skills": []},
        )
        assert create.status_code == 200
        sid = create.json()["session_id"]
        try:
            calls = client.get(
                "/api/metrics/llm/calls", params={"limit": 10, "offset": 0}
            )
            assert calls.status_code == 200
            body = calls.json()
            assert body["pagination"]["limit"] == 10
            assert body["pagination"]["offset"] == 0

            filtered = client.get(
                "/api/metrics/llm/summary", params={"session_id": sid}
            )
            assert filtered.status_code == 200
            assert filtered.json()["total_calls"] == 0

            dashboard = client.get(
                "/api/metrics/llm/dashboard",
                params={"limit": 5, "session_id": sid},
            )
            assert dashboard.status_code == 200
            assert len(dashboard.json()["recent_calls"]) == 0
        finally:
            client.delete(f"/api/session/{sid}")


@pytest.mark.integration
class TestStreamEndpoints:
    def test_stream_idle_empty_session(self, client: httpx.Client) -> None:
        create = client.post(
            "/api/session",
            json={"name": "", "preamble": "", "rules": [], "preloaded_skills": []},
        )
        assert create.status_code == 200
        sid = create.json()["session_id"]
        try:
            status, lines = _read_sse(client, "GET", f"/api/session/{sid}/stream")
            assert status == 200
            assert _parse_sse_data(lines) == []
        finally:
            client.delete(f"/api/session/{sid}")
