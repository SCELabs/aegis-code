from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from aegis_code.config import load_config
from aegis_code.models import AegisDecision
from aegis_code.secrets import resolve_key

DEFAULT_AEGIS_BASE_URL = "https://aegis-backend-production-4b47.up.railway.app"


def _get_attr_or_key(source: Any, key: str, default: Any) -> Any:
    if source is None:
        return default
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


class AegisBackendClient:
    """Small adapter around scelabs-aegis.

    The MVP is intentionally defensive here so local dev still works without a
    live backend client object.
    """

    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self._sdk_client = self._build_sdk_client()

    def _build_sdk_client(self) -> Any | None:
        # Best-effort support for likely package layouts.
        candidates = [
            ("scelabs_aegis", "AegisClient"),
            ("scelabs_aegis.client", "AegisClient"),
            ("aegis", "AegisClient"),
            ("aegis.client", "AegisClient"),
        ]
        for module_name, class_name in candidates:
            try:
                mod = __import__(module_name, fromlist=[class_name])
                cls = getattr(mod, class_name, None)
                if cls is None:
                    continue
                kwargs: dict[str, Any] = {}
                if self.api_key:
                    kwargs["api_key"] = self.api_key
                if self.base_url:
                    kwargs["base_url"] = self.base_url
                return cls(**kwargs)
            except Exception:
                continue
        return None

    def step_scope(
        self,
        *,
        step_name: str,
        step_input: dict[str, Any],
        symptoms: list[str],
        severity: str,
        metadata: dict[str, Any],
    ) -> AegisDecision:
        if self._sdk_client is None:
            return AegisDecision(
                note="Aegis SDK client unavailable; using fallback guidance.",
                execution={"status": "unavailable"},
            )

        try:
            auto_client = self._sdk_client.auto()
            result = auto_client.step(
                step_name=step_name,
                step_input=step_input,
                symptoms=symptoms,
                severity=severity,
                metadata=metadata,
            )
            return AegisDecision(
                model_tier=str(_get_attr_or_key(result, "model_tier", "mid")),
                context_mode=str(_get_attr_or_key(result, "context_mode", "balanced")),
                max_retries=int(_get_attr_or_key(result, "max_retries", 1)),
                allow_escalation=bool(
                    _get_attr_or_key(result, "allow_escalation", False)
                ),
                execution=_get_attr_or_key(result, "execution", {}) or {},
                note="ok",
            )
        except Exception as exc:
            return AegisDecision(
                note=f"Aegis auto.step failed: {exc}",
                execution={"status": "error", "error": str(exc)},
            )


def resolve_base_url(cwd: Path) -> str:
    env_base_url = os.environ.get("AEGIS_BASE_URL", "").strip()
    if env_base_url:
        return env_base_url
    cfg = load_config(cwd)
    cfg_base_url = str(cfg.aegis.base_url or "").strip()
    if cfg_base_url:
        return cfg_base_url
    return DEFAULT_AEGIS_BASE_URL


def client_from_env(default_base_url: str) -> AegisBackendClient:
    apply_resolved_aegis_env(Path.cwd(), default_base_url=default_base_url)
    return AegisBackendClient(
        api_key=os.getenv("AEGIS_API_KEY"),
        base_url=os.getenv("AEGIS_BASE_URL", resolve_base_url(Path.cwd())),
    )


def apply_resolved_aegis_env(cwd: Path, default_base_url: str | None = None) -> None:
    if not os.environ.get("AEGIS_API_KEY", "").strip():
        api_key = resolve_key("AEGIS_API_KEY", cwd)
        if api_key:
            os.environ["AEGIS_API_KEY"] = api_key

    if not os.environ.get("AEGIS_BASE_URL", "").strip():
        resolved_base_url = resolve_key("AEGIS_BASE_URL", cwd)
        if resolved_base_url:
            os.environ["AEGIS_BASE_URL"] = resolved_base_url
        else:
            os.environ["AEGIS_BASE_URL"] = resolve_base_url(cwd)
