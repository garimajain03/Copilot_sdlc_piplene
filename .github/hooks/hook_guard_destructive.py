#!/usr/bin/env python3
import json
import re
import sys

BLOCK_PATTERNS = [
    r"\brm\s+-rf\s+/(\s|$)",
    r"\brm\s+-rf\s+~(\s|$)",
    r"\brm\s+-rf\s+\.git(\s|$)",
    r"\bgit\s+push\s+--force\b",
    r"\bgit\s+push\s+-f\b",
    r"\bgit\s+reset\s+--hard\b",
    r"\bDROP\s+DATABASE\b",
    r"\bDROP\s+TABLE\b",
]

ALLOW_PATTERNS = [
    r"\brm\s+-rf\s+node_modules(\s|$)",
    r"\brm\s+-rf\s+dist(\s|$)",
    r"\brm\s+-rf\s+build(\s|$)",
]


def _extract_command(payload: dict) -> str:
    tool_input = payload.get("toolInput", {})
    if isinstance(tool_input, dict):
        return str(tool_input.get("command") or tool_input.get("cmd") or "")
    return ""


def main() -> None:
    raw = sys.stdin.read().strip()
    if not raw:
        sys.exit(0)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    command = _extract_command(payload)
    if not command:
        sys.exit(0)

    if any(re.search(p, command, re.IGNORECASE) for p in ALLOW_PATTERNS):
        sys.exit(0)

    if any(re.search(p, command, re.IGNORECASE) for p in BLOCK_PATTERNS):
        print(json.dumps({"error": f"Blocked potentially destructive command: {command}"}))
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
