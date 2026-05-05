from __future__ import annotations

import os
from typing import Any

from aegis_code.providers.base import (
    _strip_provider_prefix,
    _trim_context,
    build_diff_prompt,
    build_structured_edit_prompt,
    is_plausible_diff,
)


def generate_patch_diff_openai(
    *,
    model: str,
    task: str,
    failures: dict[str, Any],
    context: dict[str, Any],
    patch_plan: dict[str, Any],
    aegis_execution: dict[str, Any],
    api_key_env: str,
    sll_guidance: dict[str, Any] | None = None,
    max_context_chars: int,
) -> dict[str, Any]:
    trimmed_model = _strip_provider_prefix(model)
    api_key = os.getenv(api_key_env, "")
    if not api_key:
        return {
            "available": False,
            "provider": "openai",
            "model": trimmed_model,
            "diff": "",
            "error": f"Missing API key env: {api_key_env}",
        }
    try:
        from openai import OpenAI
    except Exception:
        return {
            "available": False,
            "provider": "openai",
            "model": trimmed_model,
            "diff": "",
            "error": "openai package is not installed.",
        }
    try:
        client = OpenAI(api_key=api_key)
        prompt = build_diff_prompt(
            task=task,
            failures=failures,
            context=_trim_context(context, max_context_chars),
            patch_plan=patch_plan,
            aegis_execution=aegis_execution,
            sll_guidance=sll_guidance,
        )
        response = client.chat.completions.create(
            model=trimmed_model,
            temperature=0,
            messages=[
                {"role": "system", "content": "Return only unified diff text."},
                {"role": "user", "content": prompt},
            ],
        )
        content = ""
        choices = getattr(response, "choices", [])
        if choices:
            message = getattr(choices[0], "message", None)
            content = str(getattr(message, "content", "") or "")
        diff_text = content.strip()
        if not is_plausible_diff(diff_text):
            return {
                "available": False,
                "provider": "openai",
                "model": trimmed_model,
                "diff": "",
                "error": "Provider output did not look like a unified diff.",
            }
        return {
            "available": True,
            "provider": "openai",
            "model": trimmed_model,
            "diff": diff_text,
            "error": None,
        }
    except Exception as exc:
        return {
            "available": False,
            "provider": "openai",
            "model": trimmed_model,
            "diff": "",
            "error": str(exc),
        }


def generate_structured_edits_openai(
    *,
    model: str,
    task: str,
    failures: dict[str, Any],
    context: dict[str, Any],
    patch_plan: dict[str, Any],
    aegis_execution: dict[str, Any],
    api_key_env: str,
    max_context_chars: int,
) -> dict[str, Any]:
    trimmed_model = _strip_provider_prefix(model)
    api_key = os.getenv(api_key_env, "")
    if not api_key:
        return {"available": False, "provider": "openai", "model": trimmed_model, "text": "", "error": f"Missing API key env: {api_key_env}"}
    try:
        from openai import OpenAI
    except Exception:
        return {"available": False, "provider": "openai", "model": trimmed_model, "text": "", "error": "openai package is not installed."}
    try:
        client = OpenAI(api_key=api_key)
        prompt = build_structured_edit_prompt(
            task=task,
            failures=failures,
            context=_trim_context(context, max_context_chars),
            patch_plan=patch_plan,
            aegis_execution=aegis_execution,
        )
        response = client.chat.completions.create(
            model=trimmed_model,
            temperature=0,
            messages=[
                {"role": "system", "content": "Return only JSON."},
                {"role": "user", "content": prompt},
            ],
        )
        content = ""
        choices = getattr(response, "choices", [])
        if choices:
            message = getattr(choices[0], "message", None)
            content = str(getattr(message, "content", "") or "")
        return {"available": True, "provider": "openai", "model": trimmed_model, "text": content.strip(), "error": None}
    except Exception as exc:
        return {"available": False, "provider": "openai", "model": trimmed_model, "text": "", "error": str(exc)}
