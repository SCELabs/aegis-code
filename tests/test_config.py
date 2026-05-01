from __future__ import annotations

from pathlib import Path

from aegis_code.config import ensure_project_files, load_config, project_paths


def test_init_creates_default_files(tmp_path: Path) -> None:
    created = ensure_project_files(cwd=tmp_path, force=False)
    paths = project_paths(tmp_path)
    assert paths["aegis_dir"].exists()
    assert paths["config_path"].exists()
    assert paths["project_model_path"].exists()
    assert created["config_created"] is True
    assert created["project_model_created"] is True


def test_load_config_uses_defaults_when_missing(tmp_path: Path) -> None:
    cfg = load_config(tmp_path)
    assert cfg.mode == "balanced"
    assert cfg.models.mid == "openai:gpt-4.1-mini"
    assert cfg.commands.test == "pytest -q"
    assert cfg.providers.enabled is False
    assert cfg.providers.timeout_seconds == 60
    assert cfg.patches.generate_diff is False
    assert cfg.aegis.control_enabled == "auto"


def test_load_config_reads_legacy_enhanced_runtime_flag(tmp_path: Path) -> None:
    ensure_project_files(cwd=tmp_path, force=True)
    cfg_path = project_paths(tmp_path)["config_path"]
    cfg_path.write_text(
        "aegis:\n  base_url: \"https://example.test\"\n  enhanced_runtime: true\n",
        encoding="utf-8",
    )
    cfg = load_config(tmp_path)
    assert cfg.aegis.base_url == "https://example.test"
    assert cfg.aegis.control_enabled is True
