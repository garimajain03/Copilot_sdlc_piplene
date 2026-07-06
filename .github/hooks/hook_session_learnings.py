#!/usr/bin/env python3
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    raw = sys.stdin.read().strip()
    if not raw:
        sys.exit(0)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    out_dir = Path(".github") / "sdlc-pipeline"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "session_learnings.log"

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool": payload.get("toolName", ""),
        "status": "recorded",
    }

    try:
        with out_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=True) + "\n")
    except OSError:
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
