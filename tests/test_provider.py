from __future__ import annotations

from pathlib import Path

from aegis_code import cli
from aegis_code.config import load_config
from aegis_code.provider_presets import PRESETS, detect_available_providers
from aegis_code.secrets import set_key


def test_provider_status(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    assert cli.main(["init"]) == 0
    exit_code = cli.main(["provider", "status"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Provider configuration:" in out
    assert "- cheap: openai:gpt-4.1-nano" in out
    assert "- mid: openai:gpt-4.1-mini" in out
    assert "- premium: openai:gpt-4.1" in out


def test_provider_model_update(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    assert cli.main(["init"]) == 0
    exit_code = cli.main(["provider", "model", "cheap", "openai:gpt-4.1-nano"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Model updated:" in out
    assert "- cheap -> openai:gpt-4.1-nano" in out


def test_invalid_tier(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    assert cli.main(["init"]) == 0
    exit_code = cli.main(["provider", "model", "fast", "openai:gpt-4.1-nano"])
    out = capsys.readouterr().out
    assert exit_code == 2
    assert "Error: invalid tier" in out


def test_invalid_model_format(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    assert cli.main(["init"]) == 0
    exit_code = cli.main(["provider", "model", "cheap", "gpt-4.1-nano"])
    out = capsys.readouterr().out
    assert exit_code == 2
    assert "Error: invalid model format" in out


def test_config_persistence(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert cli.main(["init"]) == 0
    assert cli.main(["provider", "model", "mid", "anthropic:claude-3-haiku"]) == 0
    cfg = load_config(tmp_path)
    assert cfg.models.mid == "anthropic:claude-3-haiku"


def test_provider_list(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    exit_code = cli.main(["provider", "list"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Available presets:" in out
    for name in PRESETS:
        assert f"- {name}" in out


def test_provider_list_includes_openrouter_and_gemini(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    exit_code = cli.main(["provider", "list"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "- openrouter" in out
    assert "- gemini" in out


def test_apply_preset_success(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    assert cli.main(["init"]) == 0
    exit_code = cli.main(["provider", "preset", "openai"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Preset applied: openai" in out
    assert "- cheap -> openai:gpt-4.1-nano" in out
    assert "- mid -> openai:gpt-4.1-mini" in out
    assert "- premium -> openai:gpt-4.1" in out


def test_apply_preset_invalid(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    assert cli.main(["init"]) == 0
    exit_code = cli.main(["provider", "preset", "unknown"])
    out = capsys.readouterr().out
    assert exit_code == 2
    assert "Error: unknown preset" in out


def test_preset_updates_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert cli.main(["init"]) == 0
    assert cli.main(["provider", "preset", "anthropic"]) == 0
    cfg = load_config(tmp_path)
    assert cfg.models.cheap == PRESETS["anthropic"]["cheap"]
    assert cfg.models.mid == PRESETS["anthropic"]["mid"]
    assert cfg.models.premium == PRESETS["anthropic"]["premium"]


def test_preset_preserves_other_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert cli.main(["init"]) == 0
    cfg_path = tmp_path / ".aegis" / "aegis-code.yml"
    cfg_path.write_text(
        "mode: balanced\n"
        "budget_per_task: 3.5\n"
        "models:\n"
        "  cheap: openai:gpt-4.1-nano\n"
        "  mid: openai:gpt-4.1-mini\n"
        "  premium: openai:gpt-4.1\n"
        "commands:\n"
        "  test: \"pytest -q\"\n"
        "  lint: \"\"\n"
        "aegis:\n"
        "  base_url: \"https://aegis-backend-production-4b47.up.railway.app\"\n"
        "  enhanced_runtime: false\n"
        "providers:\n"
        "  enabled: true\n"
        "  provider: \"openai\"\n"
        "  api_key_env: \"OPENAI_API_KEY\"\n"
        "patches:\n"
        "  generate_diff: false\n"
        "  max_context_chars: 12000\n"
        "  output_file: \".aegis/runs/latest.diff\"\n",
        encoding="utf-8",
    )
    assert cli.main(["provider", "preset", "cheap-openai"]) == 0
    cfg = load_config(tmp_path)
    assert cfg.budget_per_task == 3.5
    assert cfg.providers.enabled is True


def test_apply_openrouter_preset(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert cli.main(["init"]) == 0
    assert cli.main(["provider", "preset", "openrouter"]) == 0
    cfg = load_config(tmp_path)
    assert cfg.models.cheap == PRESETS["openrouter"]["cheap"]
    assert cfg.models.mid == PRESETS["openrouter"]["mid"]
    assert cfg.models.premium == PRESETS["openrouter"]["premium"]


def test_apply_gemini_preset(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert cli.main(["init"]) == 0
    cfg_path = tmp_path / ".aegis" / "aegis-code.yml"
    cfg_path.write_text(
        "mode: balanced\n"
        "budget_per_task: 2.0\n"
        "models:\n"
        "  cheap: openai:gpt-4.1-nano\n"
        "  mid: openai:gpt-4.1-mini\n"
        "  premium: openai:gpt-4.1\n"
        "commands:\n"
        "  test: \"pytest -q\"\n"
        "  lint: \"\"\n"
        "aegis:\n"
        "  base_url: \"https://aegis-backend-production-4b47.up.railway.app\"\n"
        "  enhanced_runtime: false\n"
        "providers:\n"
        "  enabled: true\n"
        "  provider: \"openai\"\n"
        "  api_key_env: \"OPENAI_API_KEY\"\n"
        "patches:\n"
        "  generate_diff: false\n"
        "  max_context_chars: 12000\n"
        "  output_file: \".aegis/runs/latest.diff\"\n",
        encoding="utf-8",
    )
    assert cli.main(["provider", "preset", "gemini"]) == 0
    cfg = load_config(tmp_path)
    assert cfg.models.cheap == PRESETS["gemini"]["cheap"]
    assert cfg.models.mid == PRESETS["gemini"]["mid"]
    assert cfg.models.premium == PRESETS["gemini"]["premium"]
    assert cfg.budget_per_task == 2.0
    assert cfg.providers.enabled is True


def test_provider_detect_no_keys(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    data = detect_available_providers(tmp_path)
    assert data["recommended_preset"] is None
    providers = data["providers"]
    assert all(not bool(item["available"]) for item in providers)


def test_provider_detect_openai(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    set_key("OPENAI_API_KEY", "openai-secret", tmp_path)
    data = detect_available_providers(tmp_path)
    assert data["recommended_preset"] == "openai"
    openai = next(item for item in data["providers"] if item["key"] == "OPENAI_API_KEY")
    assert openai["available"] is True
    assert openai["presets"] == ["openai", "cheap-openai"]


def test_provider_detect_priority(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    set_key("OPENROUTER_API_KEY", "router-secret", tmp_path)
    set_key("GEMINI_API_KEY", "gemini-secret", tmp_path)
    set_key("ANTHROPIC_API_KEY", "anthropic-secret", tmp_path)
    data = detect_available_providers(tmp_path)
    assert data["recommended_preset"] == "anthropic"
    set_key("OPENAI_API_KEY", "openai-secret", tmp_path)
    data2 = detect_available_providers(tmp_path)
    assert data2["recommended_preset"] == "openai"


def test_provider_detect_does_not_print_values(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    set_key("OPENAI_API_KEY", "super-secret-value", tmp_path)
    exit_code = cli.main(["provider", "detect"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "super-secret-value" not in out
    assert "found" in out


def test_provider_detect_cli_output(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    set_key("OPENAI_API_KEY", "openai-secret", tmp_path)
    exit_code = cli.main(["provider", "detect"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Provider detection:" in out
    assert "- OPENAI_API_KEY: found" in out
    assert "  presets: openai, cheap-openai" in out
    assert "- ANTHROPIC_API_KEY: missing" in out
    assert "  presets: anthropic" in out
    assert "- OPENROUTER_API_KEY: missing" in out
    assert "  presets: openrouter" in out
    assert "- GEMINI_API_KEY: missing" in out
    assert "  presets: gemini" in out
    assert "Recommended preset: openai" in out
