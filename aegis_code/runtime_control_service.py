from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from aegis_code.aegis_adapter import get_aegis_guidance
from aegis_code.runtime_control_policy import resolve_control_state


def _to_mapping(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if is_dataclass(raw):
        return asdict(raw)
    if hasattr(raw, "__dict__"):
        return dict(raw.__dict__)
    return {}


class RuntimeControlService:
    def __init__(self, options: Any, config: Any, cwd: Path, advisory_fn: Any | None = None, aegis_client_cls: Any | None = None) -> None:
        self.options = options
        self.config = config
        self.cwd = cwd.resolve()
        self._advisory_fn = advisory_fn or get_aegis_guidance
        self._aegis_client_cls = aegis_client_cls
        self.control_state = (
            resolve_control_state(options=options, config=config, environment={"cwd": self.cwd})
            if config is not None
            else {
                "enabled": True,
                "requested": True,
                "reason": "enabled_by_config",
                "mode": "enabled",
                "source": "config",
                "key_available": True,
            }
        )

    def _aegis_client(self) -> Any | None:
        if self._aegis_client_cls is not None:
            return self._aegis_client_cls
        try:
            from aegis import AegisClient  # type: ignore

            return AegisClient
        except Exception:
            return None

    def is_client_available(self) -> bool:
        return self._aegis_client() is not None

    def _base_url(self, fallback: str = "") -> str:
        if self.config is not None:
            try:
                value = str(getattr(getattr(self.config, "aegis"), "base_url", "") or "").strip()
                if value:
                    return value
            except Exception:
                pass
        return str(fallback or "")

    def _normalize_step_guidance(self, response: Any) -> dict[str, Any]:
        response_map = _to_mapping(response)
        return {
            "model_tier": response_map.get("model_tier"),
            "max_retries": response_map.get("max_retries"),
            "allow_escalation": response_map.get("allow_escalation"),
            "context_mode": response_map.get("context_mode"),
        }

    def get_step_guidance(self, task: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = payload if isinstance(payload, dict) else {}
        if not bool(self.control_state.get("requested", False)):
            raw_reason = str(self.control_state.get("reason", "disabled_by_config") or "disabled_by_config")
            disabled_reason = "no_api_key" if raw_reason == "no_api_key" else "disabled_by_config"
            return {
                "status": "disabled",
                "reason": disabled_reason,
                "policy_reason": raw_reason,
                "response": None,
                "guidance": {},
                "error": None,
            }

        client_cls = self._aegis_client()
        if client_cls is None:
            return {
                "status": "not_available",
                "reason": "import_missing",
                "policy_reason": str(self.control_state.get("reason", "") or ""),
                "response": None,
                "guidance": {},
                "error": None,
            }

        try:
            client = client_cls(base_url=self._base_url(str(data.get("base_url", "") or "")))
            response = client.auto().step(
                step_name=str(data.get("step_name", "aegis-code-runtime") or "aegis-code-runtime"),
                step_input=data.get(
                    "step_input",
                    {
                        "task": task,
                        "mode": data.get("mode"),
                        "dry_run": data.get("dry_run"),
                    },
                ),
                symptoms=data.get("symptoms", ["unstable_workflow"]),
                severity=str(data.get("severity", "medium") or "medium"),
                metadata=data.get(
                    "metadata",
                    {
                        "project_context": data.get("project_context", {}),
                        "budget_state": data.get("budget_state", {}),
                        "runtime_policy": data.get("runtime_policy", {}),
                        "verification": data.get("verification"),
                        "failures": data.get("failures"),
                        "status": data.get("status"),
                    },
                ),
            )
            return {
                "status": "applied",
                "reason": "applied",
                "policy_reason": str(self.control_state.get("reason", "") or ""),
                "response": response,
                "guidance": self._normalize_step_guidance(response),
                "error": None,
            }
        except Exception as exc:
            return {
                "status": "client_error",
                "reason": "client_error",
                "policy_reason": str(self.control_state.get("reason", "") or ""),
                "response": None,
                "guidance": {},
                "error": str(exc),
                "error_type": exc.__class__.__name__,
            }

    def get_advisory_guidance(self, task: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = payload if isinstance(payload, dict) else {}
        try:
            return self._advisory_fn(
                task=task,
                context=data.get("context", {}),
                failures=data.get("failures", {}),
                runtime_policy=data.get("runtime_policy", {}),
                timeout_ms=int(data.get("timeout_ms", 2000) or 2000),
                max_retries=int(data.get("max_retries", 1) or 1),
            )
        except Exception as exc:
            return {"available": False, "error": str(exc)}

    def get_context_refinement(self, task: str, context_text: Any = None) -> dict[str, Any]:
        local_context = context_text if isinstance(context_text, dict) else {}
        if not bool(self.control_state.get("requested", False)):
            return local_context

        client_cls = self._aegis_client()
        if client_cls is None:
            return local_context

        try:
            client = client_cls(base_url=self._base_url())
            payload = client.auto().context(
                objective=task,
                messages=[
                    {"role": "system", "content": "You are refining context for a code modification task."},
                    {"role": "user", "content": json.dumps(local_context, ensure_ascii=True)},
                ],
                constraints=[
                    "Preserve relevant files",
                    "Remove noise",
                    "Prioritize entrypoints and integration points",
                ],
                symptoms=["context_noise"],
                severity="medium",
                metadata={"task_type": "patch_generation"},
            )
            if isinstance(payload, dict):
                scope_data = payload.get("scope_data", {})
                if isinstance(scope_data, dict):
                    cleaned = scope_data.get("cleaned_messages")
                    if isinstance(cleaned, list):
                        for msg in cleaned:
                            if isinstance(msg, dict):
                                content = msg.get("content")
                                if isinstance(content, str):
                                    try:
                                        parsed = json.loads(content)
                                    except Exception:
                                        continue
                                    if isinstance(parsed, dict) and isinstance(parsed.get("files"), list) and parsed.get("files"):
                                        return parsed
                cleaned_messages = payload.get("cleaned_messages")
                if isinstance(cleaned_messages, list):
                    for msg in cleaned_messages:
                        if isinstance(msg, dict):
                            content = msg.get("content")
                            if isinstance(content, str):
                                try:
                                    parsed = json.loads(content)
                                except Exception:
                                    continue
                                if isinstance(parsed, dict) and isinstance(parsed.get("files"), list) and parsed.get("files"):
                                    return parsed
        except Exception:
            return local_context
        return local_context

    def get_corrective_control(self, task: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = payload if isinstance(payload, dict) else {}
        fallback = {
            "applied": False,
            "status": "not_available",
            "reason": "not_available",
            "error": None,
            "constraints": [],
            "context_mode": None,
            "allowed_targets": [],
            "guidance_signals": [],
        }
        client_cls = self._aegis_client()
        if client_cls is None:
            return fallback
        try:
            client = client_cls(base_url=self._base_url(str(data.get("base_url", "") or "")))
            response = client.auto().step(
                step_name="patch_regeneration_correction",
                step_input={
                    "task": task,
                    "task_type": data.get("task_type", "general"),
                    "issues": data.get("issues", []),
                    "validation_errors": data.get("validation_errors", []),
                    "context_files": data.get("context_paths", []),
                },
                symptoms=["low_patch_quality"],
                severity="medium",
                metadata={"task_type": data.get("task_type", "general")},
            )
            if not isinstance(response, dict):
                fallback["status"] = "no_guidance_returned"
                fallback["reason"] = "no_guidance_returned"
                return fallback
            constraints = response.get("constraints", [])
            allowed_targets = response.get("allowed_targets", [])
            guidance_signals = response.get("guidance_signals", [])
            has_guidance = bool(constraints) or bool(allowed_targets) or bool(guidance_signals) or bool(response.get("context_mode"))
            if not has_guidance:
                fallback["status"] = "no_guidance_returned"
                fallback["reason"] = "no_guidance_returned"
                return fallback
            return {
                "applied": True,
                "status": "applied",
                "reason": "applied",
                "error": None,
                "constraints": constraints if isinstance(constraints, list) else [],
                "context_mode": response.get("context_mode"),
                "allowed_targets": allowed_targets if isinstance(allowed_targets, list) else [],
                "guidance_signals": guidance_signals if isinstance(guidance_signals, list) else [],
            }
        except Exception as exc:
            fallback["status"] = "client_error"
            fallback["reason"] = "client_error"
            fallback["error"] = str(exc)
            return fallback

    def get_regeneration_control(self, task: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        _ = task
        data = payload if isinstance(payload, dict) else {}
        fallback = {"status": "not_available", "error": None, "actions": {}}
        client_cls = self._aegis_client()
        if client_cls is None:
            return fallback
        try:
            client = client_cls(base_url=self._base_url(str(data.get("base_url", "") or "")))
            response = client.auto().step(
                step_name="patch_regeneration_control",
                step_input={"control": "hard_invalid_patch"},
                symptoms=["invalid_patch"],
                severity="high",
                metadata=data.get("metadata", {}),
            )
            if isinstance(response, dict):
                return {
                    "status": "applied",
                    "error": None,
                    "actions": response.get("actions", response),
                }
            return {"status": "no_guidance_returned", "error": None, "actions": {}}
        except Exception as exc:
            return {"status": "client_error", "error": str(exc), "actions": {}}
