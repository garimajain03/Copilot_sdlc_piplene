#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path


def main() -> None:
    raw = sys.stdin.read().strip()
    if not raw:
        sys.exit(0)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    state_dir = Path("observability") / ".hook-state"
    state_dir.mkdir(parents=True, exist_ok=True)
    out = state_dir / "observability.last.json"

    try:
        out.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
    except OSError:
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
