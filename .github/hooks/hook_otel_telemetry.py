#!/usr/bin/env python3
import json
import os
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

    log_dir = Path("observability") / ".hook-state"
    log_dir.mkdir(parents=True, exist_ok=True)
    line = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "toolName": payload.get("toolName", ""),
        "event": "post_tool_use",
    }

    try:
        with (log_dir / "otel_telemetry.log").open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=True) + "\n")
    except OSError:
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
