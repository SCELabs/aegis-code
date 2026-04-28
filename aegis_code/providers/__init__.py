from __future__ import annotations

from typing import Any

from aegis_code.providers.openai_provider import generate_patch_diff_openai


def generate_patch_diff(
    *,
    provider: str,
    model: str,
    task: str,
    failures: dict[str, Any],
    context: dict[str, Any],
    patch_plan: dict[str, Any],
    aegis_execution: dict[str, Any],
    api_key_env: str,
    max_context_chars: int,
) -> dict[str, Any]:
    selected = provider.strip().lower()
    if selected != "openai":
        return {
            "available": False,
            "provider": selected or provider,
            "model": model,
            "diff": "",
            "error": f"Unsupported provider: {provider}",
        }
    return generate_patch_diff_openai(
        model=model,
        task=task,
        failures=failures,
        context=context,
        patch_plan=patch_plan,
        aegis_execution=aegis_execution,
        api_key_env=api_key_env,
        max_context_chars=max_context_chars,
    )

