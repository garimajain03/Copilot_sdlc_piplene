#!/usr/bin/env python3
"""RBI .env File Guard — VS Code Copilot PreToolUse Hook

Prevents the agent from reading, writing, editing, or executing commands
that access .env files. These files contain secrets and should never be
read by the agent.

Adapted from Claude Code hook for VS Code GitHub Copilot.

VS Code Copilot tool name mapping:
  Claude Code  →  VS Code Copilot
  Read         →  read_file
  Edit         →  replace_string_in_file, multi_replace_string_in_file
  Write        →  create_file
  Bash         →  run_in_terminal, send_to_terminal
  Glob         →  file_search

Property name mapping (snake_case → camelCase):
  file_path    →  filePath
  pattern      →  query

Exit codes (VS Code Copilot hook contract):
  0 — allow
  2 — block (stderr fed back to model as context)
"""

from __future__ import annotations

import json
import os
import re
import sys


# ---------------------------------------------------------------------------
# VS Code Copilot tool name groups
# ---------------------------------------------------------------------------

FILE_READ_TOOLS = {"read_file"}
FILE_EDIT_TOOLS = {"replace_string_in_file", "multi_replace_string_in_file"}
FILE_WRITE_TOOLS = {"create_file"}
TERMINAL_TOOLS = {"run_in_terminal", "send_to_terminal"}
SEARCH_TOOLS = {"file_search"}

ALL_FILE_TOOLS = FILE_READ_TOOLS | FILE_EDIT_TOOLS | FILE_WRITE_TOOLS


# ---------------------------------------------------------------------------
# .env filename detection
# ---------------------------------------------------------------------------

_ENV_FILE_RE = re.compile(r"(?:^|/)\.env(?:\.[a-zA-Z0-9_.-]+)?$")

_ENV_IN_CMD_RE = re.compile(
    r"(?:^|\s|=|'|\"|<|>|\||\(|`)"
    r"((?:[^\s'\"<>|&;()`]*/)?"
    r"\.env(?:\.[a-zA-Z0-9_.-]+)?)"
    r"(?:\s|$|'|\"|<|>|\|;|&|\)|`)",
)

_READ_COMMANDS = (
    r"\bcat\b", r"\bless\b", r"\bmore\b", r"\bhead\b", r"\btail\b",
    r"\bbat\b", r"\bsed\b", r"\bawk\b", r"\bperl\b",
    r"\bsource\b", r"\.\s",
    r"\bgrep\b", r"\begrep\b", r"\bfgrep\b", r"\brg\b", r"\bag\b",
    r"\bsort\b", r"\buniq\b", r"\bwc\b", r"\bcut\b",
    r"\bcp\b", r"\bmv\b", r"\brsync\b",
    r"\bvi\b", r"\bvim\b", r"\bnvim\b", r"\bnano\b",
    r"\bpython3?\b", r"\bnode\b",
    r"\bexport\b", r"\benv\b", r"\bxargs\b", r"\btee\b",
    r"\bdiff\b", r"\bcmp\b",
    r"\bcurl\b", r"\bscp\b",
    r"\bdocker\b", r"\bpodman\b", r"\bkubectl\b",
)

_REDIRECT_PATTERNS = (
    r"<\s*(?:[^\s]*\/)?\.env",
    r"\.env\s*\|",
    r"\|\s*.*\.env",
    r"\$\(.*\.env.*\)",
    r"`[^`]*\.env[^`]*`",
)


def _is_env_filepath(path: str) -> bool:
    if not path:
        return False
    basename = os.path.basename(path.rstrip("/"))
    if re.search(r"\.env\.(?:example|sample|template)$", basename, re.IGNORECASE):
        return False
    return bool(_ENV_FILE_RE.search("/" + basename))


def _is_env_filepath_in_args(args: str) -> bool:
    for token in args.split():
        token = token.strip("'\"")
        if _is_env_filepath(token):
            return True
    return False


def _block(reason: str, tool: str, detail: str = "") -> None:
    msg = (
        f"BLOCKED by RBI .env File Guard\n"
        f"Reason : {reason}\n"
        f"Tool   : {tool}\n"
    )
    if detail:
        msg += f"Detail : {detail!r}\n"
    msg += (
        "\n"
        ".env files contain secrets and must not be accessed by the agent.\n"
        "If you need environment variable values, ask the user to provide\n"
        "specific (non-secret) values, or read .env.example instead."
    )
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": msg,
        }
    }
    print(json.dumps(output), flush=True)
    print(msg, file=sys.stderr)
    sys.exit(2)


# ---------------------------------------------------------------------------
# Tool-specific checks
# ---------------------------------------------------------------------------

def check_file_tool(tool_name: str, tool_input: dict) -> None:
    """Check read_file, replace_string_in_file, create_file for .env access."""
    # VS Code Copilot uses camelCase: filePath
    file_path = tool_input.get("filePath", "") or tool_input.get("file_path", "")
    if _is_env_filepath(file_path):
        _block(f"direct {tool_name} of .env file", tool_name, file_path)


def check_multi_replace(tool_input: dict) -> None:
    """Check multi_replace_string_in_file for .env access in any replacement."""
    replacements = tool_input.get("replacements", [])
    if isinstance(replacements, list):
        for r in replacements:
            if isinstance(r, dict):
                fp = r.get("filePath", "") or r.get("file_path", "")
                if _is_env_filepath(fp):
                    _block("multi_replace targeting .env file", "multi_replace_string_in_file", fp)


def check_terminal(tool_input: dict) -> None:
    """Check terminal commands for .env file access."""
    command: str = tool_input.get("command", "")
    if not command:
        return

    env_match = _ENV_IN_CMD_RE.search(command)
    if not env_match:
        if not re.search(r"\.env(?:\.[a-zA-Z0-9_.-]+)?(?:\s|$|'|\"|;|&|\|)", command):
            return

    stripped = command.strip()
    if stripped.startswith("#"):
        return

    # Allow git commit/log/tag messages
    if re.match(r"^\s*git\s+(?:commit|log|tag|show|shortlog|whatchanged)\b", stripped):
        return

    # Check git commands targeting .env files directly
    git_match = re.match(r"^\s*git\s+(add|rm|checkout|restore|stash)\s+(.+)", stripped)
    if git_match:
        git_args = git_match.group(2)
        if _is_env_filepath_in_args(git_args):
            _block("git command targeting .env file", "run_in_terminal", command)
        return

    # Command substitution
    if re.search(r"\$\([^)]*\.env(?:\.[a-zA-Z0-9_.-]+)?[^)]*\)", command):
        _block("command substitution accessing .env file", "run_in_terminal", command)
    if re.search(r"`[^`]*\.env(?:\.[a-zA-Z0-9_.-]+)?[^`]*`", command):
        _block("backtick substitution accessing .env file", "run_in_terminal", command)

    # Shell redirections/pipes
    for pattern in _REDIRECT_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            _block("shell redirect/pipe accessing .env file", "run_in_terminal", command)

    # Allow echo/printf that just mentions .env in a string
    if re.match(r"^\s*(?:echo|printf)\s+['\"].*\.env.*['\"]\s*$", command):
        return

    # Allow ls / stat / test (checking existence)
    if re.match(r"^\s*(?:ls|stat|test)\b", stripped):
        return

    # Allow .env.example references
    if re.search(r"\.env\.(?:example|sample|template)\b", command, re.IGNORECASE) and \
       not re.search(r"\.env(?!\.[a-zA-Z])", command):
        return

    # Check commands that read file contents
    for cmd_pattern in _READ_COMMANDS:
        if re.search(cmd_pattern, command, re.IGNORECASE):
            _block("command accessing .env file contents", "run_in_terminal", command)

    _block(".env file referenced in command", "run_in_terminal", command)


def check_file_search(tool_input: dict) -> None:
    """Check file_search glob patterns targeting .env files."""
    # VS Code uses 'query' for file_search
    pattern = tool_input.get("query", "") or tool_input.get("pattern", "")
    if not pattern:
        return
    if re.search(r"(?:^|\*\*/?)\.env(?:\.\*|\.[a-zA-Z]+)?$", pattern):
        _block("search pattern targeting .env files", "file_search", pattern)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError, ValueError):
        sys.exit(0)

    tool_name: str = data.get("tool_name", "")
    tool_input: dict = data.get("tool_input", {})

    if tool_name == "multi_replace_string_in_file":
        check_multi_replace(tool_input)
    elif tool_name in ALL_FILE_TOOLS:
        check_file_tool(tool_name, tool_input)
    elif tool_name in TERMINAL_TOOLS:
        check_terminal(tool_input)
    elif tool_name in SEARCH_TOOLS:
        check_file_search(tool_input)

    sys.exit(0)


if __name__ == "__main__":
    main()
