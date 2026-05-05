from __future__ import annotations

from pathlib import Path

from aegis_code.patches.apply_check import check_patch_text
from aegis_code.patches.patch_applier import validate_patch_applier_parse
from aegis_code.patches.structured_edits import parse_structured_edit_response, structured_edits_to_diff


def test_parse_valid_structured_edit_json() -> None:
    parsed = parse_structured_edit_response('{"changes":[{"path":"src/main.py","mode":"replace","content":"print(1)\\n"}]}')
    assert parsed["ok"] is True


def test_parse_invalid_json_rejected() -> None:
    parsed = parse_structured_edit_response("{not json")
    assert parsed["ok"] is False
    assert "invalid_json" in parsed["errors"]


def test_replace_existing_file_creates_valid_diff(tmp_path: Path) -> None:
    path = tmp_path / "src" / "main.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("print(1)\n", encoding="utf-8")
    result = structured_edits_to_diff(
        {"changes": [{"path": "src/main.py", "mode": "replace", "content": "print(2)\n"}]},
        cwd=tmp_path,
    )
    assert result["ok"] is True
    assert "diff --git a/src/main.py b/src/main.py" in result["diff"]


def test_create_new_file_creates_valid_diff(tmp_path: Path) -> None:
    result = structured_edits_to_diff(
        {"changes": [{"path": "src/new_file.py", "mode": "create", "content": "VALUE = 1\n"}]},
        cwd=tmp_path,
    )
    assert result["ok"] is True
    assert "--- /dev/null" in result["diff"]


def test_unsafe_paths_rejected(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    result = structured_edits_to_diff(
        {"changes": [{"path": "../evil.py", "mode": "create", "content": "x\n"}]},
        cwd=tmp_path,
    )
    assert result["ok"] is False
    assert any(str(err).startswith("invalid_path:") for err in result["errors"])


def test_allowed_targets_enforced(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    result = structured_edits_to_diff(
        {"changes": [{"path": "src/other.py", "mode": "create", "content": "x\n"}]},
        cwd=tmp_path,
        allowed_targets=["src/main.py"],
    )
    assert result["ok"] is False
    assert "invalid_path:outside_allowed_targets" in result["errors"]


def test_generated_diff_passes_check_patch_text(tmp_path: Path) -> None:
    path = tmp_path / "src" / "main.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("print(1)\n", encoding="utf-8")
    result = structured_edits_to_diff(
        {"changes": [{"path": "src/main.py", "mode": "replace", "content": "print(2)\n"}]},
        cwd=tmp_path,
    )
    assert result["ok"] is True
    checked = check_patch_text(result["diff"], cwd=tmp_path)
    assert checked.get("apply_blocked", False) is False
    parse_check = validate_patch_applier_parse(result["diff"])
    assert parse_check["ok"] is True
