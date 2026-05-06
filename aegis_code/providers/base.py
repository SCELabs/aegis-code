from __future__ import annotations

from typing import Any

from aegis_code.patches.constraints import build_patch_constraints
from aegis_code.safety.patch_review import render_safety_constraints_for_prompt
from aegis_code.providers.context_builder import (
    build_named_test_file_context,
    extract_named_test_file,
    line_safe_cap,
    shape_test_generation_context,
    trim_context,
)


def _line_safe_cap(content: str, limit: int) -> str:
    return line_safe_cap(content, limit)


def _is_docs_task(task: str, patch_plan: dict[str, Any]) -> bool:
    lowered = str(task or "").lower()
    if any(token in lowered for token in ("readme", "docs", "documentation")):
        return True
    proposed = patch_plan.get("proposed_changes", [])
    if isinstance(proposed, list):
        for item in proposed:
            if not isinstance(item, dict):
                continue
            path = str(item.get("file", "")).strip().lower().replace("\\", "/")
            if path == "readme.md" or path.startswith("docs/"):
                return True
    return False


def _strip_provider_prefix(model: str) -> str:
    if ":" not in model:
        return model
    return model.split(":", 1)[1]


def _trim_context(context: dict[str, Any], max_chars: int) -> dict[str, Any]:
    return trim_context(context, max_chars)


def _extract_named_test_file(task: str) -> str:
    return extract_named_test_file(task)


def _build_named_test_file_context(path: str, content: str) -> dict[str, Any]:
    return build_named_test_file_context(path, content)


def _shape_test_generation_context(
    *,
    task: str,
    context: dict[str, Any],
    patch_plan: dict[str, Any],
) -> dict[str, Any]:
    return shape_test_generation_context(task=task, context=context, patch_plan=patch_plan)


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
        tail = str(item.get("tail", "") or "")
        blocks.append(f"- path: {path}")
        blocks.append(f"  existing_imports: {', '.join(str(x) for x in imports) if imports else '(none)'}")
        blocks.append(f"  existing_names: {', '.join(str(x) for x in names) if names else '(none)'}")
        blocks.append(f"  existing_tests: {', '.join(str(x) for x in tests) if tests else '(none)'}")
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


def build_diff_prompt(
    *,
    task: str,
    failures: dict[str, Any],
    context: dict[str, Any],
    patch_plan: dict[str, Any],
    aegis_execution: dict[str, Any],
    sll_guidance: dict[str, Any] | None = None,
) -> str:
    test_constraints: list[str] = []
    regen_constraints: list[str] = []
    task_type = str(patch_plan.get("task_type", "")).strip().lower()
    target_file = str(patch_plan.get("target_file", "")).strip()
    constraints = build_patch_constraints(task=task, task_type=task_type, context=context)
    raw_regen = patch_plan.get("regeneration_constraints", [])
    if isinstance(raw_regen, list):
        regen_constraints = [f"- {str(item)}" for item in raw_regen if str(item).strip()]
    if task_type == "test_generation":
        named_test_file = str(constraints.get("target_file") or _extract_named_test_file(task))
        test_constraints = [
            "Test-generation guidance:",
        ]
        provider_instructions = constraints.get("provider_instructions", [])
        if isinstance(provider_instructions, list):
            test_constraints.extend(f"- {str(item)}" for item in provider_instructions)
        elif named_test_file:
            test_constraints.extend([f"- Named target file: {named_test_file}", f"- Allowed target: {named_test_file}"])
        if target_file and not any("Modify only this file:" in str(item) for item in test_constraints):
            test_constraints.extend([f"- Modify only this file: {target_file}", "- Do not touch any other files."])
        if patch_plan.get("failing_test_nodeid"):
            test_constraints.extend(
                [
                    "- Modify only the failing test function.",
                    "- Do not rewrite the test file.",
                    "- Do not delete unrelated tests.",
                    "- Prefer updating the assertion expected value if implementation behavior is clearly shown by pytest.",
                    "- Use a valid unified diff with real hunk line numbers.",
                    "- Do not use placeholder hunk headers.",
                ]
            )
    elif task_type == "implementation_with_tests":
        test_constraints = [
            "Implementation-with-tests guidance:",
            "- Create or modify only the planned files.",
            "- Do not rewrite unrelated tests.",
            "- Prefer small diffs.",
            "- If creating a new module, include the module file and its tests.",
            "- Do not place helper tests in tests/test_cli.py unless explicitly requested.",
            "- Ensure unified diff hunk line counts match hunk headers.",
        ]
        allowed_targets = patch_plan.get("allowed_targets", [])
        if isinstance(allowed_targets, list) and allowed_targets:
            test_constraints.append(f"- Allowed targets: {', '.join(str(item) for item in allowed_targets)}")
    if _is_docs_task(task, patch_plan):
        docs_constraints = [
            "Documentation-task guidance:",
            "- Return ONLY a valid unified diff.",
            "- Target README.md.",
            "- Do not output explanation.",
            "- Do not modify source or tests unless explicitly requested.",
            "- Ensure the diff uses unified git format.",
            "- Use headers:",
            "  diff --git a/README.md b/README.md",
            "  --- a/README.md",
            "  +++ b/README.md",
            "- If README.md does not exist, use:",
            "  --- /dev/null",
            "  +++ b/README.md",
        ]
        test_constraints.extend(docs_constraints)
        if not any("Return ONLY a valid unified diff" in item for item in regen_constraints):
            regen_constraints.append("- Return ONLY a valid unified diff.")
        if not any("Modify README.md" in item for item in regen_constraints):
            regen_constraints.append("- Modify README.md.")
        if not any("Do not output explanation" in item for item in regen_constraints):
            regen_constraints.append("- Do not output explanation.")
    allowed_targets = patch_plan.get("allowed_targets", [])
    if isinstance(allowed_targets, list) and allowed_targets:
        test_constraints.extend(
            [
                "Allowed-target guidance:",
                f"- Modify only these files: {', '.join(str(item) for item in allowed_targets)}",
                "- Do not modify files outside allowed targets.",
            ]
        )
    prompt_context: dict[str, Any] = context
    if task_type == "test_generation":
        prompt_context = _shape_test_generation_context(task=task, context=context, patch_plan=patch_plan)
    sll_lines = ""
    if isinstance(sll_guidance, dict) and sll_guidance:
        strategy = str(sll_guidance.get("strategy", "unknown") or "unknown")
        constraints = sll_guidance.get("constraints", [])
        notes = str(sll_guidance.get("notes", "") or "")
        rendered_constraints = []
        if isinstance(constraints, list):
            rendered_constraints = [f"  - {str(item)}" for item in constraints if str(item).strip()]
        sll_lines = (
            "SLL Fix Guidance:\n"
            f"- Strategy: {strategy}\n"
            + ("- Constraints:\n" + "\n".join(rendered_constraints) + "\n" if rendered_constraints else "")
            + (f"- Notes:\n  {notes}\n" if notes else "")
        )
    repo_map_block = ""
    repo_map_rendered = _repo_map_text(prompt_context)
    if repo_map_rendered:
        repo_map_block = (
            "Repository map guidance:\n"
            "- Use the repository map to avoid inventing module names, CLI commands, files, functions, or unsupported options.\n"
            "- Prefer exact symbols and command patterns already present in the repo.\n"
            "- If the repository map conflicts with the task wording, follow the repository map unless the user explicitly requests a change.\n"
            f"{repo_map_rendered}\n"
        )
    snippet_block = ""
    snippets_text = _relevant_snippets_text(prompt_context)
    if snippets_text:
        snippet_block = (
            "Snippet grounding guidance:\n"
            "- Prefer exact behaviors/output observed in provided excerpts.\n"
            "- Do not invent commands/options/modules not present in snippets.\n"
            f"{snippets_text}\n"
        )
    return (
        "You generate a unified git diff only.\n"
        "- Produce valid diff\n"
        "Do not output markdown fences or explanations.\n"
        "If unsure, output an empty string.\n\n"
        f"{render_safety_constraints_for_prompt(task)}\n"
        f"Task: {task}\n"
        f"Failures: {failures}\n"
        f"Context: {prompt_context}\n"
        f"Patch plan: {patch_plan}\n"
        f"Aegis execution guidance: {aegis_execution}\n"
        + repo_map_block
        + snippet_block
        + ("\n".join(test_constraints) + "\n" if test_constraints else "")
        + ("Regeneration constraints:\n" + "\n".join(regen_constraints) + "\n" if regen_constraints else "")
        + sll_lines
    )


def build_structured_edit_prompt(
    *,
    task: str,
    failures: dict[str, Any],
    context: dict[str, Any],
    patch_plan: dict[str, Any],
    aegis_execution: dict[str, Any],
    operation: str | None = None,
) -> str:
    if str(operation or "").strip().lower() == "append":
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
    allowed_targets = patch_plan.get("allowed_targets", [])
    allowed_text = ""
    if isinstance(allowed_targets, list) and allowed_targets:
        allowed_text = f"Allowed paths only: {', '.join(str(item) for item in allowed_targets)}\n"
    repo_map_rendered = _repo_map_text(context)
    relevant_snippets = _relevant_snippets_text(context)
    return (
        "Return only JSON. No markdown. No explanations.\n"
        "Schema:\n"
        "{\n"
        '  "changes": [\n'
        "    {\n"
        '      "path": "src/main.py",\n'
        '      "mode": "replace",\n'
        '      "content": "full file content"\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "Rules:\n"
        "- full replacement content per file\n"
        "- mode must be replace or create\n"
        "- do not include delete or rename\n"
        "- do not include .aegis, .git, caches, venv paths\n"
        "- prefer modifying existing src/main.py and tests/test_cli.py for simple feature work\n"
        "- use the repository map to avoid inventing module names, CLI commands, files, functions, or unsupported options\n"
        "- prefer exact symbols and command patterns already present in the repo\n"
        "- if the repository map conflicts with the task wording, follow the repository map unless the user explicitly requests a change\n"
        f"{render_safety_constraints_for_prompt(task)}"
        f"{allowed_text}"
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
        + f"Patch plan: {patch_plan}\n"
        + f"Aegis execution guidance: {aegis_execution}\n"
    )


def is_plausible_diff(text: str) -> bool:
    value = text.strip()
    if not value:
        return False
    if "```" in value:
        return False
    markers = ("diff --git", "--- ", "+++ ", "@@")
    return any(marker in value for marker in markers)
