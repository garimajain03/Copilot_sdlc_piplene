#!/usr/bin/env python3
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


STATE_DIR = Path("observability") / ".hook-state"
PRICING_FILE = Path("observability") / "model-pricing.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_state() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def append_md(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(text)


def load_pricing() -> dict:
    pricing_path = os.environ.get("MODEL_PRICING_FILE", str(PRICING_FILE))
    try:
        with open(pricing_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"models": {"default": {"input_per_1m_tokens": 0.0, "output_per_1m_tokens": 0.0}}}


def estimate_cost(model: str, input_tokens: int, output_tokens: int, pricing: dict) -> float:
    models = pricing.get("models", pricing)
    model_pricing = models.get(model, models.get("default", {}))
    input_price = float(model_pricing.get("input_per_1m_tokens", model_pricing.get("input_per_1m", 0.0))) / 1_000_000
    output_price = float(model_pricing.get("output_per_1m_tokens", model_pricing.get("output_per_1m", 0.0))) / 1_000_000
    return (int(input_tokens) * input_price) + (int(output_tokens) * output_price)


def _extract_output_from_text(text: str) -> Path | None:
    if not text:
        return None
    match = re.search(r"outputs[\\/](?P<feature>[A-Za-z0-9._-]+)", text)
    if not match:
        return None
    return Path("outputs") / match.group("feature")


def _latest_output_dir() -> Path:
    outputs_root = Path("outputs")
    if outputs_root.is_dir():
        dirs = [d for d in outputs_root.iterdir() if d.is_dir()]
        if dirs:
            dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return dirs[0]
    return outputs_root / "unknown"


def extract_output_folder(payload: dict) -> Path:
    for key in ("outputFolder", "output_folder", "featureOutputDir"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return Path(val.strip())

    tool_input = payload.get("toolInput", {})
    if isinstance(tool_input, dict):
        for key in ("outputFolder", "output_folder", "path"):
            val = tool_input.get(key)
            if isinstance(val, str) and val.strip():
                return Path(val.strip())
        for key in ("prompt", "description"):
            val = tool_input.get(key)
            if isinstance(val, str):
                extracted = _extract_output_from_text(val)
                if extracted:
                    return extracted

    return _latest_output_dir()


def extract_agent_name(payload: dict) -> str:
    tool_input = payload.get("toolInput", {})
    if isinstance(tool_input, dict):
        for key in ("description", "agent", "agentName"):
            val = tool_input.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return "runSubagent"


def handle_session_start(payload: dict) -> int:
    ensure_state()
    sess = {
        "started": now_iso(),
        "total_tokens": 0,
        "total_cost": 0.0,
        "agents": 0,
    }
    (STATE_DIR / "session.json").write_text(json.dumps(sess), encoding="utf-8")
    return 0


def handle_pre(payload: dict) -> int:
    if payload.get("toolName") not in ("runSubagent", "agent"):
        return 0
    ensure_state()
    snap = {
        "agent": extract_agent_name(payload),
        "start": now_iso(),
    }
    (STATE_DIR / "active_tooluse.json").write_text(json.dumps(snap), encoding="utf-8")
    return 0


def handle_post(payload: dict) -> int:
    if payload.get("toolName") not in ("runSubagent", "agent"):
        return 0

    ensure_state()
    snap_path = STATE_DIR / "active_tooluse.json"
    if snap_path.exists():
        snap = json.loads(snap_path.read_text(encoding="utf-8"))
    else:
        snap = {"agent": extract_agent_name(payload), "start": now_iso()}

    usage = payload.get("usage", {}) or {}
    in_tok = int(usage.get("input_tokens", 0) or 0)
    out_tok = int(usage.get("output_tokens", 0) or 0)
    model = str(usage.get("model", "unknown"))
    total = in_tok + out_tok
    pricing = load_pricing()
    cost = estimate_cost(model, in_tok, out_tok, pricing)

    out_dir = extract_output_folder(payload)
    tele = out_dir / "telemetry_report.md"
    costf = out_dir / "cost_report.md"

    append_md(
        tele,
        f"\n## Agent: {snap['agent']}\n"
        "| Metric | Value |\n"
        "|--------|-------|\n"
        f"| Model | {model} |\n"
        f"| Input Tokens | {in_tok} |\n"
        f"| Output Tokens | {out_tok} |\n"
        f"| Total Tokens | {total} |\n"
        f"| Est. Cost | ${cost:.6f} |\n"
        f"| Started | {snap['start']} |\n"
        f"| Completed | {now_iso()} |\n",
    )
    append_md(costf, f"\n- Agent `{snap['agent']}`: model={model}, tokens={total}, cost=${cost:.6f}\n")

    sess_path = STATE_DIR / "session.json"
    if sess_path.exists():
        sess = json.loads(sess_path.read_text(encoding="utf-8"))
    else:
        sess = {"started": now_iso(), "total_tokens": 0, "total_cost": 0.0, "agents": 0}
    sess["total_tokens"] = int(sess.get("total_tokens", 0)) + total
    sess["total_cost"] = float(sess.get("total_cost", 0.0)) + float(cost)
    sess["agents"] = int(sess.get("agents", 0)) + 1
    sess_path.write_text(json.dumps(sess), encoding="utf-8")

    snap_path.unlink(missing_ok=True)
    print(
        f"[TELEMETRY] Agent: {snap['agent']} | Model: {model} | Tokens: {total} | Cost: ${cost:.6f}"
    )
    return 0


def handle_stop(payload: dict) -> int:
    sess_path = STATE_DIR / "session.json"
    if not sess_path.exists():
        return 0

    sess = json.loads(sess_path.read_text(encoding="utf-8"))
    out_dir = extract_output_folder(payload)
    tele = out_dir / "telemetry_report.md"
    costf = out_dir / "cost_report.md"

    append_md(
        tele,
        "\n## Pipeline Summary\n"
        "| Metric | Value |\n"
        "|--------|-------|\n"
        f"| Total Agents | {int(sess.get('agents', 0))} |\n"
        f"| Total Tokens | {int(sess.get('total_tokens', 0))} |\n"
        f"| Total Cost | ${float(sess.get('total_cost', 0.0)):.6f} |\n",
    )
    append_md(costf, f"\n- Pipeline Total: tokens={int(sess.get('total_tokens', 0))}, cost=${float(sess.get('total_cost', 0.0)):.6f}\n")

    print(
        f"[TELEMETRY] Pipeline Complete | Agents: {int(sess.get('agents', 0))} | "
        f"Total Tokens: {int(sess.get('total_tokens', 0))} | Total Cost: ${float(sess.get('total_cost', 0.0)):.6f}"
    )

    sess_path.unlink(missing_ok=True)
    (STATE_DIR / "active_tooluse.json").unlink(missing_ok=True)
    return 0


def event_name(payload: dict) -> str:
    for key in ("event", "hookEventName", "eventName"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip().lower()
    return "posttooluse"


def main() -> None:
    raw = sys.stdin.read().strip()
    if not raw:
        sys.exit(0)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    try:
        ev = event_name(payload)
        if "sessionstart" in ev:
            rc = handle_session_start(payload)
        elif "pretooluse" in ev:
            rc = handle_pre(payload)
        elif ev == "stop":
            rc = handle_stop(payload)
        else:
            rc = handle_post(payload)
        sys.exit(rc)
    except Exception:
        # Telemetry must never block pipeline execution.
        sys.exit(0)


if __name__ == "__main__":
    main()
