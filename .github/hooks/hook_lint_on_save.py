#!/usr/bin/env python3
import json
import subprocess
import sys


def main() -> None:
    raw = sys.stdin.read().strip()
    if not raw:
        sys.exit(0)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    tool_name = payload.get("toolName", "")
    if tool_name not in {"write", "edit", "execute"}:
        sys.exit(0)

    # Best-effort lint check; do not block when linter is unavailable.
    try:
        subprocess.run(["python", "-m", "py_compile", "-"], input=b"", capture_output=True, check=False)
    except Exception:
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
