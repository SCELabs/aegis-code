from __future__ import annotations

from typing import Any

from aegis_code.safety.patch_review import render_safety_constraints_for_prompt


def _repo_map_text(context: dict[str, Any]) -> str:
    if not isinstance(context, dict):
        return ""
    repo_map = context.get("repo_map")
    if isinstance(repo_map, dict):
        rendered = str(repo_map.get("rendered", "")).strip()
        if rendered:
            return rendered
    if isinstance(repo_map, str):
        return repo_map.strip()
    return ""


def _append_target_context_text(context: dict[str, Any]) -> str:
    if not isinstance(context, dict):
        return ""
    raw = context.get("append_target_contexts", [])
    if not isinstance(raw, list) or not raw:
        return ""
    blocks: list[str] = ["Append target file context:"]
    for item in raw:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", "") or "").strip()
        imports = item.get("imports", []) if isinstance(item.get("imports"), list) else []
        names = item.get("existing_names", []) if isinstance(item.get("existing_names"), list) else []
        tests = item.get("existing_tests", []) if isinstance(item.get("existing_tests"), list) else []
        js_module_system = str(item.get("js_module_system", "n/a") or "n/a")
        js_test_framework = str(item.get("js_test_framework", "n/a") or "n/a")
        package_json_type = str(item.get("package_json_type", "n/a") or "n/a")
        tail = str(item.get("tail", "") or "")
        blocks.append(f"- path: {path}")
        blocks.append(f"  existing_imports: {', '.join(str(x) for x in imports) if imports else '(none)'}")
        blocks.append(f"  existing_names: {', '.join(str(x) for x in names) if names else '(none)'}")
        blocks.append(f"  existing_tests: {', '.join(str(x) for x in tests) if tests else '(none)'}")
        blocks.append(f"  js_module_system: {js_module_system}")
        blocks.append(f"  js_test_framework: {js_test_framework}")
        blocks.append(f"  package_json_type: {package_json_type}")
        blocks.append("  tail_approx_80_lines:")
        blocks.append(tail if tail else "  (empty)")
    return "\n".join(blocks).strip()


def _relevant_snippets_text(context: dict[str, Any]) -> str:
    if not isinstance(context, dict):
        return ""
    raw = context.get("relevant_file_snippets", [])
    if not isinstance(raw, list) or not raw:
        return ""
    blocks: list[str] = ["Relevant file snippets:"]
    for item in raw:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", "") or "").strip()
        excerpt = str(item.get("excerpt", "") or "").strip()
        if not path or not excerpt:
            continue
        blocks.append(f"- path: {path}")
        blocks.append(excerpt)
    return "\n".join(blocks).strip()


def build_append_prompt(
    *,
    task: str,
    failures: dict[str, Any],
    context: dict[str, Any],
    patch_plan: dict[str, Any],
    aegis_execution: dict[str, Any],
) -> str:
    allowed_targets = patch_plan.get("allowed_targets", [])
    target = str(allowed_targets[0]).strip() if isinstance(allowed_targets, list) and allowed_targets else ""
    repo_map_rendered = _repo_map_text(context)
    append_target_context_text = _append_target_context_text(context)
    relevant_snippets = _relevant_snippets_text(context)
    return (
        "Return only JSON. No markdown. No explanations.\n"
        "Schema:\n"
        "{\n"
        '  "content": "text to append at end of file"\n'
        "}\n"
        "Rules:\n"
        "- return append content only, not full file content\n"
        "- do not return unified diff\n"
        f"- target path: {target}\n"
        "- use the repository map to avoid inventing module names, CLI commands, files, functions, or unsupported options\n"
        "- prefer exact symbols and command patterns already present in the repo\n"
        "- if the repository map conflicts with the task wording, follow the repository map unless the user explicitly requests a change\n"
        "- Do not repeat imports already present in the target file.\n"
        "- Do not add a test/function with a name already present.\n"
        "- Do not duplicate an existing workflow already covered in the target file.\n"
        "- For docs append tasks, document only behavior visible in source snippets.\n"
        "- Do not invent cleanup, sanitization, stripping, punctuation handling, or URL-safe behavior unless present.\n"
        '- If package_json_type is "module" or js_module_system is "esm", do not use require(); use import/export style.\n'
        '- If js_test_framework is "node:test", do not use Jest globals like describe/expect; use node:test style.\n'
        "- Do not introduce unrelated symbols or commands absent from repo map/snippets.\n"
        '- If the requested behavior is already covered, return: {"content": ""}\n'
        f"{render_safety_constraints_for_prompt(task)}"
        f"Task: {task}\n"
        f"Failures: {failures}\n"
        f"Context: {context}\n"
        + (f"Repository map:\n{repo_map_rendered}\n" if repo_map_rendered else "")
        + (
            "Snippet grounding guidance:\n"
            "- Prefer exact behaviors/output observed in provided excerpts.\n"
            "- Do not invent commands/options/modules not present in snippets.\n"
            f"{relevant_snippets}\n"
            if relevant_snippets
            else ""
        )
        + (f"{append_target_context_text}\n" if append_target_context_text else "")
        + f"Patch plan: {patch_plan}\n"
        + f"Aegis execution guidance: {aegis_execution}\n"
    )
