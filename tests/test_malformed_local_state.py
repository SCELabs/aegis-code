from __future__ import annotations

from pathlib import Path

from aegis_code.budget import get_budget_state, load_budget
from aegis_code.secrets import load_secrets, resolve_key
from aegis_code.workspace import get_status, load_workspace


def test_malformed_budget_json_is_safe(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    budget_path = tmp_path / ".aegis" / "budget.json"
    budget_path.parent.mkdir(parents=True, exist_ok=True)
    budget_path.write_text("{not-json", encoding="utf-8")

    assert load_budget(cwd=tmp_path) is None
    state = get_budget_state(cwd=tmp_path)
    assert state["available"] is False
    assert state["limit"] is None
    assert state["spent_estimate"] is None
    assert state["remaining_estimate"] is None


def test_malformed_secrets_json_is_safe(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    secrets_path = tmp_path / ".aegis" / "secrets.local.json"
    secrets_path.parent.mkdir(parents=True, exist_ok=True)
    secrets_path.write_text("[broken", encoding="utf-8")

    assert load_secrets(tmp_path) == {}
    assert resolve_key("OPENAI_API_KEY", tmp_path) is None


def test_malformed_workspace_json_is_safe(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    workspace_path = tmp_path / ".aegis" / "workspace.json"
    workspace_path.parent.mkdir(parents=True, exist_ok=True)
    workspace_path.write_text("not-json", encoding="utf-8")

    loaded = load_workspace(tmp_path)
    assert loaded == {"version": "0.1", "projects": []}
    status = get_status(tmp_path)
    assert status["exists"] is True
    assert status["project_count"] == 0
    assert status["projects"] == []
