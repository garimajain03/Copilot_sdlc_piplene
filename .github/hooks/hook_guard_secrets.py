#!/usr/bin/env python3
import json
import re
import sys

SECRET_PATTERNS = [
    r"ghp_[A-Za-z0-9]{30,}",
    r"AIza[0-9A-Za-z\-_]{35}",
    r"AKIA[0-9A-Z]{16}",
    r"(?i)api[_-]?key\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{16,}",
    r"(?i)secret\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{12,}",
]


def _extract_text(payload: dict) -> str:
    tool_input = payload.get("toolInput", {})
    if isinstance(tool_input, dict):
        pieces = [str(v) for v in tool_input.values()]
        return "\n".join(pieces)
    return str(tool_input)


def main() -> None:
    raw = sys.stdin.read().strip()
    if not raw:
        sys.exit(0)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    text = _extract_text(payload)
    if any(re.search(p, text) for p in SECRET_PATTERNS):
        print(json.dumps({"error": "Blocked: possible secret detected in tool input."}))
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
