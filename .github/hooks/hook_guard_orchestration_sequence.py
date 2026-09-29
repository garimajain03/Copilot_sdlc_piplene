#!/usr/bin/env python3
"""Guard Terraform work until resource cost report is approved.

This hook blocks Terraform file generation and Terraform CLI use when
outputs/<FEATURE_ID>/resource_cost_report.md is missing or not approved.
"""

import json
import re
import sys
from pathlib import Path

FILE_TOOLS = {"create_file", "apply_patch"}
TERMINAL_TOOLS = {"run_in_terminal", "send_to_terminal"}


def _get_field(payload: dict, *keys, default=""):
    for key in keys:
        if key in payload:
            return payload.get(key)
    return default


def _block(reason: str) -> None:
    print(json.dumps({"error": reason}))
    sys.exit(2)


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _active_feature(root: Path) -> str:
    outputs = root / "outputs"
    if not outputs.exists():
        return ""

    latest = ""
    latest_mtime = -1.0
    for path in outputs.iterdir():
        if not path.is_dir():
            continue
        checkpoint = path / "checkpoint.md"
        if not checkpoint.exists():
            continue
        text = checkpoint.read_text(encoding="utf-8", errors="ignore")
        if "status: in_progress" not in text:
            continue
        mtime = checkpoint.stat().st_mtime
        if mtime > latest_mtime:
            latest_mtime = mtime
            latest = path.name
    return latest


def _is_approved(root: Path, feature_id: str) -> bool:
    if not feature_id:
        return True
    report = root / "outputs" / feature_id / "resource_cost_report.md"
    if not report.exists():
        return False
    text = report.read_text(encoding="utf-8", errors="ignore").lower()
    return "status: approved" in text and (
        "approval: approved" in text or "decision: approved" in text
    )


def _targets_terraform(tool_name: str, tool_input: dict) -> bool:
    if tool_name == "create_file":
        file_path = str(_get_field(tool_input, "filePath", "file_path", default="")).replace("\\", "/").lower()
        return "/infra/terraform/" in file_path or file_path.endswith(".tf")

    if tool_name == "apply_patch":
        patch = str(_get_field(tool_input, "input", default="")).replace("\\", "/").lower()
        if "/infra/terraform/" in patch:
            return True
        if ".tf\n" in patch or ".tf\r\n" in patch:
            return True
        return re.search(r"\*\*\* (add|update|delete) file: .*\.tf", patch) is not None

    command = str(_get_field(tool_input, "command", default="")).lower()
    return bool(re.search(r"\b(terraform|tofu)\s+(init|validate|plan|apply|destroy|fmt)\b", command))


def main() -> None:
    raw = sys.stdin.read().strip()
    if not raw:
        sys.exit(0)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    tool_name = str(_get_field(payload, "toolName", "tool_name", default=""))
    if tool_name not in FILE_TOOLS and tool_name not in TERMINAL_TOOLS:
        sys.exit(0)

    tool_input = _get_field(payload, "toolInput", "tool_input", default={})
    if not isinstance(tool_input, dict):
        sys.exit(0)

    if not _targets_terraform(tool_name, tool_input):
        sys.exit(0)

    root = _workspace_root()
    feature_id = _active_feature(root)
    if _is_approved(root, feature_id):
        sys.exit(0)

    _block(
        "Blocked by guard-orchestration-sequence: resource_cost_report.md is missing or not approved. "
        "Set status: approved and approval: approved (or decision: approved) before Terraform generation/commands."
    )


if __name__ == "__main__":
    main()
