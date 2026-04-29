from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from aegis_code.models import (
    AegisConfig,
    AppConfig,
    CommandsConfig,
    ModelConfig,
    PatchesConfig,
    ProvidersConfig,
)
from aegis_code.secrets import resolve_key


AegisDirName = ".aegis"
ConfigFileName = "aegis-code.yml"
ProjectModelName = "project_model.md"

DEFAULT_PROJECT_MODEL = """# Project Model

Describe this repository's goals, architecture, and constraints.
This file is used as a local planning/context anchor for aegis-code.
"""


def default_config() -> AppConfig:
    return AppConfig()


def default_config_yaml(test_command: str = "pytest -q") -> str:
    return (
        "mode: balanced\n"
        "budget_per_task: 1.0\n"
        "models:\n"
        "  cheap: openai:gpt-4.1-nano\n"
        "  mid: openai:gpt-4.1-mini\n"
        "  premium: openai:gpt-4.1\n"
        "commands:\n"
        f"  test: \"{test_command}\"\n"
        "  lint: \"\"\n"
        "aegis:\n"
        "  base_url: \"https://aegis-backend-production-4b47.up.railway.app\"\n"
        "  enhanced_runtime: false\n"
        "providers:\n"
        "  enabled: false\n"
        "  provider: \"openai\"\n"
        "  api_key_env: \"OPENAI_API_KEY\"\n"
        "patches:\n"
        "  generate_diff: false\n"
        "  max_context_chars: 12000\n"
        "  output_file: \".aegis/runs/latest.diff\"\n"
    )


def project_paths(cwd: Path | None = None) -> dict[str, Path]:
    root = cwd or Path.cwd()
    aegis_dir = root / AegisDirName
    return {
        "root": root,
        "aegis_dir": aegis_dir,
        "config_path": aegis_dir / ConfigFileName,
        "project_model_path": aegis_dir / ProjectModelName,
        "workspace_path": aegis_dir / "workspace.json",
        "runs_dir": aegis_dir / "runs",
        "latest_json": aegis_dir / "runs" / "latest.json",
        "latest_md": aegis_dir / "runs" / "latest.md",
        "latest_diff": aegis_dir / "runs" / "latest.diff",
    }


def ensure_project_files(
    cwd: Path | None = None,
    force: bool = False,
    test_command: str | None = None,
) -> dict[str, Any]:
    paths = project_paths(cwd)
    paths["aegis_dir"].mkdir(parents=True, exist_ok=True)
    created: dict[str, bool] = {"config_created": False, "project_model_created": False}

    if force or not paths["config_path"].exists():
        selected_test_command = test_command if test_command is not None else "pytest -q"
        paths["config_path"].write_text(
            default_config_yaml(test_command=selected_test_command),
            encoding="utf-8",
        )
        created["config_created"] = True

    if force or not paths["project_model_path"].exists():
        paths["project_model_path"].write_text(DEFAULT_PROJECT_MODEL, encoding="utf-8")
        created["project_model_created"] = True

    return created


def _merged_config_dict(override_data: dict[str, Any]) -> dict[str, Any]:
    defaults = default_config().to_dict()
    merged = defaults.copy()

    for key, value in override_data.items():
        if key not in merged:
            continue
        if isinstance(value, dict) and isinstance(merged[key], dict):
            nested = merged[key].copy()
            for nested_key, nested_val in value.items():
                if nested_key in nested:
                    nested[nested_key] = nested_val
            merged[key] = nested
        else:
            merged[key] = value
    return merged


def load_config(cwd: Path | None = None) -> AppConfig:
    paths = project_paths(cwd)
    if not paths["config_path"].exists():
        cfg = default_config()
        key_name = str(cfg.providers.api_key_env or "OPENAI_API_KEY").strip() or "OPENAI_API_KEY"
        resolved = resolve_key(key_name, paths["root"])
        if resolved:
            os.environ[key_name] = resolved
        return cfg

    raw_data = yaml.safe_load(paths["config_path"].read_text(encoding="utf-8")) or {}
    if not isinstance(raw_data, dict):
        return default_config()
    merged = _merged_config_dict(raw_data)

    cfg = AppConfig(
        mode=str(merged["mode"]),
        budget_per_task=float(merged["budget_per_task"]),
        models=ModelConfig(**merged["models"]),
        commands=CommandsConfig(**merged["commands"]),
        aegis=AegisConfig(**merged["aegis"]),
        providers=ProvidersConfig(**merged["providers"]),
        patches=PatchesConfig(**merged["patches"]),
    )
    key_name = str(cfg.providers.api_key_env or "OPENAI_API_KEY").strip() or "OPENAI_API_KEY"
    resolved = resolve_key(key_name, paths["root"])
    if resolved:
        os.environ[key_name] = resolved
    return cfg
