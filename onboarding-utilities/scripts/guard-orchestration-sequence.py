#!/usr/bin/env python3
"""Orchestration Sequence Guard — VS Code Copilot PreToolUse Hook.

Blocks Terraform file generation or Terraform CLI execution when
outputs/<FEATURE_ID>/resource_cost_report.md is missing or not approved.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

TERMINAL_TOOLS = {"run_in_terminal", "send_to_terminal"}
FILE_TOOLS = {"create_file", "apply_patch"}


def _block(reason: str) -> None:
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    print(json.dumps(output), flush=True)
    print(reason, file=sys.stderr)
    sys.exit(2)


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _find_active_feature(root: Path) -> str:
    outputs_dir = root / "outputs"
    if not outputs_dir.exists():
        return ""

    latest_feature = ""
    latest_mtime = -1.0
    for feature_dir in outputs_dir.iterdir():
        if not feature_dir.is_dir():
            continue
        checkpoint = feature_dir / "checkpoint.md"
        if not checkpoint.exists():
            continue
        text = checkpoint.read_text(encoding="utf-8", errors="ignore")
        if "status: in_progress" not in text:
            continue
        mtime = checkpoint.stat().st_mtime
        if mtime > latest_mtime:
            latest_mtime = mtime
            latest_feature = feature_dir.name
    return latest_feature


def _resource_cost_approved(root: Path, feature_id: str) -> bool:
    if not feature_id:
        return True
    report = root / "outputs" / feature_id / "resource_cost_report.md"
    if not report.exists():
        return False
    text = report.read_text(encoding="utf-8", errors="ignore").lower()
    has_status = "status: approved" in text
    has_approval = "approval: approved" in text or "decision: approved" in text
    return has_status and has_approval


def _targets_terraform_files(tool_name: str, tool_input: dict) -> bool:
    if tool_name == "create_file":
        fp = str(tool_input.get("filePath", "")).replace("\\", "/").lower()
        return "/infra/terraform/" in fp or fp.endswith(".tf")

    if tool_name == "apply_patch":
        patch = str(tool_input.get("input", "")).replace("\\", "/").lower()
        return (
            "/infra/terraform/" in patch
            or ".tf\n" in patch
            or ".tf\r\n" in patch
            or re.search(r"\*\*\* (add|update|delete) file: .*\.tf", patch) is not None
        )

    return False


def _runs_terraform_command(tool_name: str, tool_input: dict) -> bool:
    if tool_name not in TERMINAL_TOOLS:
        return False
    command = str(tool_input.get("command", "")).lower()
    if not command:
        return False
    return bool(re.search(r"\b(terraform|tofu)\s+(init|validate|plan|apply|destroy|fmt)\b", command))


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError, ValueError):
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    if tool_name not in FILE_TOOLS and tool_name not in TERMINAL_TOOLS:
        sys.exit(0)

    tool_input = data.get("tool_input", {})
    checks_needed = _targets_terraform_files(tool_name, tool_input) or _runs_terraform_command(tool_name, tool_input)
    if not checks_needed:
        sys.exit(0)

    root = _workspace_root()
    feature_id = _find_active_feature(root)

    if not _resource_cost_approved(root, feature_id):
        _block(
            "BLOCKED by Orchestration Sequence Guard\n"
            "Reason: resource_cost_report.md is missing or not approved.\n"
            "Required before Terraform generation or Terraform CLI usage.\n"
            "Fix: set in outputs/<FEATURE_ID>/resource_cost_report.md:\n"
            "  status: approved\n"
            "  approval: approved (or decision: approved)"
        )

    sys.exit(0)


if __name__ == "__main__":
    main()
