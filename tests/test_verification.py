from __future__ import annotations

import json
from pathlib import Path

from aegis_code.verification import resolve_verification_command


def test_verification_capabilities_priority_when_observed_true(tmp_path: Path) -> None:
    aegis_dir = tmp_path / ".aegis"
    aegis_dir.mkdir(parents=True, exist_ok=True)
    (aegis_dir / "aegis-code.yml").write_text('commands:\n  test: "python -m pytest -q"\n', encoding="utf-8")
    (aegis_dir / "capabilities.json").write_text(
        json.dumps({"test_command": "pytest -q", "test_command_observed": True}),
        encoding="utf-8",
    )
    resolved = resolve_verification_command(tmp_path)
    assert resolved["command"] == "pytest -q"
    assert resolved["available"] is True
    assert resolved["source"] == "capabilities"
    assert resolved["observed"] is True


def test_verification_config_used_when_capabilities_not_observed(tmp_path: Path) -> None:
    aegis_dir = tmp_path / ".aegis"
    aegis_dir.mkdir(parents=True, exist_ok=True)
    (aegis_dir / "aegis-code.yml").write_text('commands:\n  test: "python -m pytest -q"\n', encoding="utf-8")
    (aegis_dir / "capabilities.json").write_text(
        json.dumps({"test_command": "pytest -q", "test_command_observed": False}),
        encoding="utf-8",
    )
    resolved = resolve_verification_command(tmp_path)
    assert resolved["command"] == "python -m pytest -q"
    assert resolved["available"] is True
    assert resolved["source"] == "config"
    assert resolved["observed"] is False


def test_verification_detection_fallback(tmp_path: Path) -> None:
    aegis_dir = tmp_path / ".aegis"
    aegis_dir.mkdir(parents=True, exist_ok=True)
    (aegis_dir / "aegis-code.yml").write_text('commands:\n  test: ""\n', encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    resolved = resolve_verification_command(tmp_path)
    assert resolved["command"] == "python -m pytest -q"
    assert resolved["available"] is True
    assert resolved["source"] == "detection"
    assert resolved["observed"] is False


def test_verification_none_case(tmp_path: Path) -> None:
    aegis_dir = tmp_path / ".aegis"
    aegis_dir.mkdir(parents=True, exist_ok=True)
    (aegis_dir / "aegis-code.yml").write_text('commands:\n  test: ""\n', encoding="utf-8")
    resolved = resolve_verification_command(tmp_path)
    assert resolved["command"] is None
    assert resolved["available"] is False
    assert resolved["source"] == "none"
    assert resolved["observed"] is False
