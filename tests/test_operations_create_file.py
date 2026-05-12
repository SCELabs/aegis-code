from __future__ import annotations

from pathlib import Path

from aegis_code.operations import create_file as create_file_ops


def test_create_file_builds_new_file_diff() -> None:
    diff = create_file_ops._build_create_file_diff(
        target_path="src/helpers.js",
        new_content="export function hasNotes(notes) { return notes.length > 0; }\n",
    )
    assert "diff --git a/src/helpers.js b/src/helpers.js" in diff
    assert "--- /dev/null" in diff
    assert "+++ b/src/helpers.js" in diff
    assert "+export function hasNotes(notes) { return notes.length > 0; }" in diff


def test_create_file_rejects_existing_target(tmp_path: Path) -> None:
    target = tmp_path / "src" / "helpers.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("export const x = 1;\n", encoding="utf-8")
    assert create_file_ops._target_exists(cwd=tmp_path, target_path="src/helpers.js") is True


def test_create_file_rejects_invalid_provider_json() -> None:
    ok, content, err = create_file_ops._parse_create_file_provider_response("not-json")
    assert ok is False
    assert content is None
    assert err == "create_file_output_invalid"
