from __future__ import annotations

from typing import Any

from aegis_code.providers.openai_compatible import generate_patch_diff_openai_compatible
from aegis_code.providers.openai_compatible import generate_structured_edits_openai_compatible
from aegis_code.providers.openai_provider import generate_patch_diff_openai
from aegis_code.providers.openai_provider import generate_structured_edits_openai


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
    base_url: str,
    max_context_chars: int,
    sll_guidance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected = provider.strip().lower()
    if selected == "openai":
        return generate_patch_diff_openai(
            model=model,
            task=task,
            failures=failures,
            context=context,
            patch_plan=patch_plan,
            aegis_execution=aegis_execution,
            api_key_env=api_key_env,
            sll_guidance=sll_guidance,
            max_context_chars=max_context_chars,
        )
    if selected == "openai-compatible":
        return generate_patch_diff_openai_compatible(
            model=model,
            task=task,
            failures=failures,
            context=context,
            patch_plan=patch_plan,
            aegis_execution=aegis_execution,
            api_key_env=api_key_env,
            base_url=base_url,
            sll_guidance=sll_guidance,
            max_context_chars=max_context_chars,
        )
    else:
        return {
            "available": False,
            "provider": selected or provider,
            "model": model,
            "diff": "",
            "error": f"Unsupported provider: {provider}",
        }


def generate_structured_edits(
    *,
    provider: str,
    model: str,
    task: str,
    failures: dict[str, Any],
    context: dict[str, Any],
    patch_plan: dict[str, Any],
    aegis_execution: dict[str, Any],
    api_key_env: str,
    base_url: str,
    max_context_chars: int,
) -> dict[str, Any]:
    selected = provider.strip().lower()
    if selected == "openai":
        return generate_structured_edits_openai(
            model=model,
            task=task,
            failures=failures,
            context=context,
            patch_plan=patch_plan,
            aegis_execution=aegis_execution,
            api_key_env=api_key_env,
            max_context_chars=max_context_chars,
        )
    if selected == "openai-compatible":
        return generate_structured_edits_openai_compatible(
            provider="openai-compatible",
            model=model,
            task=task,
            failures=failures,
            context=context,
            patch_plan=patch_plan,
            aegis_execution=aegis_execution,
            api_key_env=api_key_env,
            base_url=base_url,
            max_context_chars=max_context_chars,
        )
    return {
        "available": False,
        "provider": selected or provider,
        "model": model,
        "text": "",
        "error": f"Unsupported provider: {provider}",
    }
