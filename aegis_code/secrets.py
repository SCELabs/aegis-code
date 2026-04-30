from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _project_secrets_path(cwd: Path) -> Path:
    return cwd / ".aegis" / "secrets.json"


def _legacy_project_secrets_path(cwd: Path) -> Path:
    return cwd / ".aegis" / "secrets.local.json"


def _global_secrets_path() -> Path:
    override = os.environ.get("AEGIS_HOME", "").strip()
    if override:
        return Path(override) / "secrets.json"
    return Path.home() / ".aegis" / "secrets.json"


def _ensure_gitignore(cwd: Path) -> None:
    path = cwd / ".gitignore"
    required = [".aegis/secrets.json", ".aegis/secrets.local.json", ".env"]
    if not path.exists():
        path.write_text("\n".join(required) + "\n", encoding="utf-8")
        return
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    changed = False
    for entry in required:
        if entry not in lines:
            lines.append(entry)
            changed = True
    if changed:
        new_content = "\n".join(lines)
        if content.endswith("\n"):
            new_content += "\n"
        path.write_text(new_content, encoding="utf-8")


def _apply_secure_permissions(path: Path) -> None:
    try:
        if os.name != "nt":
            path.chmod(0o600)
    except Exception:
        pass


def _load_secret_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k).upper(): str(v) for k, v in data.items() if str(v).strip()}


def _save_secret_file(path: Path, data: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    _apply_secure_permissions(path)


def mask_key(value: str) -> str:
    text = str(value or "")
    if len(text) <= 8:
        return "*" * len(text)
    return f"{text[:4]}****{text[-4:]}"


def load_secrets(cwd: Path, scope: str = "project") -> dict[str, str]:
    normalized = str(scope or "project").strip().lower()
    if normalized == "global":
        return _load_secret_file(_global_secrets_path())
    project = _load_secret_file(_project_secrets_path(cwd))
    if project:
        return project
    return _load_secret_file(_legacy_project_secrets_path(cwd))


def save_secrets(data: dict[str, str], cwd: Path, scope: str = "project") -> None:
    normalized = str(scope or "project").strip().lower()
    normalized_data = {str(k).upper(): str(v) for k, v in data.items() if str(v).strip()}
    if normalized == "global":
        _save_secret_file(_global_secrets_path(), normalized_data)
        return
    _ensure_gitignore(cwd)
    _save_secret_file(_project_secrets_path(cwd), normalized_data)


def set_key(name: str, value: str, cwd: Path, scope: str = "project") -> dict[str, Any]:
    key_name = str(name).upper()
    normalized = str(scope or "project").strip().lower()
    data = load_secrets(cwd, scope=normalized)
    data[key_name] = value
    save_secrets(data, cwd, scope=normalized)
    return {"set": True, "name": key_name, "scope": normalized}


def clear_key(name: str, cwd: Path, scope: str = "project") -> dict[str, Any]:
    key_name = str(name).upper()
    normalized = str(scope or "project").strip().lower()
    data = load_secrets(cwd, scope=normalized)
    existed = key_name in data
    if existed:
        del data[key_name]
        save_secrets(data, cwd, scope=normalized)
    return {"cleared": existed, "name": key_name, "scope": normalized}


def list_scoped_keys(cwd: Path) -> dict[str, dict[str, str]]:
    return {
        "global": load_secrets(cwd, scope="global"),
        "project": load_secrets(cwd, scope="project"),
    }


def _read_env_file_key(name: str, cwd: Path) -> str | None:
    key_name = name.upper()
    env_path = cwd / ".env"
    if not env_path.exists():
        return None
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        left, right = line.split("=", 1)
        if left.strip().upper() != key_name:
            continue
        value = right.strip().strip("'").strip('"')
        if value:
            return value
    return None


def resolve_key_source(name: str, cwd: Path) -> dict[str, Any]:
    key_name = str(name).upper()
    env_value = os.environ.get(key_name, "").strip()
    if env_value:
        return {"name": key_name, "source": "env", "present": True, "value": env_value}
    env_file = _read_env_file_key(key_name, cwd)
    if env_file:
        return {"name": key_name, "source": "env", "present": True, "value": env_file}
    project = load_secrets(cwd, scope="project")
    if str(project.get(key_name, "")).strip():
        return {"name": key_name, "source": "project", "present": True, "value": str(project[key_name]).strip()}
    global_data = load_secrets(cwd, scope="global")
    if str(global_data.get(key_name, "")).strip():
        return {"name": key_name, "source": "global", "present": True, "value": str(global_data[key_name]).strip()}
    return {"name": key_name, "source": "missing", "present": False, "value": None}


def get_status(cwd: Path) -> dict[str, Any]:
    project = load_secrets(cwd, scope="project")
    global_data = load_secrets(cwd, scope="global")
    names = sorted(
        set(project.keys())
        | set(global_data.keys())
        | {"OPENAI_API_KEY", "AEGIS_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY"}
    )
    keys = []
    for name in names:
        resolved = resolve_key_source(name, cwd)
        keys.append({"name": name, "source": resolved["source"], "present": bool(resolved["present"])})
    return {"keys": keys}


def resolve_key(name: str, cwd: Path) -> str | None:
    resolved = resolve_key_source(name, cwd)
    value = resolved.get("value")
    if isinstance(value, str) and value.strip():
        return value
    return None
