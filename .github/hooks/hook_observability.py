#!/usr/bin/env python3
"""Compatibility wrapper for observability hook.

Delegates to onboarding-utilities/scripts/observability-hook.py so this repo's
runtime hooks use the same maintained lifecycle implementation as pipeline
generation artifacts.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _fallback_response() -> None:
    print(json.dumps({"continue": True}))


def main() -> None:
    script_path = Path(__file__).resolve().parents[2] / "onboarding-utilities" / "scripts" / "observability-hook.py"
    if not script_path.exists():
        _fallback_response()
        return

    raw_input = sys.stdin.read()
    try:
        proc = subprocess.run(
            [sys.executable, str(script_path)],
            input=raw_input,
            text=True,
            capture_output=True,
            check=False,
        )
        stdout = (proc.stdout or "").strip()
        if stdout:
            print(stdout)
        else:
            _fallback_response()
    except Exception:
        _fallback_response()


if __name__ == "__main__":
    main()
