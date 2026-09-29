#!/usr/bin/env python3
"""RBI Destructive Command Guard — VS Code Copilot PreToolUse Hook

Intercepts every tool call and blocks terminal commands that could cause
irreversible damage to the host machine.

Adapted from Claude Code hook for VS Code GitHub Copilot.

VS Code Copilot tool name: run_in_terminal (instead of Claude's "Bash")

Exit codes (VS Code Copilot hook contract):
  0 — safe, allow tool to proceed
  2 — blocked; stderr is fed back to the model as context
"""

import json
import re
import sys

# VS Code Copilot tool names that execute terminal commands
TERMINAL_TOOLS = {"run_in_terminal", "send_to_terminal"}

# Critical paths that should never be recursively removed
CRITICAL_PATHS = (
    "/",
    "~",
    "$HOME",
    "${HOME}",
    "/etc",
    "/usr",
    "/bin",
    "/sbin",
    "/lib",
    "/lib64",
    "/boot",
    "/var",
    "/private",
    "/opt",
    "/System",
    "/Library",
    "/Applications",
    "/Volumes",
    "/dev",
    "/proc",
    "/sys",
)

_SHELL_SEP = re.compile(r"[;&]|\|\|?|\n")


def _has_recursive_flag(args: str) -> bool:
    return bool(re.search(r"(?:^|\s)-[a-zA-Z]*[rR]|--recursive", args))


def check_destructive_rm(command: str) -> tuple[bool, str]:
    for part in _SHELL_SEP.split(command):
        tokens = part.strip().split()
        if not tokens:
            continue
        if tokens[0] in ("sudo", "doas") and len(tokens) > 1:
            tokens = tokens[1:]
        if not tokens or tokens[0] != "rm":
            continue
        args = " ".join(tokens[1:])
        if not _has_recursive_flag(args):
            continue
        for path in CRITICAL_PATHS:
            pattern = rf"(?:^|\s){re.escape(path)}(?:\s|/|\*|$)"
            if re.search(pattern, args):
                return True, f"recursive rm targeting critical path '{path}'"
    return False, ""


# Static patterns that are always dangerous
_STATIC_RULES: list[tuple[str, str]] = [
    (r"\bmkfs\b", "filesystem format command (mkfs)"),
    (r"\bdd\b.+of\s*=\s*/dev/(disk|sd[a-z]+|nvme|rd/)", "dd writing to a block device"),
    (r"\bdiskutil\s+(eraseDisk|eraseVolume|zeroDisk|secureErase|reformat)\b", "diskutil destructive operation"),
    (r"\bchmod\b.+-R.+777\s+/(?:\s|$)", "chmod -R 777 on filesystem root"),
    (r"\bchmod\b.+777\s+(~|\$\{?HOME\}?)(?:\s|$)", "chmod 777 on home directory"),
    (r":\s*\(\s*\)\s*\{[^}]*:\s*\|.*:\s*&", "fork bomb pattern"),
    (r"(?:^|[;&|])\s*>\s*/etc/(passwd|shadow|sudoers|hosts|fstab)\b", "truncation of critical system file via shell redirection"),
    (r"\bshred\b.+/dev/(disk|sd[a-z]+|nvme)", "shred targeting a block device"),
    (r"\bwipefs\b.+/dev/", "wipefs on a block device"),
    (r"\bterraform\s+(apply|destroy)\b", "destructive terraform command (plan-only allowed)"),
    (r"\btofu\s+(apply|destroy)\b", "destructive tofu command (plan-only allowed)"),
    (r"\bpulumi\s+(up|destroy)\b", "destructive pulumi command (preview-only allowed)"),
    (r"\bcdk\s+(deploy|destroy)\b", "destructive cdk command (diff-only allowed)"),
    (r"\baws\s+cloudformation\s+delete-stack\b", "destructive cloudformation stack deletion"),
    (r"\baws\s+s3\s+rb\b", "destructive S3 bucket deletion"),
    (r"\baz\s+deployment\s+.*create\b", "destructive azure deployment create"),
    (r"\baz\s+group\s+delete\b", "destructive azure resource group deletion"),
    (r"\bgcloud\s+deployment-manager\s+.*delete\b", "destructive GCP deployment manager delete"),
    (r"\bkubectl\s+delete\b", "destructive kubectl delete"),
    (r"\bhelm\s+uninstall\b", "destructive helm uninstall"),
]


def _block(reason: str, command: str) -> None:
    """Output JSON to stderr for VS Code Copilot and exit with code 2."""
    error_msg = (
        f"BLOCKED by RBI Destructive Command Guard\n"
        f"Reason  : {reason}\n"
        f"Command : {command!r}\n\n"
        f"This command could cause irreversible system damage and has been prevented.\n"
        f"If you genuinely need to run this, execute it manually in your own terminal."
    )
    # Output structured JSON for VS Code Copilot PreToolUse
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": error_msg,
        }
    }
    print(json.dumps(output), flush=True)
    # Also print to stderr for the model context
    print(error_msg, file=sys.stderr)
    sys.exit(2)


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError, ValueError):
        sys.exit(0)

    tool_name = data.get("tool_name", "")

    # Only act on terminal execution tools
    if tool_name not in TERMINAL_TOOLS:
        sys.exit(0)

    tool_input = data.get("tool_input", {})
    command: str = tool_input.get("command", "")
    if not command:
        sys.exit(0)

    blocked, reason = check_destructive_rm(command)
    if blocked:
        _block(reason, command)

    for pattern, description in _STATIC_RULES:
        if re.search(pattern, command, re.IGNORECASE | re.DOTALL):
            _block(description, command)

    sys.exit(0)


if __name__ == "__main__":
    main()
