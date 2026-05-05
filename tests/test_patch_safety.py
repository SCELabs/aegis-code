from __future__ import annotations

import json
from pathlib import Path

from aegis_code.cli import main as cli_main
from aegis_code.models import AegisDecision
from aegis_code.report import render_markdown_report
from aegis_code.runtime import TaskOptions, build_run_payload
from aegis_code.safety.patch_review import scan_diff
from tests.helpers import command_result_from_output, pytest_output_pass


class _Client:
    def step_scope(self, **_: object) -> AegisDecision:
        return AegisDecision(
            model_tier="mid",
            context_mode="focused",
            max_retries=0,
            allow_escalation=False,
            execution={},
        )


def test_scan_clean_diff_pass() -> None:
    report = scan_diff(
        "diff --git a/src/main.py b/src/main.py\n--- a/src/main.py\n+++ b/src/main.py\n@@ -1 +1 @@\n-x=1\n+x=2\n"
    )
    assert report.highest_severity == "pass"
    assert report.issues == []


def test_scan_path_home_warn() -> None:
    report = scan_diff(
        "diff --git a/src/main.py b/src/main.py\n--- a/src/main.py\n+++ b/src/main.py\n@@ -1 +1,2 @@\n x=1\n+TODO_FILE = Path.home() / '.todo_cli.json'\n"
    )
    assert report.highest_severity == "warn"
    assert any(item.type == "writes_outside_project" for item in report.issues)


def test_scan_subprocess_warn() -> None:
    report = scan_diff("diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1,2 @@\n x=1\n+subprocess.run(['echo','x'])\n")
    assert any(item.type == "process_execution" for item in report.issues)


def test_scan_eval_warn() -> None:
    report = scan_diff("diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1,2 @@\n x=1\n+value = eval(expr)\n")
    assert any(item.type == "dynamic_code_execution" for item in report.issues)


def test_scan_network_warn() -> None:
    report = scan_diff("diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1,2 @@\n x=1\n+requests.get('https://x')\n")
    assert any(item.type == "network_access" for item in report.issues)


def test_scan_secret_env_warn() -> None:
    report = scan_diff("diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1,2 @@\n x=1\n+token = os.environ.get('API_KEY')\n")
    assert any(item.type == "secret_or_env_access" for item in report.issues)


def test_scan_multiple_issues_aggregate() -> None:
    report = scan_diff(
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1,4 @@\n x=1\n+Path.home()\n+subprocess.run(['x'])\n+eval('1+1')\n"
    )
    assert len(report.issues) >= 3
    assert report.highest_severity == "warn"


def test_scan_removed_lines_do_not_warn() -> None:
    report = scan_diff(
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1,2 +1 @@\n-Path.home()\n x=1\n"
    )
    assert report.highest_severity == "pass"


def test_runtime_payload_includes_patch_safety_warn(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "src" / "main.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr(
        "aegis_code.runtime.generate_structured_edits",
        lambda **_: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "text": '{"changes":[{"path":"src/main.py","mode":"replace","content":"from pathlib import Path\\nTODO_FILE = Path.home() / \\".todo_cli.json\\"\\n"}]}',
            "error": None,
        },
    )
    monkeypatch.setattr("aegis_code.runtime.generate_patch_diff", lambda **_: (_ for _ in ()).throw(AssertionError("fallback should not run")))
    payload = build_run_payload(options=TaskOptions(task="implement todo CLI commands", propose_patch=True), cwd=tmp_path, client=_Client())
    assert payload["patch_diff"]["status"] == "generated"
    assert payload["patch_safety"]["highest_severity"] == "warn"
    report = render_markdown_report(payload)
    assert "## Patch Safety Review" in report
    assert "Safety: `WARN`" in report


def test_patch_command_generated_path_home_diff_has_safety_warn(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "src" / "main.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr(
        "aegis_code.runtime.generate_structured_edits",
        lambda **_: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "text": '{"changes":[{"path":"src/main.py","mode":"replace","content":"from pathlib import Path\\nTODO_FILE = Path.home() / \\".todo_cli.json\\"\\n"}]}',
            "error": None,
        },
    )
    monkeypatch.setattr("aegis_code.runtime.generate_patch_diff", lambda **_: (_ for _ in ()).throw(AssertionError("fallback should not run")))
    payload = build_run_payload(
        options=TaskOptions(
            task="store todos in the user's home directory using Path.home()",
            propose_patch=True,
            command="patch",
            scope_contract={
                "source": "cli_explicit",
                "allowed_targets": ["src/main.py"],
                "max_files": 1,
                "allow_new_files": False,
                "allowed_operations": ["replace"],
                "missing_targets": [],
                "block_reason": None,
            },
        ),
        cwd=tmp_path,
        client=_Client(),
    )
    assert payload["patch_diff"]["status"] == "generated"
    assert payload["patch_safety"]["highest_severity"] == "warn"


def test_apply_check_prints_safety_warn(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    diff_path = runs / "latest.diff"
    diff_path.write_text(
        "diff --git a/src/main.py b/src/main.py\n--- a/src/main.py\n+++ b/src/main.py\n@@ -1 +1,2 @@\n x=1\n+TODO_FILE = Path.home() / '.todo_cli.json'\n",
        encoding="utf-8",
    )
    latest = {
        "patch_diff": {"path": str(diff_path)},
        "patch_safety": {
            "highest_severity": "warn",
            "issues": [{"file": "src/main.py", "message": "Uses Path.home(), which may write outside the project directory."}],
        },
    }
    (runs / "latest.json").write_text(json.dumps(latest), encoding="utf-8")
    exit_code = cli_main(["apply", "--check", str(diff_path)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Safety: WARN" in out
    assert "src/main.py: Uses Path.home()" in out


def test_apply_check_prints_safety_pass(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    diff_path = runs / "latest.diff"
    diff_path.write_text(
        "diff --git a/src/main.py b/src/main.py\n--- a/src/main.py\n+++ b/src/main.py\n@@ -1 +1 @@\n-x=1\n+x=2\n",
        encoding="utf-8",
    )
    latest = {
        "patch_diff": {"path": str(diff_path)},
        "patch_safety": {"highest_severity": "pass", "issues": []},
    }
    (runs / "latest.json").write_text(json.dumps(latest), encoding="utf-8")
    exit_code = cli_main(["apply", "--check", str(diff_path)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Safety: PASS" in out
