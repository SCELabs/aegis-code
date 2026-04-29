from __future__ import annotations

from pathlib import Path

import yaml

from aegis_code.config import ensure_project_files, project_paths
from aegis_code.secrets import resolve_key


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
    "openrouter": {
        "cheap": "openrouter:deepseek/deepseek-chat",
        "mid": "openrouter:qwen/qwen-2.5-coder-32b-instruct",
        "premium": "openrouter:anthropic/claude-3.5-sonnet",
    },
    "gemini": {
        "cheap": "gemini:gemini-1.5-flash",
        "mid": "gemini:gemini-1.5-pro",
        "premium": "gemini:gemini-1.5-pro",
    },
}

KNOWN_PROVIDER_KEYS = {
    "OPENAI_API_KEY": ["openai", "cheap-openai"],
    "ANTHROPIC_API_KEY": ["anthropic"],
    "OPENROUTER_API_KEY": ["openrouter"],
    "GEMINI_API_KEY": ["gemini"],
}

_RECOMMEND_PRIORITY = ["openai", "anthropic", "openrouter", "gemini"]


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


def detect_available_providers(cwd: Path) -> dict:
    providers: list[dict[str, object]] = []
    available_presets: set[str] = set()
    for key, presets in KNOWN_PROVIDER_KEYS.items():
        available = bool(resolve_key(key, cwd))
        if available:
            for preset in presets:
                available_presets.add(str(preset))
        providers.append(
            {
                "key": key,
                "available": available,
                "presets": list(presets),
            }
        )

    recommended: str | None = None
    for preset in _RECOMMEND_PRIORITY:
        if preset in available_presets:
            recommended = preset
            break

    return {
        "providers": providers,
        "recommended_preset": recommended,
    }
