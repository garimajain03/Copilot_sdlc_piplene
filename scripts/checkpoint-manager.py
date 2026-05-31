#!/usr/bin/env python3
"""
checkpoint-manager.py — Pause, Resume, Re-run support for SDLC Pipeline Agents

Manages agent execution state via checkpoint files. Supports:
- Saving checkpoint (pause)
- Loading checkpoint (resume)
- Resetting checkpoint (re-run)
- Recording feedback for re-run
- Tracking phase completion status

Usage:
  python3 checkpoint-manager.py save --agent preflight --phase "Phase 2: Codebase Scan" --state-file /path/to/state.json
  python3 checkpoint-manager.py load --agent preflight --state-file /path/to/state.json
  python3 checkpoint-manager.py reset --agent preflight --state-file /path/to/state.json
  python3 checkpoint-manager.py feedback --agent preflight --state-file /path/to/state.json --feedback "Re-scan repo X"
  python3 checkpoint-manager.py status --state-file /path/to/state.json

Exit codes:
  0 — Success
  1 — Error
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_state(state_file: str) -> dict:
    """Load existing state or create empty state."""
    if os.path.exists(state_file):
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

    return {
        "version": "1.0.0",
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "agents": {},
    }


def save_state(state_file: str, state: dict):
    """Save state to file."""
    state["updated_at"] = utc_now()
    os.makedirs(os.path.dirname(state_file) or ".", exist_ok=True)
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def cmd_save(args):
    """Save checkpoint — mark agent phase as completed or paused."""
    state = load_state(args.state_file)
    agent = args.agent

    if agent not in state["agents"]:
        state["agents"][agent] = {
            "status": "in_progress",
            "started_at": utc_now(),
            "phases": {},
            "feedback": [],
            "run_count": 1,
            "errors": [],
        }

    agent_state = state["agents"][agent]
    agent_state["status"] = args.status if args.status else "paused"
    agent_state["updated_at"] = utc_now()

    if args.phase:
        agent_state["phases"][args.phase] = {
            "status": args.status if args.status else "completed",
            "completed_at": utc_now(),
        }

    if args.data:
        try:
            data = json.loads(args.data)
            agent_state["last_data"] = data
        except json.JSONDecodeError:
            agent_state["last_data"] = args.data

    save_state(args.state_file, state)
    print(json.dumps({"action": "save", "agent": agent, "status": agent_state["status"]}))


def cmd_load(args):
    """Load checkpoint — return agent state for resume."""
    state = load_state(args.state_file)
    agent = args.agent

    if agent not in state["agents"]:
        print(json.dumps({"action": "load", "agent": agent, "found": False}))
        return

    agent_state = state["agents"][agent]
    completed_phases = [
        phase for phase, info in agent_state.get("phases", {}).items()
        if info.get("status") == "completed"
    ]

    output = {
        "action": "load",
        "agent": agent,
        "found": True,
        "status": agent_state["status"],
        "run_count": agent_state.get("run_count", 1),
        "completed_phases": completed_phases,
        "pending_feedback": agent_state.get("feedback", []),
        "last_data": agent_state.get("last_data"),
        "errors": agent_state.get("errors", []),
    }
    print(json.dumps(output, indent=2))


def cmd_reset(args):
    """Reset checkpoint — prepare for clean re-run."""
    state = load_state(args.state_file)
    agent = args.agent

    old_run_count = 1
    old_feedback = []

    if agent in state["agents"]:
        old_run_count = state["agents"][agent].get("run_count", 1)
        old_feedback = state["agents"][agent].get("feedback", [])

    state["agents"][agent] = {
        "status": "not_started",
        "started_at": None,
        "phases": {},
        "feedback": old_feedback,  # Preserve feedback across resets
        "run_count": old_run_count + 1,
        "errors": [],
        "reset_at": utc_now(),
    }

    save_state(args.state_file, state)
    print(json.dumps({
        "action": "reset",
        "agent": agent,
        "run_count": old_run_count + 1,
        "preserved_feedback": len(old_feedback),
    }))


def cmd_feedback(args):
    """Record customer feedback for re-run."""
    state = load_state(args.state_file)
    agent = args.agent

    if agent not in state["agents"]:
        state["agents"][agent] = {
            "status": "awaiting_feedback",
            "started_at": None,
            "phases": {},
            "feedback": [],
            "run_count": 0,
            "errors": [],
        }

    state["agents"][agent]["feedback"].append({
        "message": args.feedback,
        "timestamp": utc_now(),
        "phase": args.phase,
    })
    state["agents"][agent]["status"] = "awaiting_rerun"

    save_state(args.state_file, state)
    print(json.dumps({
        "action": "feedback",
        "agent": agent,
        "total_feedback": len(state["agents"][agent]["feedback"]),
    }))


def cmd_error(args):
    """Record an error for the agent."""
    state = load_state(args.state_file)
    agent = args.agent

    if agent not in state["agents"]:
        state["agents"][agent] = {
            "status": "error",
            "started_at": None,
            "phases": {},
            "feedback": [],
            "run_count": 1,
            "errors": [],
        }

    state["agents"][agent]["errors"].append({
        "message": args.error,
        "phase": args.phase,
        "timestamp": utc_now(),
        "recoverable": args.recoverable,
    })
    state["agents"][agent]["status"] = "error"

    save_state(args.state_file, state)
    print(json.dumps({
        "action": "error",
        "agent": agent,
        "total_errors": len(state["agents"][agent]["errors"]),
        "recoverable": args.recoverable,
    }))


def cmd_status(args):
    """Show status of all agents."""
    state = load_state(args.state_file)

    summary = {
        "updated_at": state.get("updated_at"),
        "agents": {},
    }

    for agent, info in state.get("agents", {}).items():
        completed = [p for p, i in info.get("phases", {}).items() if i.get("status") == "completed"]
        summary["agents"][agent] = {
            "status": info.get("status"),
            "run_count": info.get("run_count", 1),
            "completed_phases": len(completed),
            "total_errors": len(info.get("errors", [])),
            "pending_feedback": len(info.get("feedback", [])),
        }

    print(json.dumps(summary, indent=2))


def main():
    parser = argparse.ArgumentParser(description="SDLC Pipeline Checkpoint Manager")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # save
    save_p = subparsers.add_parser("save", help="Save checkpoint")
    save_p.add_argument("--agent", required=True)
    save_p.add_argument("--phase", help="Phase name to mark")
    save_p.add_argument("--status", default="completed", choices=["completed", "paused", "in_progress"])
    save_p.add_argument("--data", help="JSON data to save with checkpoint")
    save_p.add_argument("--state-file", required=True)

    # load
    load_p = subparsers.add_parser("load", help="Load checkpoint")
    load_p.add_argument("--agent", required=True)
    load_p.add_argument("--state-file", required=True)

    # reset
    reset_p = subparsers.add_parser("reset", help="Reset for re-run")
    reset_p.add_argument("--agent", required=True)
    reset_p.add_argument("--state-file", required=True)

    # feedback
    fb_p = subparsers.add_parser("feedback", help="Record feedback")
    fb_p.add_argument("--agent", required=True)
    fb_p.add_argument("--feedback", required=True)
    fb_p.add_argument("--phase", default="general")
    fb_p.add_argument("--state-file", required=True)

    # error
    err_p = subparsers.add_parser("error", help="Record error")
    err_p.add_argument("--agent", required=True)
    err_p.add_argument("--error", required=True)
    err_p.add_argument("--phase", default="unknown")
    err_p.add_argument("--recoverable", type=bool, default=True)
    err_p.add_argument("--state-file", required=True)

    # status
    status_p = subparsers.add_parser("status", help="Show all status")
    status_p.add_argument("--state-file", required=True)

    args = parser.parse_args()

    commands = {
        "save": cmd_save,
        "load": cmd_load,
        "reset": cmd_reset,
        "feedback": cmd_feedback,
        "error": cmd_error,
        "status": cmd_status,
    }

    try:
        commands[args.command](args)
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
