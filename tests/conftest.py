from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_secret_resolution(monkeypatch, tmp_path):
    monkeypatch.setenv("AEGIS_HOME", str(tmp_path / ".aegis-global"))
    for key in (
        "AEGIS_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY",
        "GEMINI_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

