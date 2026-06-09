from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import workspace_registry as reg


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry_dir = tmp_path / ".agent"
    monkeypatch.setattr(reg, "_REGISTRY_DIR", registry_dir)
    monkeypatch.setattr(reg, "_REGISTRY_FILE", registry_dir / "workspaces.json")


def test_register_and_list_workspaces(tmp_path: Path) -> None:
    ws_a = tmp_path / "ws-a"
    ws_b = tmp_path / "ws-b"
    ws_a.mkdir()
    ws_b.mkdir()

    _, uuid_a = reg.register_workspace(str(ws_a))
    _, uuid_b = reg.register_workspace(str(ws_b))
    _, uuid_a_again = reg.register_workspace(str(ws_a))

    listed = reg.list_workspaces()
    assert listed == {
        uuid_a: str(ws_a.resolve()),
        uuid_b: str(ws_b.resolve()),
    }
    assert uuid_a_again == uuid_a

    data = json.loads(reg._REGISTRY_FILE.read_text(encoding="utf-8"))
    assert len(data["workspaces"]) == 2


def test_list_prunes_missing_directories(tmp_path: Path) -> None:
    alive = tmp_path / "alive"
    alive.mkdir()
    gone = tmp_path / "gone"
    gone.mkdir()

    reg._write_raw({"alive": str(alive.resolve()), "gone": str(gone.resolve())})
    gone.rmdir()

    assert reg.list_workspaces() == {"alive": str(alive.resolve())}
