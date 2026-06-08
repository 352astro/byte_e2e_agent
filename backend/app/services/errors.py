"""Domain exceptions for the service layer.

Routers map these to HTTP status codes; services raise them instead of raw
KeyError / RuntimeError / ValueError where possible.
"""

from __future__ import annotations


class ServiceError(Exception):
    """Base class for service-layer errors."""


class SessionNotFound(ServiceError):
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        super().__init__(f"Session not found: {session_id}")


class AmbiguousSession(ServiceError):
    def __init__(self, session_id: str, workspaces: list[str]) -> None:
        self.session_id = session_id
        self.workspaces = workspaces
        joined = ", ".join(workspaces)
        super().__init__(f"Session id is ambiguous: {session_id} ({joined})")


class CommitNotFound(ServiceError):
    def __init__(self, sha: str) -> None:
        self.sha = sha
        super().__init__(f"Commit not found: {sha}")


class AgentBusy(ServiceError):
    """Raised when the workspace runtime is already running a task."""

    def __init__(
        self,
        message: str = "Another agent task is already running in this workspace",
    ) -> None:
        super().__init__(message)


class PendingRequestNotFound(ServiceError):
    def __init__(self, transcript_id: str) -> None:
        self.transcript_id = transcript_id
        super().__init__(f"No pending request: {transcript_id}")


class InvalidWorkspace(ServiceError):
    pass


def is_runtime_busy_error(exc: RuntimeError) -> bool:
    return "Runtime already running" in str(exc)
