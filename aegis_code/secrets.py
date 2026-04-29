from __future__ import annotations

import json
import os
from pathlib import Path


def _secrets_path(cwd: Path) -> Path:
    return cwd / ".aegis" / "secrets.local.json"


def _ensure_gitignore(cwd: Path) -> None:
    path = cwd / ".gitignore"
    required = [".aegis/secrets.local.json", ".env"]
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


def load_secrets(cwd: Path) -> dict:
    path = _secrets_path(cwd)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


def save_secrets(data: dict, cwd: Path) -> None:
    path = _secrets_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def set_key(name: str, value: str, cwd: Path) -> dict:
    key_name = name.upper()
    _ensure_gitignore(cwd)
    data = load_secrets(cwd)
    data[key_name] = value
    save_secrets(data, cwd)
    return {"set": True, "name": key_name}


def clear_key(name: str, cwd: Path) -> dict:
    key_name = name.upper()
    data = load_secrets(cwd)
    existed = key_name in data
    if existed:
        del data[key_name]
        save_secrets(data, cwd)
    return {"cleared": existed, "name": key_name}


def get_status(cwd: Path) -> dict:
    data = load_secrets(cwd)
    key_names = sorted(set(data.keys()) | {"OPENAI_API_KEY", "AEGIS_API_KEY"})
    keys = [{"name": name, "present": bool(data.get(name))} for name in key_names]
    return {"keys": keys}


def resolve_key(name: str, cwd: Path) -> str | None:
    key_name = name.upper()

    env_value = os.environ.get(key_name, "").strip()
    if env_value:
        return env_value

    env_path = cwd / ".env"
    if env_path.exists():
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            left, right = line.split("=", 1)
            if left.strip().upper() != key_name:
                continue
            value = right.strip().strip("'").strip('"')
            if value:
                return value

    secrets = load_secrets(cwd)
    secret_value = str(secrets.get(key_name, "")).strip()
    if secret_value:
        return secret_value
    return None
