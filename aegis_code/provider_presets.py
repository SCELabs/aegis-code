from __future__ import annotations

from pathlib import Path

import yaml

from aegis_code.config import ensure_project_files, project_paths


PRESETS = {
    "openai": {
        "cheap": "openai:gpt-4.1-nano",
        "mid": "openai:gpt-4.1-mini",
        "premium": "openai:gpt-4.1",
    },
    "cheap-openai": {
        "cheap": "openai:gpt-4.1-nano",
        "mid": "openai:gpt-4.1-nano",
        "premium": "openai:gpt-4.1-mini",
    },
    "anthropic": {
        "cheap": "anthropic:claude-3-haiku",
        "mid": "anthropic:claude-3-5-haiku",
        "premium": "anthropic:claude-3-5-sonnet",
    },
    "local-ollama": {
        "cheap": "ollama:qwen2.5-coder:7b",
        "mid": "ollama:qwen2.5-coder:14b",
        "premium": "ollama:qwen2.5-coder:32b",
    },
}


def apply_preset(name: str, cwd: Path) -> dict:
    preset_name = str(name)
    if preset_name not in PRESETS:
        return {"applied": False, "reason": "not_found"}

    ensure_project_files(cwd=cwd, force=False)
    config_path = project_paths(cwd)["config_path"]
    raw_data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw_data, dict):
        raw_data = {}
    raw_data["models"] = dict(PRESETS[preset_name])
    config_path.write_text(yaml.safe_dump(raw_data, sort_keys=False), encoding="utf-8")
    return {"applied": True, "preset": preset_name}
