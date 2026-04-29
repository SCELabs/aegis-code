from __future__ import annotations

import json
from pathlib import Path

from aegis_code.aegis_client import DEFAULT_AEGIS_BASE_URL, resolve_base_url
from aegis_code.onboard import run_onboard


class _FakeResponse:
    def __init__(self, body: str) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body.encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        _ = exc_type, exc, tb
        return False


def test_base_url_env_priority(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "aegis-code.yml").write_text(
        'aegis:\n  base_url: "https://config.example"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("AEGIS_BASE_URL", "https://env.example")
    assert resolve_base_url(tmp_path) == "https://env.example"


def test_base_url_config_fallback(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AEGIS_BASE_URL", raising=False)
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "aegis-code.yml").write_text(
        'aegis:\n  base_url: "https://config.example"\n',
        encoding="utf-8",
    )
    assert resolve_base_url(tmp_path) == "https://config.example"


def test_base_url_default_fallback(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AEGIS_BASE_URL", raising=False)
    assert resolve_base_url(tmp_path) == DEFAULT_AEGIS_BASE_URL


def test_onboard_uses_default_url(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AEGIS_BASE_URL", raising=False)
    captured = {"url": None}
    body = json.dumps({"account_id": "a", "api_key": "secret", "plan": "free", "limits": {}})

    def _fake_urlopen(request, timeout=10):
        _ = timeout
        captured["url"] = request.full_url
        return _FakeResponse(body)

    monkeypatch.setattr("aegis_code.onboard.urlopen", _fake_urlopen)
    result = run_onboard(email="user@example.com", cwd=tmp_path)
    assert result.get("success", False) is True
    assert captured["url"] == f"{DEFAULT_AEGIS_BASE_URL}/v1/onboard"
