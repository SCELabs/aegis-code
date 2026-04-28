from __future__ import annotations

from pathlib import Path

from aegis_code.patches.diff_writer import write_latest_diff


def test_write_latest_diff_writes_expected_path(tmp_path: Path) -> None:
    diff = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-a\n+b\n"
    path = write_latest_diff(diff, cwd=tmp_path)
    assert path == tmp_path / ".aegis" / "runs" / "latest.diff"
    assert path.exists()
    assert path.read_text(encoding="utf-8") == diff

