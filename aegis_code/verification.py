from __future__ import annotations

from pathlib import Path
from typing import Any

from aegis_code.config import load_config, project_paths
from aegis_code.context.capabilities import detect_capabilities
from aegis_code.probe import load_capabilities


def resolve_verification_command(cwd: Path) -> dict[str, Any]:
    capabilities = load_capabilities(cwd)
    if isinstance(capabilities, dict):
        command = str(capabilities.get("test_command", "") or "").strip()
        observed = bool(capabilities.get("test_command_observed", False))
        if command and observed:
            return {
                "command": command,
                "available": True,
                "source": "capabilities",
                "observed": True,
            }

    cfg = load_config(cwd)
    config_path = project_paths(cwd)["config_path"]
    config_command = str(cfg.commands.test or "").strip()
    if config_path.exists() and config_command:
        return {
            "command": config_command,
            "available": True,
            "source": "config",
            "observed": False,
        }

    detected = detect_capabilities(cwd)
    detected_command = str(detected.get("test_command", "") or "").strip()
    if detected_command:
        return {
            "command": detected_command,
            "available": True,
            "source": "detection",
            "observed": False,
        }

    if config_command:
        return {
            "command": config_command,
            "available": True,
            "source": "config",
            "observed": False,
        }

    return {
        "command": None,
        "available": False,
        "source": "none",
        "observed": False,
    }
