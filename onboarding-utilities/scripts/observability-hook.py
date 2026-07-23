#!/usr/bin/env python3
"""
observability-hook.py — VS Code Agent Hook for Observability Process Lifecycle

Manages local otel-collector and prometheus processes around the orchestrator
pipeline lifecycle.

Events handled:
  SessionStart  → Start processes if not already running
  Stop          → Stop processes when pipeline ends

The hook is idempotent — starting already-running processes is a no-op,
and stopping already-stopped processes is safe.

Input:  JSON via stdin (VS Code hook protocol)
Output: JSON via stdout (hook response)
"""

from __future__ import annotations

import json
import os
import re
import sys
import subprocess
import shutil
import signal
import time
import errno
from pathlib import Path


# ─── Configuration ───────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
OBS_DIR = SCRIPT_DIR.parent / "observability"
PID_DIR = OBS_DIR / ".pids"
LOG_DIR = OBS_DIR / ".logs"
PROM_DATA_DIR = OBS_DIR / ".prom-data"
LOCAL_BIN_DIR = OBS_DIR / ".bin"
HOOK_STATE_DIR = OBS_DIR / ".hook-state"
HOOK_LOG_FILE = LOG_DIR / "observability-hook.log"
HOOK_FAILURE_FILE = HOOK_STATE_DIR / "observability_hook_last_failure.json"
HOOK_FAILURE_EVENTS_FILE = HOOK_STATE_DIR / "hook_failures.ndjson"

OTEL_CONFIG = OBS_DIR / "otel-collector-config.yml"
PROM_CONFIG = OBS_DIR / "prometheus" / "prometheus.yml"

# IST timezone offset for process log timestamps
IST_TZ = "+05:30"

# Maximum number of orchestrator log runs to retain
MAX_LOG_RUNS = 3

# Tracker statuses that indicate a pipeline is still actively running.
ACTIVE_PIPELINE_STATUSES = {"in_progress", "pending_finalization"}

# If tracker status cannot be determined, treat an active marker older than this
# threshold as stale and allow shutdown.
STALE_MARKER_MAX_AGE_SECS = 300

# Services to health-check after start
HEALTH_CHECKS = [
    ("OTel Collector", "http://localhost:13133"),
    ("Prometheus", "http://localhost:9090/-/ready"),
]


# ─── Helpers ─────────────────────────────────────────────────────────────────

def log(msg: str):
    """Log to stderr and persist to a hook log file."""
    ts = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())
    line = f"[observability-hook {ts}] {msg}"
    try:
        print(line, file=sys.stderr)
    except UnicodeEncodeError:
        # Fallback for Windows consoles with non-UTF-8 code pages.
        print(line.encode("ascii", "replace").decode("ascii"), file=sys.stderr)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(HOOK_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{line}\n")
    except OSError:
        pass


def record_failure(event: str, message: str, details: dict | None = None):
    """Persist a hook failure marker and append to consolidated failure events."""
    payload = {
        "hook": "observability-hook",
        "event": event,
        "message": message,
        "details": details or {},
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()),
        "log_file": str(HOOK_LOG_FILE),
    }
    try:
        HOOK_STATE_DIR.mkdir(parents=True, exist_ok=True)
        HOOK_FAILURE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        with open(HOOK_FAILURE_EVENTS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
        log(f"Failure marker written: {HOOK_FAILURE_FILE}")
    except OSError as e:
        log(f"WARNING: Failed to persist failure marker: {e}")


def clear_failure_marker(reason: str):
    """Clear the latest failure marker when hook health is restored."""
    try:
        if HOOK_FAILURE_FILE.exists():
            HOOK_FAILURE_FILE.unlink()
            log(f"Cleared failure marker ({reason})")
    except OSError as e:
        log(f"WARNING: Failed to clear failure marker: {e}")


def hook_response(event: str, context: str = "") -> dict:
    """Return a standard continue response, optionally with additionalContext."""
    if not context:
        return {"continue": True}
    return {
        "continue": True,
        "hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": context,
        },
    }


def get_field(data: dict, *keys, default=""):
    """Get a field from a dict trying multiple key variants."""
    for key in keys:
        if key in data:
            return data[key]
    return default


def get_tracker_status(feature_id: str) -> str | None:
    """Read orchestration status from outputs/<feature_id>/orchestration_tracker.md."""
    tracker_candidates = [
        OBS_DIR.parent / "agents" / "agents-workflow" / "outputs" / feature_id / "orchestration_tracker.md",
        OBS_DIR.parent.parent / "outputs" / feature_id / "orchestration_tracker.md",
    ]

    tracker_file = next((p for p in tracker_candidates if p.exists()), None)
    if tracker_file is None:
        return None

    try:
        contents = tracker_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    patterns = [
        # Matches markdown bullets like: - **Status:** completed
        r"(?im)^\s*[-*]?\s*\**status\**\s*\**\s*:\s*\**\s*([a-z_]+)\s*\**\s*$",
        # Matches table rows like: | Status | completed |
        r"(?im)^\s*\|\s*status\s*\|\s*([a-z_]+)\s*\|",
    ]
    for pattern in patterns:
        match = re.search(pattern, contents)
        if match:
            return match.group(1).strip().lower()
    return None


def remove_stale_active_markers(feature_id: str):
    """Best-effort cleanup for stale pipeline markers."""
    stale_candidates = [
        OBS_DIR / ".hook-state" / "active_feature_id",
        OBS_DIR / ".hook-state" / "pipeline_session_id",
    ]
    for marker in stale_candidates:
        try:
            if marker.exists():
                marker.unlink()
                log(f"Removed stale marker: {marker.name} (feature={feature_id})")
        except OSError as e:
            log(f"WARNING: Failed to remove stale marker {marker}: {e}")


def evaluate_active_marker_state() -> tuple[str, str | None, str | None, int | None]:
    """Evaluate active marker state.

    Returns: (state, feature_id, status, age_secs)
      - state='none'            → no active marker
      - state='active'          → marker exists and tracker says active
      - state='stale_status'    → marker exists but tracker status is terminal
      - state='unknown_recent'  → marker exists, status unknown, marker is recent
      - state='unknown_stale'   → marker exists, status unknown, marker is stale
    """
    hook_state_dir = SCRIPT_DIR.parent / "observability" / ".hook-state"
    active_file = hook_state_dir / "active_feature_id"
    if not active_file.exists():
        return "none", None, None, None

    feature_id = active_file.read_text().strip()
    if not feature_id:
        return "none", None, None, None

    status = get_tracker_status(feature_id)
    if status in ACTIVE_PIPELINE_STATUSES:
        return "active", feature_id, status, None
    if status:
        return "stale_status", feature_id, status, None

    try:
        age_secs = max(0, int(time.time() - active_file.stat().st_mtime))
    except OSError:
        age_secs = STALE_MARKER_MAX_AGE_SECS + 1

    if age_secs <= STALE_MARKER_MAX_AGE_SECS:
        return "unknown_recent", feature_id, None, age_secs
    return "unknown_stale", feature_id, None, age_secs


def binary_available(name: str) -> bool:
    """Check if a binary is available in local .bin/ or PATH."""
    return resolve_binary(name) is not None


def resolve_binary(name: str) -> str | None:
    """Resolve the full path to a binary, checking local .bin/ first, then PATH."""
    # Check project-local .bin/ directory first
    local_bin = LOCAL_BIN_DIR / name
    if local_bin.exists() and os.access(local_bin, os.X_OK):
        return str(local_bin)

    # Windows executable naming fallback in local .bin.
    local_bin_exe = LOCAL_BIN_DIR / f"{name}.exe"
    if local_bin_exe.exists() and os.access(local_bin_exe, os.X_OK):
        return str(local_bin_exe)

    # Cross-platform PATH lookup.
    path_hit = shutil.which(name)
    if path_hit:
        return path_hit

    path_hit_exe = shutil.which(f"{name}.exe")
    if path_hit_exe:
        return path_hit_exe

    return None


def is_running(name: str) -> bool:
    """Check if a process is running by its PID file."""
    pidfile = PID_DIR / f"{name}.pid"
    if pidfile.exists():
        try:
            pid = int(pidfile.read_text().strip())
            os.kill(pid, 0)  # Signal 0 checks if process exists
            return True
        except (ValueError, ProcessLookupError, PermissionError):
            # Stale PID file
            pidfile.unlink(missing_ok=True)
        except OSError as e:
            # On Windows, invalid PID state can surface as WinError 87.
            if getattr(e, "winerror", None) == 87 or getattr(e, "errno", None) in (errno.ESRCH,):
                pidfile.unlink(missing_ok=True)
                return False
            raise
    return False


def start_process(name: str, cmd: list[str], logfile: str) -> tuple[bool, str]:
    """Start a process in the background, save its PID.
    Rotates existing logs before starting (keeps last MAX_LOG_RUNS runs)."""
    PID_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    log_path = LOG_DIR / logfile
    rotate_ok, rotate_msg = _rotate_logs(logfile)
    if not rotate_ok:
        return False, f"Could not rotate {logfile}: {rotate_msg}"

    # Set TZ=Asia/Kolkata so both prometheus and otelcol-contrib write IST timestamps
    child_env = os.environ.copy()
    child_env["TZ"] = "Asia/Kolkata"

    try:
        with open(log_path, "w", encoding="utf-8") as lf:
            proc = subprocess.Popen(
                cmd,
                stdout=lf,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env=child_env,
            )
        pidfile = PID_DIR / f"{name}.pid"
        pidfile.write_text(str(proc.pid))
        return True, f"{name} started (PID {proc.pid})"
    except FileNotFoundError:
        return False, f"{cmd[0]} command not found"
    except Exception as e:
        return False, f"Failed to start {name}: {e}"


def _rotate_logs(logfile: str) -> tuple[bool, str]:
    """Rotate log files, keeping the last MAX_LOG_RUNS runs.
    Current log → logfile.1, logfile.1 → logfile.2, etc.
    Deletes anything older than MAX_LOG_RUNS."""
    log_path = LOG_DIR / logfile
    if not log_path.exists():
        return True, "no existing log"

    base = logfile
    # Delete the oldest if it exceeds MAX_LOG_RUNS
    for i in range(MAX_LOG_RUNS, 0, -1):
        older = LOG_DIR / f"{base}.{i}"
        newer = LOG_DIR / f"{base}.{i - 1}" if i > 1 else log_path
        if i == MAX_LOG_RUNS and older.exists():
            try:
                older.unlink()
            except OSError as e:
                if getattr(e, "winerror", None) == 32:
                    msg = f"log file lock while deleting {older.name}; skipping rotation"
                    log(f"WARNING: {msg}")
                    return False, msg
                raise
        if newer.exists():
            try:
                newer.rename(LOG_DIR / f"{base}.{i}")
            except OSError as e:
                if getattr(e, "winerror", None) == 32:
                    msg = f"log file lock while rotating {newer.name}; skipping rotation"
                    log(f"WARNING: {msg}")
                    return False, msg
                raise

    # Clean up any extra rotated files beyond MAX_LOG_RUNS
    for extra in sorted(LOG_DIR.glob(f"{base}.*")):
        try:
            idx = int(extra.suffix.lstrip('.'))
            if idx > MAX_LOG_RUNS:
                extra.unlink()
                log(f"Cleaned up old log: {extra.name}")
        except ValueError:
            pass
        except OSError as e:
            if getattr(e, "winerror", None) == 32:
                log(f"WARNING: log file lock while cleaning {extra.name}; leaving file in place")
            else:
                raise

    return True, "rotation complete"


def stop_process(name: str) -> tuple[bool, str]:
    """Stop a process by its PID file."""
    pidfile = PID_DIR / f"{name}.pid"
    if not pidfile.exists():
        return True, f"{name} is not running"
    try:
        pid = int(pidfile.read_text().strip())
        if os.name == "nt":
            # Windows-safe termination path.
            result = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if result.returncode not in (0, 128):
                combined = f"{result.stdout}\n{result.stderr}".lower()
                if "not found" not in combined and "no instance" not in combined:
                    return False, f"Failed to stop {name} (PID {pid}): {result.stderr.strip() or result.stdout.strip()}"
        else:
            os.kill(pid, signal.SIGTERM)

        # Give it a moment to exit gracefully
        for _ in range(10):
            try:
                os.kill(pid, 0)
                time.sleep(0.2)
            except ProcessLookupError:
                break
            except OSError as e:
                if getattr(e, "winerror", None) == 87 or getattr(e, "errno", None) in (errno.ESRCH,):
                    break
                raise
        pidfile.unlink(missing_ok=True)
        return True, f"{name} stopped (PID {pid})"
    except (ValueError, ProcessLookupError):
        pidfile.unlink(missing_ok=True)
        return True, f"{name} was not running (stale PID)"
    except PermissionError:
        return False, f"Permission denied stopping {name}"
    except OSError as e:
        if getattr(e, "winerror", None) == 87 or getattr(e, "errno", None) in (errno.ESRCH,):
            pidfile.unlink(missing_ok=True)
            return True, f"{name} was not running (stale PID)"
        return False, f"Failed stopping {name}: {e}"


def health_check() -> list[tuple[str, bool]]:
    """Run health checks against all services."""
    import urllib.request
    results = []
    for name, url in HEALTH_CHECKS:
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=5) as resp:
                results.append((name, resp.status == 200))
        except Exception:
            results.append((name, False))
    return results


# ─── Hook Event Handlers ────────────────────────────────────────────────────

def handle_session_start(hook_input: dict) -> dict:
    """SessionStart: ensure observability processes are running."""
    event_name = "SessionStart"
    log("SessionStart: checking observability stack...")

    # Self-heal stale markers from previous runs so Stop decisions stay accurate.
    marker_state, marker_feature_id, marker_status, marker_age = evaluate_active_marker_state()
    if marker_state == "stale_status":
        log(
            f"SessionStart self-heal: stale active marker for '{marker_feature_id}' "
            f"(tracker status '{marker_status}')"
        )
        remove_stale_active_markers(marker_feature_id)
    elif marker_state == "unknown_stale":
        log(
            f"SessionStart self-heal: stale active marker for '{marker_feature_id}' "
            f"(unknown status, age={marker_age}s)"
        )
        remove_stale_active_markers(marker_feature_id)

    # Check binaries
    otelcol_bin = "otelcol-contrib"
    prom_bin = "prometheus"

    otelcol_path = resolve_binary(otelcol_bin)
    prom_path = resolve_binary(prom_bin)

    if not otelcol_path:
        message = (
            f"{otelcol_bin} is not installed. "
            "Install by running: powershell -ExecutionPolicy Bypass -File .github/scripts/install-observability.ps1"
        )
        log(f"{otelcol_bin} not found in {LOCAL_BIN_DIR} or PATH")
        record_failure(event_name, message)
        return hook_response(event_name, f"[Observability][FAILED] {message}")

    if not prom_path:
        message = (
            f"{prom_bin} is not installed. "
            "Install by running: powershell -ExecutionPolicy Bypass -File .github/scripts/install-observability.ps1"
        )
        log(f"{prom_bin} not found in {LOCAL_BIN_DIR} or PATH")
        record_failure(event_name, message)
        return hook_response(event_name, f"[Observability][FAILED] {message}")

    # Check if already running
    otelcol_running = is_running("otelcol")
    prom_running = is_running("prometheus")

    log(f"Resolved binaries: otelcol={otelcol_path}, prometheus={prom_path}")

    if otelcol_running and prom_running:
        log("Both processes already running")
        checks = health_check()
        healthy_count = sum(1 for _, ok in checks if ok)
        total = len(checks)
        for name, ok in checks:
            log(f"  [{'OK' if ok else 'FAIL'}] {name}")
        context = (
            f"[Observability] Stack already running ({healthy_count}/{total} services healthy). "
            "Telemetry collection is active."
        )
        if healthy_count < total:
            record_failure(
                event_name,
                "Observability stack is running but one or more services are unhealthy.",
                {"healthy_count": healthy_count, "total": total},
            )
            return hook_response(
                event_name,
                (
                    f"[Observability][FAILED] Stack running with degraded health "
                    f"({healthy_count}/{total}). Check {HOOK_LOG_FILE}."
                ),
            )
        clear_failure_marker("SessionStart healthy")
        return hook_response(event_name, context)

    # Start OTel Collector
    started_services = []
    if not otelcol_running:
        if not OTEL_CONFIG.exists():
            message = f"Config not found: {OTEL_CONFIG}"
            log(f"OTel config not found: {OTEL_CONFIG}")
            record_failure(event_name, message)
            return hook_response(event_name, f"[Observability][FAILED] {message}")
        ok, msg = start_process("otelcol", [otelcol_path, f"--config={OTEL_CONFIG}"], "otelcol.log")
        log(msg)
        if ok:
            started_services.append("OTel Collector")
        else:
            if "log file lock" in msg.lower():
                checks = dict(health_check())
                if checks.get("OTel Collector", False):
                    log("OTel log file is locked but service is healthy; treating as already running")
                    started_services.append("OTel Collector (already running)")
                else:
                    message = f"Failed to start OTel Collector: {msg}"
                    record_failure(event_name, message)
                    return hook_response(event_name, f"[Observability][FAILED] {message}")
            else:
                message = f"Failed to start OTel Collector: {msg}"
                record_failure(event_name, message)
                return hook_response(event_name, f"[Observability][FAILED] {message}")
    else:
        started_services.append("OTel Collector (already running)")

    # Start Prometheus
    if not prom_running:
        PROM_DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not PROM_CONFIG.exists():
            message = f"Config not found: {PROM_CONFIG}"
            log(f"Prometheus config not found: {PROM_CONFIG}")
            record_failure(event_name, message)
            return hook_response(event_name, f"[Observability][FAILED] {message}")
        ok, msg = start_process("prometheus", [
            prom_path,
            f"--config.file={PROM_CONFIG}",
            f"--storage.tsdb.path={PROM_DATA_DIR}",
            "--web.listen-address=:9090",
            "--storage.tsdb.retention.time=7d",
        ], "prometheus.log")
        log(msg)
        if ok:
            started_services.append("Prometheus")
        else:
            if "log file lock" in msg.lower():
                checks = dict(health_check())
                if checks.get("Prometheus", False):
                    log("Prometheus log file is locked but service is healthy; treating as already running")
                    started_services.append("Prometheus (already running)")
                else:
                    message = f"Failed to start Prometheus: {msg}"
                    record_failure(event_name, message)
                    return hook_response(event_name, f"[Observability][FAILED] {message}")
            else:
                message = f"Failed to start Prometheus: {msg}"
                record_failure(event_name, message)
                return hook_response(event_name, f"[Observability][FAILED] {message}")
    else:
        started_services.append("Prometheus (already running)")

    # Wait and check health
    time.sleep(3)
    checks = health_check()
    healthy_count = sum(1 for _, ok in checks if ok)
    total = len(checks)
    for name, ok in checks:
        log(f"  [{'OK' if ok else 'FAIL'}] {name}")

    if healthy_count < total:
        message = (
            f"Stack started but health checks are degraded ({healthy_count}/{total}). "
            f"Check {HOOK_LOG_FILE}."
        )
        record_failure(
            event_name,
            "Observability services did not become fully healthy after startup.",
            {"healthy_count": healthy_count, "total": total, "services": started_services},
        )
        return hook_response(event_name, f"[Observability][FAILED] {message}")

    clear_failure_marker("SessionStart healthy")
    return hook_response(
        event_name,
        (
            f"[Observability] Stack started ({healthy_count}/{total} services healthy). "
            "Telemetry collection is active. "
            "Services: Prometheus :9090, OTel Collector :4317/:4318"
        ),
    )


def handle_stop(hook_input: dict) -> dict:
    """Stop: shut down observability processes when pipeline ends.

    IMPORTANT: Only stop processes if there is NO active pipeline running.
    If active_feature_id exists in hook state, the pipeline is still in progress
    (this may be a mid-session Stop from a follow-up question, not the final stop).
    """
    event_name = "Stop"
    log("Stop: checking if pipeline is still active...")

    marker_state, feature_id, status, age_secs = evaluate_active_marker_state()
    if marker_state == "active":
        log(
            f"Pipeline '{feature_id}' status is '{status}' — keeping observability stack running"
        )
        return {
            "continue": True,
            "hookSpecificOutput": {
                "hookEventName": "Stop",
                "additionalContext": (
                    f"[Observability] Pipeline '{feature_id}' status '{status}' — "
                    "observability stack kept running for continued telemetry collection."
                ),
            },
        }

    if marker_state == "stale_status":
        log(
            f"Detected stale active marker for '{feature_id}' (tracker status '{status}')"
        )
        remove_stale_active_markers(feature_id)
    elif marker_state == "unknown_recent":
        log(
            f"Pipeline marker '{feature_id}' has unknown status and is recent ({age_secs}s) — "
            "keeping observability stack running"
        )
        return {
            "continue": True,
            "hookSpecificOutput": {
                "hookEventName": "Stop",
                "additionalContext": (
                    f"[Observability] Pipeline '{feature_id}' marker is recent with unknown status — "
                    "stack kept running to avoid interrupting active telemetry."
                ),
            },
        }
    elif marker_state == "unknown_stale":
        log(
            f"Detected stale active marker for '{feature_id}' (unknown status, age={age_secs}s)"
        )
        remove_stale_active_markers(feature_id)

    log("No active pipeline — shutting down observability stack...")

    stopped = []
    stop_failures = []
    for name in ["otelcol", "prometheus"]:
        if is_running(name):
            ok, msg = stop_process(name)
            log(msg)
            if ok:
                stopped.append(name)
            else:
                stop_failures.append(f"{name}: {msg}")
        else:
            log(f"{name} is not running")

    if stop_failures:
        message = "; ".join(stop_failures)
        record_failure(event_name, "Failed to stop one or more observability services.", {"failures": stop_failures})
        return hook_response(event_name, f"[Observability][FAILED] {message}. Check {HOOK_LOG_FILE}.")

    if stopped:
        log(f"Stopped: {', '.join(stopped)}")
    else:
        log("Nothing to stop")

    clear_failure_marker("Stop clean shutdown")
    return {"continue": True}


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    try:
        raw_input = sys.stdin.read()
        hook_input = json.loads(raw_input) if raw_input.strip() else {}
    except json.JSONDecodeError as e:
        log(f"ERROR: Failed to parse hook input: {e}")
        record_failure("Unknown", f"Failed to parse hook input: {e}")
        print(json.dumps({"continue": True}))
        return

    event = get_field(hook_input, "hookEventName", "hook_event_name", "event", "eventName")
    log(f"Event: {event}")

    try:
        if event == "SessionStart":
            result = handle_session_start(hook_input)
        elif event == "Stop":
            result = handle_stop(hook_input)
        else:
            log(f"Ignoring event: {event}")
            result = hook_response(event or "Unknown", "[Observability] Unsupported event; no action taken")
    except Exception as e:
        record_failure(event or "Unknown", f"Unhandled hook exception: {e}")
        log(f"ERROR: Unhandled exception: {e}")
        result = hook_response(
            event or "Unknown",
            f"[Observability][FAILED] Hook crashed: {e}. Check {HOOK_LOG_FILE}.",
        )

    if result.get("continue") is True and not isinstance(result.get("hookSpecificOutput"), dict):
        result = hook_response(event or "Unknown", "[Observability] Hook completed")

    print(json.dumps(result))


if __name__ == "__main__":
    main()
