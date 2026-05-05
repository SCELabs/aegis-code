from __future__ import annotations

from aegis_code.providers.base import build_diff_prompt
from aegis_code.safety.patch_review import render_safety_constraints_for_prompt, scan_diff


def test_constraints_without_risky_intent_are_strict() -> None:
    text = render_safety_constraints_for_prompt("implement todo cli commands")
    assert "Do not write outside the project root unless explicitly requested." in text
    assert "Avoid Path.home() and absolute system paths unless required by the task." in text


def test_constraints_with_home_intent_relax_filesystem_rule() -> None:
    text = render_safety_constraints_for_prompt("store todos in the user's home directory using Path.home()")
    assert "The user has explicitly requested behavior that may write outside the project directory." in text
    assert "Do not write outside the project root unless explicitly requested." not in text
    assert "Avoid Path.home() and absolute system paths unless required by the task." not in text


def test_constraints_with_subprocess_intent_relax_process_rule() -> None:
    text = render_safety_constraints_for_prompt("run shell command via subprocess to check status")
    assert "Subprocess/shell behavior is explicitly requested" in text
    assert "Avoid shell execution and subprocess invocation unless required by the task." not in text


def test_constraints_without_subprocess_intent_keep_process_rule() -> None:
    text = render_safety_constraints_for_prompt("update parser behavior")
    assert "Avoid shell execution and subprocess invocation unless required by the task." in text


def test_scan_diff_flags_path_home_even_if_intent_would_allow() -> None:
    report = scan_diff(
        "diff --git a/src/main.py b/src/main.py\n--- a/src/main.py\n+++ b/src/main.py\n@@ -1 +1,2 @@\n x=1\n+TODO_FILE = Path.home() / '.todo_cli.json'\n"
    )
    assert report.highest_severity == "warn"
    assert any(issue.type == "writes_outside_project" for issue in report.issues)


def test_prompt_includes_intent_aware_safety_block() -> None:
    prompt = build_diff_prompt(
        task="store todos in the user's home directory using Path.home()",
        failures={},
        context={"files": []},
        patch_plan={"task_type": "general", "proposed_changes": []},
        aegis_execution={},
    )
    assert "The user has explicitly requested behavior that may write outside the project directory." in prompt
