from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

FREE_TIER_CALL_LIMIT = 100


def _usage_path(cwd: Path) -> Path:
    return cwd / ".aegis" / "usage.json"


def _default_usage() -> dict:
    return {
        "calls": 0,
        "successful": 0,
        "fallbacks": 0,
        "actions_applied": 0,
        "last_used": None,
    }


def load_usage(cwd: Path) -> dict:
    path = _usage_path(cwd)
    if not path.exists():
        return _default_usage()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _default_usage()
    if not isinstance(data, dict):
        return _default_usage()
    usage = _default_usage()
    for key in ("calls", "successful", "fallbacks", "actions_applied"):
        value = data.get(key, 0)
        try:
            usage[key] = max(0, int(value))
        except Exception:
            usage[key] = 0
    last_used = data.get("last_used")
    usage["last_used"] = str(last_used) if isinstance(last_used, str) else None
    return usage


def save_usage(data: dict, cwd: Path) -> None:
    path = _usage_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _default_usage()
    for key in ("calls", "successful", "fallbacks", "actions_applied"):
        value = data.get(key, 0)
        try:
            payload[key] = max(0, int(value))
        except Exception:
            payload[key] = 0
    last_used = data.get("last_used")
    payload["last_used"] = str(last_used) if isinstance(last_used, str) else None
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def update_usage(impact: dict, cwd: Path) -> None:
    usage = load_usage(cwd)
    client_available = bool(impact.get("client_available", False))
    used = bool(impact.get("used", False))
    fallback_used = bool(impact.get("fallback_used", False))
    action_count = int(impact.get("action_count", 0) or 0)

    if client_available:
        usage["calls"] = int(usage.get("calls", 0)) + 1
    if used:
        usage["successful"] = int(usage.get("successful", 0)) + 1
    if fallback_used:
        usage["fallbacks"] = int(usage.get("fallbacks", 0)) + 1
    usage["actions_applied"] = int(usage.get("actions_applied", 0)) + max(0, action_count)
    usage["last_used"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    save_usage(usage, cwd)


def get_usage_warning(data: dict) -> dict | None:
    calls = int(data.get("calls", 0) or 0)
    limit = int(FREE_TIER_CALL_LIMIT)
    approaching_threshold = int(limit * 0.9)
    if calls >= limit:
        return {"type": "limit_reached", "limit": limit}
    if calls >= approaching_threshold:
        return {"type": "approaching_limit", "limit": limit}
    return None
