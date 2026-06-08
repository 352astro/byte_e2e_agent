"""Browser tools backed by BrowserGym BrowserEnv.

BrowserInspect starts a browser inspection sub-agent. The child session owns a
BrowserGym environment and can observe it with BrowserObserve or act on it with
BrowserAct.
"""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Literal

from browsergym.core.action.highlevel import HighLevelActionSet
from browsergym.core.env import BrowserEnv
from browsergym.core.observation import extract_data_items_from_aria
from browsergym.core.task import OpenEndedTask
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

_browsergym_action_set = HighLevelActionSet(
    subsets=["bid", "coord", "nav"],
    multiaction=False,
    strict=True,
)

# BrowserGym uses Playwright's sync API and a package-global Playwright object.
# Keep all env calls on one worker thread so reset/step/close share the same
# sync runtime and headed windows close reliably.
_browsergym_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="browsergym")


def _is_headless() -> bool:
    from app.core.config import get_settings

    return get_settings().browser_headless


class BrowserGymSession:
    """BrowserGym BrowserEnv lifecycle bound to one agent session."""

    def __init__(self, *, url: str, goal: str) -> None:
        self.url = url
        self.goal = goal
        self.env: BrowserEnv | None = None
        self.obs: dict[str, Any] | None = None
        self.info: dict[str, Any] = {}
        self.reward: float = 0
        self.terminated = False
        self.truncated = False
        self._lock = asyncio.Lock()

    async def start(self) -> dict[str, Any]:
        async with self._lock:
            return await _run_browsergym(self._start_sync)

    def _start_sync(self) -> dict[str, Any]:
        if self.env is not None:
            self.env.close()
        self.env = BrowserEnv(
            task_entrypoint=OpenEndedTask,
            task_kwargs={"start_url": self.url, "goal": self.goal},
            headless=_is_headless(),
            wait_for_user_message=False,
            terminate_on_infeasible=False,
            slow_mo=0,
            action_mapping=_browsergym_action_set.to_python_code,
        )
        self.obs, self.info = self.env.reset(seed=0)
        self.reward = 0
        self.terminated = False
        self.truncated = False
        return self.obs

    async def step(self, action: str) -> dict[str, Any]:
        async with self._lock:
            return await _run_browsergym(lambda: self._step_sync(action))

    def _step_sync(self, action: str) -> dict[str, Any]:
        if self.env is None:
            raise RuntimeError("BrowserGym environment is not open")
        self.obs, self.reward, self.terminated, self.truncated, self.info = self.env.step(action)
        return self.obs

    async def close(self) -> None:
        async with self._lock:
            await _run_browsergym(self._close_sync)

    def _close_sync(self) -> None:
        if self.env is not None:
            self.env.close()
            self.env = None
        self.obs = None


class BrowserGymSessionManager:
    """BrowserGym sessions keyed by agent session id."""

    def __init__(self) -> None:
        self._sessions: dict[str, BrowserGymSession] = {}

    async def start(self, session_id: str, *, url: str, goal: str) -> BrowserGymSession:
        await self.close(session_id)
        session = BrowserGymSession(url=url, goal=goal)
        self._sessions[session_id] = session
        await session.start()
        return session

    def peek(self, session_id: str) -> BrowserGymSession | None:
        return self._sessions.get(session_id)

    async def close(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session is not None:
            await session.close()

    async def close_all(self) -> None:
        sessions = list(self._sessions.values())
        self._sessions.clear()
        await asyncio.gather(*(session.close() for session in sessions), return_exceptions=True)


_browsergym_sessions = BrowserGymSessionManager()


async def _run_browsergym(fn):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_browsergym_executor, fn)


async def close_browser_session(session_id: str) -> None:
    await _browsergym_sessions.close(session_id)


async def close_all_browser_sessions() -> None:
    await _browsergym_sessions.close_all()


def close_all_browser_sessions_sync() -> None:
    asyncio.run(close_all_browser_sessions())


async def start_browsergym_session(
    session_id: str,
    *,
    url: str,
    goal: str,
    max_bytes: int = 50_000,
) -> str:
    """Start a BrowserGym BrowserEnv for a BrowserInspect child session."""
    try:
        session = await _browsergym_sessions.start(session_id, url=url, goal=goal)
    except Exception as exc:
        return f"Error starting BrowserGym environment for {url}: {exc}"
    return _format_browsergym_env_observation(
        session.obs or {},
        max_bytes=max_bytes,
        prefix="Initial BrowserGym observation:",
    )


def _truncate(text: str, max_bytes: int) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text
    truncated = raw[:max_bytes].decode("utf-8", errors="replace")
    return (
        f"{truncated}\n[... truncated at {max_bytes} bytes, {len(raw) - max_bytes} bytes omitted]"
    )


def _format_browsergym_env_observation(
    obs: dict[str, Any],
    *,
    max_bytes: int,
    prefix: str = "",
    detail: Literal["summary", "full"] = "full",
) -> str:
    lines: list[str] = []
    if prefix:
        lines.append(prefix)
    lines.extend(
        [
            f"Title: {_active_browsergym_title(obs)}",
            f"URL: {obs.get('url', '')}",
            f"Viewport: {_browsergym_viewport(obs)}",
            f"Focused bid: {obs.get('focused_element_bid') or '(none)'}",
            f"Open pages: {', '.join(obs.get('open_pages_urls') or []) or '(none)'}",
            f"Last action: {obs.get('last_action') or '(none)'}",
            f"Last action error: {obs.get('last_action_error') or '(none)'}",
            "",
            "── Actionable Elements ──",
        ]
    )
    lines.extend(_format_browsergym_interactive_elements(obs))
    if detail == "full":
        lines.extend(["", "── Page Outline ──"])
        lines.extend(_format_browsergym_page_outline(obs))
        lines.extend(["", "── All BrowserGym Elements ──"])
        lines.extend(_format_browsergym_elements(obs))
    return _truncate("\n".join(lines), max_bytes)


def _browsergym_viewport(obs: dict[str, Any]) -> str:
    screenshot = obs.get("screenshot")
    shape = getattr(screenshot, "shape", None)
    if shape and len(shape) >= 2:
        return f"{shape[1]}x{shape[0]}"
    return "(unknown)"


def _active_browsergym_title(obs: dict[str, Any]) -> str:
    titles = list(obs.get("open_pages_titles") or [])
    active_index = obs.get("active_page_index")
    try:
        idx = int(active_index[0])
    except Exception:
        idx = 0
    if 0 <= idx < len(titles):
        return titles[idx]
    return ""


def _format_browsergym_elements(obs: dict[str, Any], *, max_nodes: int = 140) -> list[str]:
    extra_properties = obs.get("extra_element_properties") or {}
    nodes = (obs.get("axtree_object") or {}).get("nodes", [])
    lines: list[str] = []
    for node in nodes:
        if node.get("ignored"):
            continue
        role = _ax_value(node.get("role"))
        name = _ax_value(node.get("name"))
        value = _ax_value(node.get("value"))
        bid = str(node.get("browsergym_id") or "") or _extract_browsergym_bid_from_ax_node(node)
        if not any([role, name, value, bid]):
            continue
        parts = []
        if bid:
            parts.append(f"[bid={bid}]")
        if role:
            parts.append(role)
        if name:
            parts.append(json.dumps(name, ensure_ascii=False))
        if value:
            parts.append(f"value={json.dumps(value, ensure_ascii=False)}")
        props = extra_properties.get(bid) if bid else None
        if props:
            parts.extend(_format_browsergym_props(props))
        lines.append(" ".join(parts))
        if len(lines) >= max_nodes:
            lines.append(f"... truncated after {max_nodes} accessibility nodes")
            break
    return lines or ["(no BrowserGym elements available)"]


def _format_browsergym_interactive_elements(
    obs: dict[str, Any],
    *,
    max_nodes: int = 120,
) -> list[str]:
    extra_properties = obs.get("extra_element_properties") or {}
    nodes = (obs.get("axtree_object") or {}).get("nodes", [])
    items: list[tuple[float, float, str]] = []
    for node in nodes:
        if node.get("ignored"):
            continue
        bid = str(node.get("browsergym_id") or "") or _extract_browsergym_bid_from_ax_node(node)
        if not bid:
            continue
        props = extra_properties.get(bid) or {}
        role = _ax_value(node.get("role"))
        name = _ax_value(node.get("name"))
        value = _ax_value(node.get("value"))
        if not _is_interactive_browsergym_node(role, props):
            continue
        parts = [f"[bid={bid}]"]
        if role:
            parts.append(role)
        if name:
            parts.append(json.dumps(name, ensure_ascii=False))
        if value:
            parts.append(f"value={json.dumps(value, ensure_ascii=False)}")
        parts.extend(_format_browsergym_props(props))
        bbox = props.get("bbox") or [1_000_000, 1_000_000]
        items.append((float(bbox[1]), float(bbox[0]), " ".join(parts)))

    items.sort(key=lambda item: (item[0], item[1], item[2]))
    lines = [line for _, _, line in items[:max_nodes]]
    if len(items) > max_nodes:
        lines.append(f"... truncated after {max_nodes} visible interactive elements")
    return lines or ["(no visible interactive elements detected)"]


def _format_browsergym_page_outline(obs: dict[str, Any], *, max_nodes: int = 180) -> list[str]:
    extra_properties = obs.get("extra_element_properties") or {}
    nodes = (obs.get("axtree_object") or {}).get("nodes", [])
    by_id = {node.get("nodeId"): node for node in nodes if node.get("nodeId") is not None}
    child_ids = {child for node in nodes for child in node.get("childIds", [])}
    roots = [node for node in nodes if node.get("nodeId") not in child_ids]
    lines: list[str] = []

    def visit(node: dict, depth: int) -> None:
        if len(lines) >= max_nodes or node.get("ignored"):
            return
        role = _ax_value(node.get("role"))
        name = _ax_value(node.get("name"))
        value = _ax_value(node.get("value"))
        bid = str(node.get("browsergym_id") or "") or _extract_browsergym_bid_from_ax_node(node)
        props = extra_properties.get(bid) if bid else None
        if _is_meaningful_outline_node(role, name, value, bid, props):
            parts = ["  " * min(depth, 6) + "-"]
            if bid:
                parts.append(f"[bid={bid}]")
            if role:
                parts.append(role)
            if name:
                parts.append(json.dumps(name, ensure_ascii=False))
            if value:
                parts.append(f"value={json.dumps(value, ensure_ascii=False)}")
            if props:
                parts.extend(_format_browsergym_props(props))
            lines.append(" ".join(parts))
        for child_id in node.get("childIds", []):
            child = by_id.get(child_id)
            if child is not None:
                visit(child, depth + 1)

    for root in roots:
        visit(root, 0)
        if len(lines) >= max_nodes:
            break
    if not lines:
        for node in nodes:
            if len(lines) >= max_nodes or node.get("ignored"):
                continue
            role = _ax_value(node.get("role"))
            name = _ax_value(node.get("name"))
            value = _ax_value(node.get("value"))
            bid = str(node.get("browsergym_id") or "") or _extract_browsergym_bid_from_ax_node(node)
            props = extra_properties.get(bid) if bid else None
            if _is_meaningful_outline_node(role, name, value, bid, props):
                parts = ["-"]
                if bid:
                    parts.append(f"[bid={bid}]")
                if role:
                    parts.append(role)
                if name:
                    parts.append(json.dumps(name, ensure_ascii=False))
                if value:
                    parts.append(f"value={json.dumps(value, ensure_ascii=False)}")
                if props:
                    parts.extend(_format_browsergym_props(props))
                lines.append(" ".join(parts))
    if len(lines) >= max_nodes:
        lines.append(f"... truncated after {max_nodes} outline nodes")
    return lines or ["(page outline unavailable)"]


def _is_interactive_browsergym_node(role: str, props: dict) -> bool:
    interactive_roles = {
        "button",
        "checkbox",
        "combobox",
        "link",
        "menuitem",
        "option",
        "radio",
        "searchbox",
        "slider",
        "spinbutton",
        "switch",
        "tab",
        "textbox",
    }
    return bool(props.get("clickable") or props.get("set_of_marks") or role in interactive_roles)


def _is_meaningful_outline_node(
    role: str,
    name: str,
    value: str,
    bid: str,
    props: dict | None,
) -> bool:
    if bid or value:
        return True
    if role in {
        "heading",
        "button",
        "link",
        "textbox",
        "searchbox",
        "checkbox",
        "radio",
        "combobox",
        "tab",
        "menuitem",
        "StaticText",
        "text",
    }:
        return bool(name)
    return bool(name and props and (props.get("clickable") or props.get("set_of_marks")))


def _format_browsergym_props(props: dict) -> list[str]:
    parts: list[str] = []
    bbox = props.get("bbox")
    if bbox and len(bbox) >= 4:
        parts.append(
            f"bbox=({_fmt_num(bbox[0])},{_fmt_num(bbox[1])},{_fmt_num(bbox[2])},{_fmt_num(bbox[3])})"
        )
    if props.get("visibility") is not None:
        parts.append(f"visible={_fmt_num(props.get('visibility'))}")
    if props.get("clickable"):
        parts.append("clickable")
    if props.get("set_of_marks"):
        parts.append("mark")
    return parts


def _fmt_num(value) -> str:
    try:
        number = float(value)
    except Exception:
        return str(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.2f}"


def _extract_browsergym_bid_from_ax_node(node: dict) -> str:
    for prop in node.get("properties", []):
        if prop.get("name") == "roledescription":
            data_items, _ = extract_data_items_from_aria(_ax_value(prop.get("value")))
            if data_items:
                return data_items[0]
    description = _ax_value(node.get("description"))
    if description:
        data_items, _ = extract_data_items_from_aria(description)
        if data_items:
            return data_items[0]
    return ""


def _ax_value(payload) -> str:
    if isinstance(payload, dict):
        value = payload.get("value", "")
        return "" if value is None else str(value)
    if payload is None:
        return ""
    return str(payload)


def _structured_action_to_browsergym(
    *,
    primitive: str,
    bid: str,
    target: str,
    text: str,
    key: str,
    url: str,
    x: float | None,
    y: float | None,
    to_x: float | None,
    to_y: float | None,
    dx: float,
    dy: float,
    button: str,
    options: str | list[str],
) -> str:
    if primitive in {"click", "dblclick"}:
        _require(bid, "bid")
        return f"{primitive}({_literal(bid)}, {_literal(button)})"
    if primitive == "hover":
        _require(bid, "bid")
        return f"hover({_literal(bid)})"
    if primitive == "fill":
        _require(bid, "bid")
        return f"fill({_literal(bid)}, {_literal(text)})"
    if primitive == "press":
        _require(bid, "bid")
        _require(key, "key")
        return f"press({_literal(bid)}, {_literal(key)})"
    if primitive in {"focus", "clear"}:
        _require(bid, "bid")
        return f"{primitive}({_literal(bid)})"
    if primitive == "select_option":
        _require(bid, "bid")
        if options == "":
            raise ValueError("options is required for select_option")
        return f"select_option({_literal(bid)}, {_literal(options)})"
    if primitive == "drag_and_drop":
        _require(bid, "bid")
        _require(target, "target")
        return f"drag_and_drop({_literal(bid)}, {_literal(target)})"
    if primitive == "mouse_move":
        return f"mouse_move({_required_number(x, 'x')}, {_required_number(y, 'y')})"
    if primitive == "mouse_down":
        return (
            f"mouse_down({_required_number(x, 'x')}, "
            f"{_required_number(y, 'y')}, {_literal(button)})"
        )
    if primitive == "mouse_up":
        return (
            f"mouse_up({_required_number(x, 'x')}, {_required_number(y, 'y')}, {_literal(button)})"
        )
    if primitive in {"mouse_click", "mouse_dblclick"}:
        return (
            f"{primitive}({_required_number(x, 'x')}, "
            f"{_required_number(y, 'y')}, {_literal(button)})"
        )
    if primitive == "mouse_drag_and_drop":
        return (
            f"mouse_drag_and_drop({_required_number(x, 'x')}, "
            f"{_required_number(y, 'y')}, {_required_number(to_x, 'to_x')}, "
            f"{_required_number(to_y, 'to_y')})"
        )
    if primitive in {"keyboard_down", "keyboard_up", "keyboard_press"}:
        _require(key, "key")
        return f"{primitive}({_literal(key)})"
    if primitive == "keyboard_type":
        return f"keyboard_type({_literal(text)})"
    if primitive == "keyboard_insert_text":
        return f"keyboard_insert_text({_literal(text)})"
    if primitive == "scroll":
        return f"scroll({dx}, {dy})"
    if primitive == "goto":
        _require(url, "url")
        return f"goto({_literal(url)})"
    if primitive in {"go_back", "go_forward", "noop"}:
        return f"{primitive}()"
    raise ValueError(f"Unsupported primitive: {primitive}")


def _validate_browsergym_action(action: str) -> str:
    _browsergym_action_set.to_python_code(action)
    return action


def _require(value: str, label: str) -> None:
    if not value:
        raise ValueError(f"{label} is required")


def _required_number(value: float | None, label: str) -> float:
    if value is None:
        raise ValueError(f"{label} is required")
    return value


def _literal(value: Any) -> str:
    return repr(value)


class BrowserObserveInput(BaseModel):
    """BrowserObserve tool input."""

    max_bytes: int = Field(
        default=80_000,
        ge=1000,
        le=500_000,
        description="Maximum UTF-8 bytes to return before truncating.",
    )
    detail: Literal["summary", "full"] = Field(
        default="full",
        description="Observation detail level. Use full when inspecting layout or page content.",
    )


async def browser_observe_handler(
    max_bytes: int = 80_000,
    detail: str = "full",
    *,
    ws=None,
    session_id: str = "",
    interrupt_event=None,
) -> str:
    """Return the current BrowserGym observation for the active BrowserInspect session."""
    if interrupt_event and interrupt_event.is_set():
        return "[BrowserObserve interrupted]"
    browsergym_session = _browsergym_sessions.peek(session_id) if session_id else None
    if browsergym_session is None or browsergym_session.obs is None:
        return "Error: BrowserGym environment is not open. Use BrowserInspect first."
    if detail not in {"summary", "full"}:
        return f"Error: unsupported detail level {detail!r}"
    return _format_browsergym_env_observation(
        browsergym_session.obs,
        max_bytes=max_bytes,
        prefix="Current BrowserGym observation:",
        detail=detail,
    )


browser_observe_tool = StructuredTool.from_function(
    coroutine=browser_observe_handler,
    name="BrowserObserve",
    description=(
        "Observe the current BrowserInspect BrowserGym environment. Does not navigate "
        "or open URLs; it reads the same environment BrowserAct acts on."
    ),
    args_schema=BrowserObserveInput,
)


class BrowserActInput(BaseModel):
    """BrowserAct tool input."""

    max_bytes: int = Field(
        default=50_000,
        ge=1000,
        le=500_000,
        description="Maximum UTF-8 bytes to return before truncating.",
    )
    primitive: Literal[
        "click",
        "dblclick",
        "hover",
        "fill",
        "press",
        "focus",
        "clear",
        "select_option",
        "drag_and_drop",
        "mouse_move",
        "mouse_down",
        "mouse_up",
        "mouse_click",
        "mouse_dblclick",
        "mouse_drag_and_drop",
        "keyboard_down",
        "keyboard_up",
        "keyboard_press",
        "keyboard_type",
        "keyboard_insert_text",
        "scroll",
        "goto",
        "go_back",
        "go_forward",
        "noop",
    ] = Field(
        ...,
        description="BrowserGym action primitive.",
    )
    bid: str = Field(
        default="",
        description="BrowserGym element id from BrowserInspect's observation.",
    )
    target: str = Field(default="", description="Target BrowserGym bid for drag/drop actions.")
    text: str = Field(default="", description="Text for fill/keyboard_type/insert_text.")
    key: str = Field(default="", description="Keyboard key or key combination.")
    url: str = Field(default="", description="URL for goto.")
    x: float | None = Field(default=None, description="Mouse x coordinate.")
    y: float | None = Field(default=None, description="Mouse y coordinate.")
    to_x: float | None = Field(default=None, description="Mouse drag target x coordinate.")
    to_y: float | None = Field(default=None, description="Mouse drag target y coordinate.")
    dx: float = Field(default=0, description="Horizontal scroll delta.")
    dy: float = Field(default=0, description="Vertical scroll delta.")
    button: Literal["left", "middle", "right"] = Field(
        default="left",
        description="Mouse button.",
    )
    options: str | list[str] = Field(
        default="",
        description="Option value(s) for select_option.",
    )


async def browser_act_handler(
    primitive: str,
    max_bytes: int = 50_000,
    bid: str = "",
    target: str = "",
    text: str = "",
    key: str = "",
    url: str = "",
    x: float | None = None,
    y: float | None = None,
    to_x: float | None = None,
    to_y: float | None = None,
    dx: float = 0,
    dy: float = 0,
    button: str = "left",
    options: str | list[str] = "",
    *,
    ws=None,
    session_id: str = "",
    interrupt_event=None,
) -> str:
    """Execute a structured browser action in the session's BrowserGym env."""
    if interrupt_event and interrupt_event.is_set():
        return "[BrowserAct interrupted]"

    action = ""
    try:
        action = _structured_action_to_browsergym(
            primitive=primitive,
            bid=bid,
            target=target,
            text=text,
            key=key,
            url=url,
            x=x,
            y=y,
            to_x=to_x,
            to_y=to_y,
            dx=dx,
            dy=dy,
            button=button,
            options=options,
        )
        action = _validate_browsergym_action(action)
        browsergym_session = _browsergym_sessions.peek(session_id) if session_id else None
        if browsergym_session is None:
            return "Error: BrowserGym environment is not open. Use BrowserInspect first."
        obs = await browsergym_session.step(action)
        return _format_browsergym_env_observation(
            obs,
            max_bytes=max_bytes,
            prefix=f"After action: {action}",
        )
    except Exception as exc:
        label = action or f"primitive={primitive!r}"
        return f"Error executing BrowserAct action {label}: {exc}"


browser_act_tool = StructuredTool.from_function(
    coroutine=browser_act_handler,
    name="BrowserAct",
    description="Execute a structured BrowserGym action in the current BrowserInspect session.",
    args_schema=BrowserActInput,
)


class BrowserInspectInput(BaseModel):
    """BrowserInspect 工具输入参数。"""

    url: str = Field(..., description="URL to open before inspection.")
    max_steps: int = Field(
        default=8,
        ge=1,
        le=20,
        description="Maximum reasoning steps for the inspector sub-agent.",
    )
    prompt: str = Field(
        ...,
        description=(
            "Task for the browser inspector sub-agent after the URL is open "
            "(e.g. 'Check for console errors and verify the Send button exists').\n"
            "\n"
            "CRITICAL: the sub-agent starts with an EMPTY context — it sees "
            "nothing from the parent conversation. You MUST embed ALL relevant "
            "information into this prompt: what code was changed, what the "
            "expected behavior is, which files are involved, any known issues, "
            "and exactly what to inspect. A vague prompt will cause the "
            "sub-agent to miss issues. Be exhaustive."
        ),
    )


async def browser_inspect_handler(**kwargs) -> str:
    """实际执行在 execute_one_tool 中通过名称分发。"""
    return "Error: BrowserInspect must be dispatched via execute_one_tool."


browser_inspect_tool = StructuredTool.from_function(
    coroutine=browser_inspect_handler,
    name="BrowserInspect",
    description="Launch a sub-agent with a BrowserGym environment to inspect a web page.",
    args_schema=BrowserInspectInput,
)
