#!/usr/bin/env python3
"""
hook-failure-report.py — summarize hook failures for orchestrator finalization.

Usage:
  python3 .github/hooks/hook-failure-report.py [feature_id]

Outputs JSON to stdout with:
  - status: healthy | degraded
  - active_failures: latest failure markers from hook-state
  - feature_failures: feature-specific artifact publish failures (if feature_id provided)
  - recent_failure_events: tail of consolidated hook failure event stream
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OBS_DIR = REPO_ROOT / ".github" / "observability"
HOOK_STATE_DIR = OBS_DIR / ".hook-state"
FAILURE_EVENTS_FILE = HOOK_STATE_DIR / "hook_failures.ndjson"

LATEST_FAILURE_MARKERS = [
    HOOK_STATE_DIR / "observability_hook_last_failure.json",
    HOOK_STATE_DIR / "otel_hook_last_failure.json",
    HOOK_STATE_DIR / "publish_artifacts_last_failure.json",
]


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        data["_path"] = str(path)
        return data
    except (OSError, json.JSONDecodeError):
        return {
            "_path": str(path),
            "message": "Failed to read marker file",
            "invalid_json": True,
        }


def _tail_ndjson(path: Path, max_lines: int = 20) -> list[dict]:
    if not path.exists():
        return []
    try:
        lines = path.read_text().splitlines()[-max_lines:]
    except OSError:
        return []

    rows: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows.append({"raw": line, "invalid_json": True})
    return rows


def _feature_failure_marker(feature_id: str) -> dict | None:
    marker = HOOK_STATE_DIR / f"artifacts_publish_failed_{feature_id}"
    return _read_json(marker)


def _tail_log(path_str: str, max_lines: int = 20) -> list[str]:
    if not path_str:
        return []
    path = Path(path_str)
    if not path.exists() or not path.is_file():
        return []
    try:
        return path.read_text(errors="replace").splitlines()[-max_lines:]
    except OSError:
        return []


def build_report(feature_id: str | None) -> dict:
    active_failures: list[dict] = []
    for marker in LATEST_FAILURE_MARKERS:
        data = _read_json(marker)
        if data is not None:
            active_failures.append(data)

    feature_failures: list[dict] = []
    if feature_id:
        feature_marker = _feature_failure_marker(feature_id)
        if feature_marker is not None:
            feature_failures.append(feature_marker)

    recent_events = _tail_ndjson(FAILURE_EVENTS_FILE, max_lines=25)

    all_failures = active_failures + feature_failures
    for failure in all_failures:
        failure["log_tail"] = _tail_log(failure.get("log_file", ""), max_lines=20)

    status = "healthy" if not all_failures else "degraded"

    return {
        "status": status,
        "feature_id": feature_id or "",
        "active_failures": active_failures,
        "feature_failures": feature_failures,
        "recent_failure_events": recent_events,
        "failure_count": len(all_failures),
    }


def main() -> int:
    feature_id = sys.argv[1].strip() if len(sys.argv) > 1 else ""
    report = build_report(feature_id or None)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
