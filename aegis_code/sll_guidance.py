from __future__ import annotations

from typing import Any


def build_sll_fix_guidance(sll_data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(sll_data, dict) or not bool(sll_data.get("available", False)):
        return {"strategy": "unknown", "constraints": [], "notes": "No structural guidance available."}

    regime = str(sll_data.get("regime", "unknown") or "unknown").strip().lower()
    collapse = sll_data.get("collapse_risk")
    fragmentation = sll_data.get("fragmentation_risk")
    drift = sll_data.get("drift_risk")

    collapse_v = float(collapse) if isinstance(collapse, (int, float)) else 0.0
    fragmentation_v = float(fragmentation) if isinstance(fragmentation, (int, float)) else 0.0
    drift_v = float(drift) if isinstance(drift, (int, float)) else 0.0

    if regime == "fragmentation" and (collapse_v > 0.7 or fragmentation_v > 0.7):
        return {
            "strategy": "narrow_scope",
            "constraints": [
                "Modify fewer files",
                "Focus only on failing test target",
                "Avoid broad refactors",
                "Prefer minimal diffs",
            ],
            "notes": "Output shows incoherent structure; reduce scope and complexity.",
        }

    if collapse_v > 0.7:
        return {
            "strategy": "change_approach",
            "constraints": [
                "Do not repeat previous fix pattern",
                "Avoid identical assertions or logic",
                "Try alternative fix approach",
            ],
            "notes": "Output shows repetition or degeneracy; avoid repeating same solution.",
        }

    if drift_v > 0.4:
        return {
            "strategy": "re_anchor",
            "constraints": [
                "Re-focus on failing test",
                "Use explicit file targets",
                "Avoid unrelated files",
            ],
            "notes": "Output drifting away from target; re-anchor to failure context.",
        }

    if regime == "boundary":
        return {
            "strategy": "proceed",
            "constraints": [
                "Prefer small diffs",
                "Stay within allowed targets",
            ],
            "notes": "Structure stable; proceed with bounded fix.",
        }

    return {"strategy": "unknown", "constraints": [], "notes": "No structural guidance available."}
