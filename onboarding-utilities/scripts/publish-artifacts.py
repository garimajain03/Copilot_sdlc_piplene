#!/usr/bin/env python3
"""
publish-artifacts.py — Publish pipeline artifacts to intl-agentic-observability-store.

Called directly by the orchestrator during pipeline finalization.

Usage:
  python3 .github/hooks/publish-artifacts.py <feature_id>

Strategy:
    - Branch name = observability (shared for all tickets)
    - Checks out/pulls observability branch and publishes directly
  - Copies artifacts into <feature_id>/run_<N>/ (auto-incremented)
    - Commits and pushes directly to origin/observability
    - Post-publish verification: confirms branch on remote and SHA match

Exit codes:  0 = success, 1 = error
Output:      Single JSON object to stdout.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
OUTPUTS_DIR = REPO_ROOT / ".github" / "agents" / "agents-workflow" / "outputs"
STORE_SUBMODULE = REPO_ROOT / "intl-agentic-observability-store"
TARGET_BRANCH = "observability"
STORE_BRANCH_URL = f"https://github.com/rbilabs/intl-agentic-observability-store/tree/{TARGET_BRANCH}"
MAX_PUSH_RETRIES = 3
PUSH_RETRY_DELAY = 2
OBS_LOG_DIR = REPO_ROOT / ".github" / "observability" / ".logs"
HOOK_STATE_DIR = REPO_ROOT / ".github" / "observability" / ".hook-state"
PUBLISH_FAILURE_FILE = HOOK_STATE_DIR / "publish_artifacts_last_failure.json"
HOOK_FAILURE_EVENTS_FILE = HOOK_STATE_DIR / "hook_failures.ndjson"

LOG_FILE: Path | None = None


# ─── Helpers ─────────────────────────────────────────────────────────────────

def log(msg: str):
    """Log to stderr and persist publish-artifacts execution logs."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"[publish-artifacts {ts}] {msg}"
    print(line, file=sys.stderr)
    if LOG_FILE is not None:
        try:
            with open(LOG_FILE, "a") as f:
                f.write(f"{line}\n")
        except OSError:
            pass


def init_log(feature_id: str):
    """Initialize a per-run publish log file."""
    global LOG_FILE
    OBS_LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    LOG_FILE = OBS_LOG_DIR / f"publish-artifacts-{feature_id}-{ts}.log"
    with open(LOG_FILE, "w") as f:
        f.write(f"publish-artifacts start {datetime.now(timezone.utc).isoformat()}\n")


def record_publish_failure(error: str, extra: dict | None = None):
    """Persist latest publish-artifacts failure details for finalization review."""
    payload = {
        "hook": "publish-artifacts",
        "event": "FinalizationPublish",
        "message": error,
        "details": extra or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "log_file": str(LOG_FILE) if LOG_FILE else "",
    }
    try:
        HOOK_STATE_DIR.mkdir(parents=True, exist_ok=True)
        PUBLISH_FAILURE_FILE.write_text(json.dumps(payload, indent=2))
        with open(HOOK_FAILURE_EVENTS_FILE, "a") as f:
            f.write(json.dumps(payload) + "\n")
        log(f"Failure marker written: {PUBLISH_FAILURE_FILE}")
    except OSError as e:
        log(f"WARNING: Failed to write publish failure marker: {e}")


def clear_publish_failure_marker():
    """Clear latest publish failure marker after successful publish."""
    try:
        if PUBLISH_FAILURE_FILE.exists():
            PUBLISH_FAILURE_FILE.unlink()
            log(f"Cleared publish failure marker: {PUBLISH_FAILURE_FILE}")
    except OSError as e:
        log(f"WARNING: Failed to clear publish failure marker: {e}")

def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 60) -> tuple[bool, str]:
    cmd_str = " ".join(cmd)
    try:
        log(f"RUN: {cmd_str} (cwd={cwd or STORE_SUBMODULE})")
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout)
        out = r.stdout.strip()
        if r.returncode == 0:
            if out:
                log(f"OK: {cmd_str} -> {out}")
            else:
                log(f"OK: {cmd_str}")
            return True, out
        err = r.stderr.strip() or out
        log(f"FAIL: {cmd_str} -> {err}")
        return False, err
    except subprocess.TimeoutExpired:
        err = f"Timed out: {cmd_str}"
        log(err)
        return False, err
    except FileNotFoundError:
        err = f"Not found: {cmd[0]}"
        log(err)
        return False, err


def git(args: list[str]) -> tuple[bool, str]:
    return _run(["git"] + args, cwd=STORE_SUBMODULE)


def fail(msg: str, **extra):
    log(f"ERROR: {msg}")
    record_publish_failure(msg, extra)
    print(json.dumps({
        "success": False,
        "error": msg,
        "log_file": str(LOG_FILE) if LOG_FILE else "",
        **extra,
    }))
    sys.exit(1)


def remote_branch_exists(branch: str) -> bool:
    ok, out = git(["ls-remote", "--heads", "origin", branch])
    return ok and branch in out


def local_branch_exists(branch: str) -> bool:
    ok, _ = git(["rev-parse", "--verify", branch])
    return ok


def get_next_run_suffix(ticket_dir: Path) -> int:
    max_n = 0
    if ticket_dir.is_dir():
        for item in ticket_dir.iterdir():
            m = re.match(r"^run_(\d+)$", item.name)
            if m:
                max_n = max(max_n, int(m.group(1)))
    return max_n + 1


def _is_non_fast_forward_push_error(msg: str) -> bool:
    m = (msg or "").lower()
    markers = [
        "non-fast-forward",
        "fetch first",
        "failed to push some refs",
        "updates were rejected",
    ]
    return any(marker in m for marker in markers)


def push_with_retry(args: list[str]) -> tuple[bool, str]:
    last_err = ""
    for attempt in range(1, MAX_PUSH_RETRIES + 1):
        ok, msg = git(args)
        if ok:
            return True, msg
        last_err = msg
        if _is_non_fast_forward_push_error(msg):
            log("Push rejected as non-fast-forward; attempting fetch + rebase before retry")
            ok_fetch, fetch_msg = git(["fetch", "origin", TARGET_BRANCH])
            if not ok_fetch:
                return False, f"Push rejected and fetch failed: {fetch_msg}"

            ok_rebase, rebase_msg = git(["rebase", f"origin/{TARGET_BRANCH}"])
            if not ok_rebase:
                # Best-effort cleanup in case a rebase was started.
                git(["rebase", "--abort"])
                return False, f"Push rejected and auto-rebase failed: {rebase_msg}"

        if attempt < MAX_PUSH_RETRIES:
            time.sleep(PUSH_RETRY_DELAY)
    return False, last_err


# ─── Main publish logic ─────────────────────────────────────────────────────

def publish(feature_id: str):
    init_log(feature_id)
    log(f"Publishing artifacts for feature: {feature_id}")

    # ── Validate ─────────────────────────────────────────────────────────
    if not STORE_SUBMODULE.is_dir():
        fail("Submodule not found. Run: git submodule update --init intl-agentic-observability-store")

    source_dir = OUTPUTS_DIR / feature_id
    if not source_dir.is_dir() or not any(source_dir.iterdir()):
        fail(f"No artifacts at {source_dir}")


    # ── Prune stale remote refs, fetch latest ────────────────────────────
    ok, msg = git(["fetch", "--prune", "origin"])
    if not ok:
        fail(f"git fetch --prune failed: {msg}")

    # ── Branch checkout (shared observability branch) ────────────────────
    branch = TARGET_BRANCH
    has_remote = remote_branch_exists(branch)
    has_local = local_branch_exists(branch)

    if not has_remote:
        fail(f"Remote branch not found: origin/{branch}")

    if has_local:
        ok, msg = git(["checkout", branch])
        if not ok:
            fail(f"Failed to checkout local branch {branch}: {msg}")
    else:
        ok, msg = git(["checkout", "-b", branch, f"origin/{branch}"])
        if not ok:
            fail(f"Failed to checkout tracking branch {branch}: {msg}")

    ok, msg = git(["pull", "origin", branch])
    if not ok:
        fail(f"Failed to pull latest {branch}: {msg}")

    # ── Copy artifacts ───────────────────────────────────────────────────
    ticket_dir = STORE_SUBMODULE / feature_id
    run_n = get_next_run_suffix(ticket_dir)
    run_folder = f"run_{run_n}"
    dest = ticket_dir / run_folder
    dest.mkdir(parents=True, exist_ok=True)

    for item in source_dir.iterdir():
        d = dest / item.name
        if item.is_dir():
            if d.exists():
                shutil.rmtree(d)
            shutil.copytree(item, d)
        else:
            shutil.copy2(item, d)

    # ── Commit ───────────────────────────────────────────────────────────
    git(["add", "."])
    ok, msg = git(["commit", "-m", f"chore: publish artifacts for {feature_id} ({run_folder})"])
    if not ok:
        fail(f"Commit failed: {msg}")

    # ── Push ─────────────────────────────────────────────────────────────
    ok, msg = push_with_retry(["push", "origin", branch])
    if not ok:
        ok, msg = push_with_retry(["push", "--set-upstream", "origin", branch])
    if not ok:
        fail(f"Push failed after {MAX_PUSH_RETRIES} retries: {msg}")

    # ── Post-publish verification ────────────────────────────────────────
    # Re-fetch to confirm remote state
    git(["fetch", "origin"])
    verified_remote = remote_branch_exists(branch)
    ok, remote_sha = git(["rev-parse", f"origin/{branch}"])
    ok2, local_sha = git(["rev-parse", "HEAD"])
    sha_match = ok and ok2 and remote_sha == local_sha

    result = {
        "success": True,
        "feature_id": feature_id,
        "branch": branch,
        "run_folder": run_folder,
        "pr_url": "",
        "artifact_url": STORE_BRANCH_URL,
        "log_file": str(LOG_FILE) if LOG_FILE else "",
        "verification": {
            "remote_branch_exists": verified_remote,
            "sha_match": sha_match,
        },
    }

    if not verified_remote:
        result["success"] = False
        result["error"] = "Post-verification failed: branch not on remote after push"
    elif not sha_match:
        result["warning"] = "Local/remote SHA mismatch — push may be incomplete"

    if result["success"]:
        clear_publish_failure_marker()
    else:
        record_publish_failure(result.get("error", "Unknown publish verification failure"), result)

    print(json.dumps(result, indent=2))
    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        fail("Usage: python3 publish-artifacts.py <feature_id>")
    publish(sys.argv[1])
