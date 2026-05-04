from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from aegis_code.aegis_client import resolve_base_url
from aegis_code.secrets import set_key


def run_onboard(email: str, cwd: Path, scope: str = "global") -> dict:
    base_url = resolve_base_url(cwd)
    endpoint = f"{base_url.rstrip('/')}/v1/onboard"
    payload = json.dumps({"email": email}).encode("utf-8")
    request = Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        reason = "http_error"
        try:
            error_body = exc.read().decode("utf-8")
            parsed = json.loads(error_body)
            if isinstance(parsed, dict):
                detail = parsed.get("detail")
                if isinstance(detail, dict):
                    detail_error = str(detail.get("error", "")).strip()
                    if detail_error:
                        reason = detail_error
        except Exception:
            pass
        return {"success": False, "reason": reason, "status_code": int(exc.code)}
    except (URLError, TimeoutError, OSError):
        return {"success": False, "reason": "network_error"}

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return {"success": False, "reason": "invalid_response"}

    if not isinstance(data, dict):
        return {"success": False, "reason": "invalid_response"}
    api_key = str(data.get("api_key", "")).strip()
    if not api_key:
        return {"success": False, "reason": "invalid_response"}

    set_key("AEGIS_API_KEY", api_key, cwd, scope=scope)
    return {"success": True, "scope": str(scope)}
