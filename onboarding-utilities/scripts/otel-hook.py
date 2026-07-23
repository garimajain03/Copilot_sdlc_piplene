#!/usr/bin/env python3
"""
otel-hook.py — VS Code Agent Hook for OpenTelemetry Observability

Handles PreToolUse, PostToolUse, SessionStart, and Stop hook events to
automatically collect OTel metrics from Prometheus around each agent
execution in the orchestrator pipeline.

Input:  JSON via stdin (VS Code hook protocol)
Output: JSON via stdout (hook response)

Lifecycle:
  SessionStart                       → records session baseline (global, via hooks.json)
    PreToolUse  (tool_name=runSubagent/agent) → records baseline metrics snapshot (orchestrator only)
    PostToolUse (tool_name=runSubagent/agent) → queries metrics delta, appends to telemetry_report.md
  Stop                                → session cleanup (global, via hooks.json)
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import traceback
from pathlib import Path
from datetime import datetime, timezone, timedelta


# ─── Configuration ───────────────────────────────────────────────────────────

PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")
OTEL_SERVICE = os.environ.get("OTEL_SERVICE", "copilot-chat")

# IST timezone for log timestamps
IST = timezone(timedelta(hours=5, minutes=30))

# Cost rates per 1M tokens (USD).
# These defaults can be overridden from external pricing sources (URL/file/env JSON).
DEFAULT_MODEL_COST_RATES = {
    "claude-opus-4.6": {"input": 5.00, "output": 25.00},
    "claude-sonnet-4": {"input": 3.00, "output": 15.00},
    "gpt-5.2": {"input": 1.75, "output": 14.00},
    # Baseline default for the new pipeline model. Override via pricing source when needed.
    "gpt-5.3-codex": {"input": 1.75, "output": 14.00},
    "gpt-4.1": {"input": 0.00, "output": 0.00},
    "gpt-4o-mini": {"input": 0.00, "output": 0.00},
    "gpt-4o-mini-2024-07-18": {"input": 0.00, "output": 0.00},
    "copilot-nes-oct": {"input": 0.00, "output": 0.00},
    "copilot-suggestions-himalia-001": {"input": 0.00, "output": 0.00},
}

# Optional pricing source configuration (first non-empty source wins and merges over defaults).
# JSON format for all sources: {"model-name": {"input": <usd_per_1m>, "output": <usd_per_1m>}, ...}
# URL/file can also wrap this map inside a "models" key.
MODEL_PRICING_URL = os.environ.get("OTEL_MODEL_PRICING_URL", "").strip()
MODEL_PRICING_FILE = os.environ.get("OTEL_MODEL_PRICING_FILE", "").strip()
MODEL_PRICING_JSON = os.environ.get("OTEL_MODEL_PRICING_JSON", "").strip()

# Aliases to normalize model labels coming from OTel metrics and agent frontmatter.
MODEL_PRICING_ALIASES = {
    "gpt-5-3-codex": "gpt-5.3-codex",
    "gpt-5.3-codex": "gpt-5.3-codex",
    "gpt53codex": "gpt-5.3-codex",
}

# Active pricing table used for cost calculation. Populated at runtime in main().
MODEL_COST_RATES: dict[str, dict[str, float]] = {}
_UNKNOWN_PRICING_MODELS: set[str] = set()

# Agent name → feature_id mapping file (written by the orchestrator hook)
# We store state in a temp directory keyed by agent_id / session_id
STATE_DIR = Path(os.environ.get(
    "OTEL_HOOK_STATE_DIR",
    os.path.join(os.path.dirname(__file__), "..", "observability", ".hook-state")
))

# Log directory for persistent otel-hook logs
LOG_DIR = Path(os.path.join(os.path.dirname(__file__), "..", "observability", ".logs"))
HOOK_FAILURE_FILE = STATE_DIR / "otel_hook_last_failure.json"
HOOK_FAILURE_EVENTS_FILE = STATE_DIR / "hook_failures.ndjson"

# Maximum number of otel-hook log files to retain
MAX_LOG_RUNS = 3

# Pipeline agents we care about (prefix match)
PIPELINE_AGENT_PREFIXES = [
    "Agentic Flow 0",
    "Agentic Flow 1",
    "Agentic Flow 2a",
    "Agentic Flow 2",
    "Agentic Flow 3a",
    "Agentic Flow 3b",
    "Agentic Flow 3c",
    "Agentic Flow 4",
    "Agentic Flow 5",
    "Agentic Flow 6",
]

# Fallback metric name patterns — if the primary metric is not found,
# try these alternatives (VS Code may change metric names across versions)
METRIC_FALLBACKS = {
    "copilot_gen_ai_client_token_usage_sum": [
        "gen_ai_client_token_usage_sum",
        "copilot_gen_ai_client_token_usage_total",
    ],
    "copilot_copilot_chat_tool_call_count_total": [
        "copilot_chat_tool_call_count_total",
        "gen_ai_tool_call_count_total",
    ],
    "copilot_copilot_chat_tool_call_duration_sum": [
        "copilot_chat_tool_call_duration_sum",
    ],
    "copilot_gen_ai_client_operation_duration_count": [
        "gen_ai_client_operation_duration_count",
    ],
    "copilot_gen_ai_client_operation_duration_bucket": [
        "gen_ai_client_operation_duration_bucket",
    ],
    "copilot_copilot_chat_time_to_first_token_bucket": [
        "copilot_chat_time_to_first_token_bucket",
    ],
    "copilot_copilot_chat_agent_invocation_duration_count": [
        "copilot_chat_agent_invocation_duration_count",
    ],
}

# Resolved metric names cache (populated by discover_metrics)
_resolved_metrics: dict[str, str] = {}

# File logger handle (initialized in main)
_log_file = None


def get_field(data: dict, *keys, default=""):
    """Get a field from a dict trying multiple key variants (snake_case + camelCase)."""
    for key in keys:
        if key in data:
            return data[key]
    return default


def _to_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _is_agent_tool(tool_name: str) -> bool:
    return tool_name in ("runSubagent", "agent")


NON_FEATURE_DIR_NAMES = {
    "agents-repo",
    "outputs",
    "observability",
    ".github",
    "repos",
    "skills",
    "hooks",
}


def _is_valid_feature_id(value: str) -> bool:
    candidate = str(value or "").strip()
    if not candidate:
        return False
    if candidate.lower() in NON_FEATURE_DIR_NAMES:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9._-]{2,100}", candidate))


def _to_dict(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, TypeError, ValueError):
            return {}
    return {}


def _extract_usage_override(hook_input: dict, tool_input: dict) -> dict:
    """Extract usage tokens from hook payload first; return empty dict when unavailable."""
    usage_candidates = []
    usage_candidates.append(_to_dict(get_field(hook_input, "usage", default={})))
    usage_candidates.append(_to_dict(get_field(tool_input, "usage", default={})))

    tool_output = _to_dict(get_field(hook_input, "toolOutput", "tool_output", default={}))
    usage_candidates.append(_to_dict(get_field(tool_output, "usage", default={})))

    tool_response = _to_dict(get_field(hook_input, "tool_response", "toolResponse", default={}))
    usage_candidates.append(_to_dict(get_field(tool_response, "usage", default={})))

    usage = {}
    for candidate in usage_candidates:
        if candidate:
            usage = candidate
            break

    if not usage:
        return {}

    input_tokens = _to_int(
        get_field(usage, "input_tokens", "inputTokens", "prompt_tokens", "promptTokens", default=0)
    )
    output_tokens = _to_int(
        get_field(usage, "output_tokens", "outputTokens", "completion_tokens", "completionTokens", default=0)
    )
    total_tokens = _to_int(get_field(usage, "total_tokens", "totalTokens", default=0))
    if total_tokens > 0 and input_tokens == 0 and output_tokens == 0:
        input_tokens = total_tokens

    if input_tokens <= 0 and output_tokens <= 0:
        return {}

    model = (
        str(get_field(usage, "model", default="")).strip()
        or str(get_field(hook_input, "model", default="")).strip()
        or str(get_field(tool_input, "model", default="")).strip()
        or "default"
    )

    return {
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }


def normalize_model_name(model: str) -> str:
    """Normalize raw model labels to a stable lookup key."""
    if not model:
        return ""
    normalized = model.strip().lower().replace("_", "-")
    normalized = re.sub(r"\s+", "-", normalized)
    normalized = re.sub(r"[^a-z0-9.\-]", "-", normalized)
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    return normalized


def resolve_pricing_model(model: str) -> str:
    """Resolve model aliases/variants to a canonical pricing key."""
    normalized = normalize_model_name(model)
    if not normalized:
        return normalized

    if normalized in MODEL_PRICING_ALIASES:
        return MODEL_PRICING_ALIASES[normalized]

    # Handle labels like gpt-5-3-codex -> gpt-5.3-codex.
    m = re.match(r"^gpt-(\d+)-(\d+)-codex$", normalized)
    if m:
        canonical = f"gpt-{m.group(1)}.{m.group(2)}-codex"
        MODEL_PRICING_ALIASES[normalized] = canonical
        return canonical

    return normalized


def _extract_pricing_map(raw: object) -> dict:
    """Extract pricing map from either {model: rates} or {models: {model: rates}}."""
    if not isinstance(raw, dict):
        return {}
    if isinstance(raw.get("models"), dict):
        return raw["models"]
    return raw


def _coerce_pricing_map(raw: object, source_name: str) -> dict[str, dict[str, float]]:
    """Coerce arbitrary pricing JSON into canonical {model: {input, output}}."""
    pricing_map = _extract_pricing_map(raw)
    if not pricing_map:
        return {}

    coerced: dict[str, dict[str, float]] = {}
    for model_name, rates in pricing_map.items():
        if not isinstance(rates, dict):
            continue
        try:
            input_rate = float(rates.get("input", 0))
            output_rate = float(rates.get("output", 0))
        except (TypeError, ValueError):
            log(f"WARNING: Invalid pricing entry for model='{model_name}' from {source_name} — skipping")
            continue

        canonical_model = resolve_pricing_model(str(model_name))
        if canonical_model:
            coerced[canonical_model] = {
                "input": input_rate,
                "output": output_rate,
            }

    return coerced


def load_model_cost_rates() -> dict[str, dict[str, float]]:
    """Load model pricing from configured sources and merge over defaults."""
    rates = dict(DEFAULT_MODEL_COST_RATES)
    source_labels: list[str] = []

    if MODEL_PRICING_FILE:
        try:
            raw_file_pricing = json.loads(Path(MODEL_PRICING_FILE).read_text())
            file_rates = _coerce_pricing_map(raw_file_pricing, f"file:{MODEL_PRICING_FILE}")
            if file_rates:
                rates.update(file_rates)
                source_labels.append(f"file:{MODEL_PRICING_FILE}")
        except (OSError, json.JSONDecodeError) as e:
            log(f"WARNING: Failed to load OTEL_MODEL_PRICING_FILE='{MODEL_PRICING_FILE}': {e}")

    if MODEL_PRICING_JSON:
        try:
            raw_json_pricing = json.loads(MODEL_PRICING_JSON)
            json_rates = _coerce_pricing_map(raw_json_pricing, "env:OTEL_MODEL_PRICING_JSON")
            if json_rates:
                rates.update(json_rates)
                source_labels.append("env:OTEL_MODEL_PRICING_JSON")
        except json.JSONDecodeError as e:
            log(f"WARNING: Failed to parse OTEL_MODEL_PRICING_JSON: {e}")

    if MODEL_PRICING_URL:
        remote_payload = http_get(MODEL_PRICING_URL)
        if remote_payload is not None:
            url_rates = _coerce_pricing_map(remote_payload, f"url:{MODEL_PRICING_URL}")
            if url_rates:
                rates.update(url_rates)
                source_labels.append(f"url:{MODEL_PRICING_URL}")
        else:
            log(f"WARNING: Failed to fetch pricing from OTEL_MODEL_PRICING_URL='{MODEL_PRICING_URL}'")

    # Ensure canonical GPT-5.3-Codex entry exists so model-cost aggregation never misses it.
    rates.setdefault("gpt-5.3-codex", DEFAULT_MODEL_COST_RATES["gpt-5.3-codex"])

    if source_labels:
        log(f"Loaded model pricing from: {', '.join(source_labels)}")
    else:
        log("Using default model pricing table (no external pricing source configured)")

    return rates


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _init_file_logger():
    """Initialize the persistent file logger. Rotates old logs keeping MAX_LOG_RUNS."""
    global _log_file
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / "otel-hook.log"

    # Rotate existing logs
    if log_path.exists():
        for i in range(MAX_LOG_RUNS, 0, -1):
            older = LOG_DIR / f"otel-hook.log.{i}"
            newer = LOG_DIR / f"otel-hook.log.{i - 1}" if i > 1 else log_path
            if i == MAX_LOG_RUNS and older.exists():
                older.unlink()
            if newer.exists():
                newer.rename(LOG_DIR / f"otel-hook.log.{i}")
        # Clean up extras
        for extra in sorted(LOG_DIR.glob("otel-hook.log.*")):
            try:
                idx = int(extra.suffix.lstrip('.'))
                if idx > MAX_LOG_RUNS:
                    extra.unlink()
            except ValueError:
                pass

    _log_file = open(log_path, "a")
    _log_file.write(f"\n{'='*80}\n")
    _log_file.write(f"otel-hook session started at {now_ist()}\n")
    _log_file.write(f"{'='*80}\n")
    _log_file.flush()


def log(msg: str):
    """Log to stderr (visible in VS Code's Hook output channel) AND to persistent file."""
    timestamp = now_ist()
    formatted = f"[otel-hook {timestamp}] {msg}"
    print(formatted, file=sys.stderr)
    if _log_file:
        try:
            _log_file.write(f"{formatted}\n")
            _log_file.flush()
        except Exception:
            pass


def log_error(msg: str, exc: Exception | None = None):
    """Log an error with optional traceback."""
    log(f"ERROR: {msg}")
    if exc:
        tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
        for line in tb:
            log(f"  {line.rstrip()}")


def record_failure(event: str, message: str, details: dict | None = None):
    """Persist latest failure details for orchestrator finalization checks."""
    payload = {
        "hook": "otel-hook",
        "event": event,
        "message": message,
        "details": details or {},
        "timestamp": now_utc(),
        "log_file": str(LOG_DIR / "otel-hook.log"),
    }
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        HOOK_FAILURE_FILE.write_text(json.dumps(payload, indent=2))
        with open(HOOK_FAILURE_EVENTS_FILE, "a") as f:
            f.write(json.dumps(payload) + "\n")
        log(f"Failure marker written: {HOOK_FAILURE_FILE}")
    except OSError as e:
        log(f"WARNING: Failed to write OTel failure marker: {e}")


def clear_failure_marker(reason: str):
    """Clear latest OTel failure marker after successful hook execution."""
    try:
        if HOOK_FAILURE_FILE.exists():
            HOOK_FAILURE_FILE.unlink()
            log(f"Cleared failure marker ({reason})")
    except OSError as e:
        log(f"WARNING: Failed to clear OTel failure marker: {e}")


def hook_response(event: str, context: str = "") -> dict:
    """Return a standard continue response, optionally with additional context."""
    if not context:
        context = "[OTel] Hook completed"
    return {
        "continue": True,
        "hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": context,
        },
    }


def now_ist() -> str:
    """Return current time in IST as ISO-8601 string."""
    return datetime.now(IST).strftime("%Y-%m-%dT%H:%M:%S+05:30")


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_epoch() -> float:
    return time.time()


def is_pipeline_agent(agent_type: str) -> bool:
    """Check if this agent is one of our pipeline agents."""
    if not agent_type:
        return False
    return any(agent_type.startswith(prefix) for prefix in PIPELINE_AGENT_PREFIXES)


def safe_filename(name: str) -> str:
    """Convert agent name to a filesystem-safe string."""
    return name.replace(" ", "_").replace("/", "_").replace(".", "_")


def http_get(url: str, timeout: int = 5) -> dict | None:
    """Simple HTTP GET using urllib (no external deps)."""
    import urllib.request
    import urllib.error
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.URLError as e:
        log(f"HTTP GET failed for {url}: {e.reason}")
        return None
    except Exception as e:
        log(f"HTTP GET unexpected error for {url}: {type(e).__name__}: {e}")
        return None


def prom_query(query: str, ts: float | None = None) -> dict | None:
    """Query Prometheus instant query API."""
    import urllib.parse
    url = f"{PROMETHEUS_URL}/api/v1/query?query={urllib.parse.quote(query)}"
    if ts:
        url += f"&time={ts}"
    result = http_get(url)
    if result and result.get("status") == "error":
        log(f"Prometheus query error: {result.get('error', 'unknown')} | query={query}")
        return None
    return result


def prom_scalar(query: str, ts: float | None = None) -> str:
    """Get a single scalar value from Prometheus."""
    result = prom_query(query, ts)
    if not result:
        return "N/A"
    try:
        results = result.get("data", {}).get("result", [])
        if results:
            return results[0]["value"][1]
    except (KeyError, IndexError) as e:
        log(f"prom_scalar parse error: {e} | query={query}")
    return "N/A"


def prom_by_label(query: str, label: str, ts: float | None = None) -> list[tuple[str, str]]:
    """Get metric values grouped by a label."""
    result = prom_query(query, ts)
    if not result:
        return []
    try:
        results = result.get("data", {}).get("result", [])
        return [
            (r["metric"].get(label, "unknown"), r["value"][1])
            for r in sorted(results, key=lambda x: float(x["value"][1]), reverse=True)
        ]
    except (KeyError, IndexError):
        return []


def discover_session_id() -> str | None:
    """Discover the current VS Code session_id from Prometheus metrics.

    The session_id is a resource-level label (format: {machineId}{windowOpenTimestamp})
    promoted to metric labels via resource_to_telemetry_conversion in the OTel collector.
    It scopes metrics to the current VS Code window — all chat sessions and subagents
    within the same window share this value."""
    # Try the primary metric first, then fallbacks
    for metric in [resolve_metric("copilot_gen_ai_client_token_usage_sum"),
                   "copilot_gen_ai_client_operation_duration_count"]:
        result = prom_query(f'topk(1, {metric})')
        if result:
            try:
                results = result.get("data", {}).get("result", [])
                if results:
                    sid = results[0]["metric"].get("session_id")
                    if sid:
                        log(f"Discovered session_id from Prometheus via {metric}: {sid}")
                        return sid
            except (KeyError, IndexError):
                continue
    log("WARNING: Could not discover session_id from any metric")
    return None


def discover_metrics() -> dict[str, list[str]]:
    """Discover all copilot-related metric names available in Prometheus.
    Returns a dict grouping metrics by category for diagnostic logging."""
    global _resolved_metrics
    result = prom_query('{__name__=~"copilot_.*"}')
    if not result:
        log("WARNING: Metric discovery query returned no data")
        return {}

    metric_names: set[str] = set()
    try:
        for r in result.get("data", {}).get("result", []):
            name = r.get("metric", {}).get("__name__", "")
            if name:
                metric_names.add(name)
    except (KeyError, TypeError) as e:
        log_error("Failed to parse metric discovery response", e)
        return {}

    # Categorize
    categories: dict[str, list[str]] = {
        "token_usage": [],
        "tool_calls": [],
        "operation_duration": [],
        "agent_invocation": [],
        "other": [],
    }
    for name in sorted(metric_names):
        if "token_usage" in name:
            categories["token_usage"].append(name)
        elif "tool_call" in name:
            categories["tool_calls"].append(name)
        elif "operation_duration" in name:
            categories["operation_duration"].append(name)
        elif "agent_invocation" in name:
            categories["agent_invocation"].append(name)
        else:
            categories["other"].append(name)

    log(f"Metric discovery: {len(metric_names)} copilot metrics found")
    for cat, names in categories.items():
        if names:
            log(f"  {cat}: {names}")

    # Auto-resolve fallback metric names
    for primary, fallbacks in METRIC_FALLBACKS.items():
        if primary in metric_names:
            _resolved_metrics[primary] = primary
        else:
            resolved = False
            for fb in fallbacks:
                if fb in metric_names:
                    log(f"  Metric fallback: {primary} → {fb}")
                    _resolved_metrics[primary] = fb
                    resolved = True
                    break
            if not resolved:
                log(f"  WARNING: No metric found for {primary} (tried: {fallbacks})")
                _resolved_metrics[primary] = primary  # Use original, will return N/A

    return categories


def resolve_metric(primary_name: str) -> str:
    """Resolve a metric name, using fallback if the primary was not found during discovery."""
    return _resolved_metrics.get(primary_name, primary_name)


def load_or_discover_session_id() -> str:
    """Load cached session_id or discover from Prometheus. Returns filter string."""
    sid_file = STATE_DIR / "pipeline_session_id"
    if sid_file.exists():
        sid = sid_file.read_text().strip()
        if sid:
            return sid
    sid = discover_session_id() or ""
    if sid:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        sid_file.write_text(sid)
        log(f"Cached session_id: {sid}")
    return sid


def sid_filter(session_id: str) -> str:
    """Build a Prometheus label filter clause for session_id.
    Returns e.g. ',session_id="abc123"' or '' if no session_id."""
    if session_id:
        return f',session_id="{session_id}"'
    return ""


def _canonical_token_type(token_type: str) -> str:
    """Normalize provider-specific token labels to input/output buckets."""
    normalized = str(token_type or "").strip().lower()
    if normalized in ("input", "prompt", "request", "in"):
        return "input"
    if normalized in ("output", "completion", "response", "out"):
        return "output"
    return ""


def _sum_tokens_by_type(tokens_by_model: dict, token_type: str) -> float:
    """Sum one token bucket across all models."""
    total = 0.0
    for model_values in tokens_by_model.values():
        try:
            total += float(model_values.get(token_type, 0))
        except (TypeError, ValueError):
            continue
    return total


def prom_tokens_by_model(sf: str = "", ts: float | None = None) -> dict[str, dict[str, float]]:
    """Get token usage grouped by model and token type.
    Returns: {model: {"input": val, "output": val}}"""
    metric = resolve_metric("copilot_gen_ai_client_token_usage_sum")
    result = prom_query(
        f"sum by (gen_ai_request_model, gen_ai_token_type) ({metric}{{{sf.lstrip(',')}}})",
        ts,
    )
    if not result:
        return {}
    models: dict[str, dict[str, float]] = {}
    try:
        for r in result.get("data", {}).get("result", []):
            model = r["metric"].get("gen_ai_request_model", "unknown")
            token_type = _canonical_token_type(r["metric"].get("gen_ai_token_type", "unknown"))
            if not token_type:
                continue
            val = float(r["value"][1])
            bucket = models.setdefault(model, {"input": 0.0, "output": 0.0})
            bucket[token_type] += val
    except (KeyError, IndexError) as e:
        log_error("prom_tokens_by_model parse error", e)
    except (TypeError, ValueError) as e:
        log_error("prom_tokens_by_model numeric parse error", e)
    return models


def prom_tool_counts(sf: str = "", ts: float | None = None) -> dict[str, str]:
    """Get tool call counts grouped by tool name.
    Returns: {tool_name: count_str}"""
    metric = resolve_metric("copilot_copilot_chat_tool_call_count_total")
    result = prom_query(
        f"sum by (gen_ai_tool_name) ({metric}{{{sf.lstrip(',')}}})",
        ts,
    )
    if not result:
        return {}
    tools: dict[str, str] = {}
    try:
        for r in result.get("data", {}).get("result", []):
            name = r["metric"].get("gen_ai_tool_name", "unknown")
            tools[name] = r["value"][1]
    except (KeyError, IndexError) as e:
        log_error("prom_tool_counts parse error", e)
    return tools


def prom_tool_duration_total(sf: str = "", ts: float | None = None) -> str:
    """Get total tool call duration sum (seconds)."""
    metric = resolve_metric("copilot_copilot_chat_tool_call_duration_sum")
    return prom_scalar(
        f"sum({metric}{{{sf.lstrip(',')}}})", ts
    )


def prom_tool_duration_by_tool(sf: str = "", ts: float | None = None) -> dict[str, str]:
    """Get tool call duration sum grouped by tool name.
    Returns: {tool_name: duration_seconds_str}"""
    metric = resolve_metric("copilot_copilot_chat_tool_call_duration_sum")
    result = prom_query(
        f"sum by (gen_ai_tool_name) ({metric}{{{sf.lstrip(',')}}})",
        ts,
    )
    if not result:
        return {}
    tools: dict[str, str] = {}
    try:
        for r in result.get("data", {}).get("result", []):
            name = r["metric"].get("gen_ai_tool_name", "unknown")
            tools[name] = r["value"][1]
    except (KeyError, IndexError) as e:
        log_error("prom_tool_duration_by_tool parse error", e)
    return tools


def prom_llm_calls_by_model(sf: str = "", ts: float | None = None) -> dict[str, str]:
    """Get LLM call counts grouped by model.
    Returns: {model: count_str}"""
    metric = resolve_metric("copilot_gen_ai_client_operation_duration_count")
    result = prom_query(
        f"sum by (gen_ai_request_model) ({metric}{{{sf.lstrip(',')}}})",
        ts,
    )
    if not result:
        return {}
    models: dict[str, str] = {}
    try:
        for r in result.get("data", {}).get("result", []):
            name = r["metric"].get("gen_ai_request_model", "unknown")
            models[name] = r["value"][1]
    except (KeyError, IndexError) as e:
        log_error("prom_llm_calls_by_model parse error", e)
    return models


def compute_cost(tokens: float, model: str, token_type: str) -> float:
    """Compute cost in USD for a given token count using MODEL_COST_RATES."""
    global MODEL_COST_RATES
    if not MODEL_COST_RATES:
        MODEL_COST_RATES = load_model_cost_rates()

    canonical_model = resolve_pricing_model(model)
    rates = MODEL_COST_RATES.get(canonical_model)
    if not rates:
        # Preserve previous fallback behavior but log unknown model keys once.
        if canonical_model not in _UNKNOWN_PRICING_MODELS:
            _UNKNOWN_PRICING_MODELS.add(canonical_model)
            log(
                "WARNING: No pricing configured for model "
                f"'{model}' (canonical='{canonical_model}'). Using fallback rates."
            )
        rates = {"input": 0.15, "output": 0.60}

    rate_per_million = rates.get(token_type, 0)
    return (tokens / 1_000_000) * rate_per_million


def compute_delta_numeric(baseline_val: str, current_val: str) -> float:
    """Compute numeric delta between two metric values."""
    try:
        b = float(baseline_val) if baseline_val not in ("N/A", "") else 0
        c = float(current_val) if current_val not in ("N/A", "") else 0
        return max(c - b, 0)
    except (ValueError, TypeError):
        return 0


def check_stack() -> bool:
    """Check if the observability stack is reachable."""
    import urllib.request
    import urllib.error
    try:
        req = urllib.request.Request(f"{PROMETHEUS_URL}/-/ready")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except urllib.error.URLError as e:
        log(f"Stack check failed: URLError: {e.reason}")
        return False
    except Exception as e:
        log(f"Stack check failed: {type(e).__name__}: {e}")
        return False


def _extract_feature_id_from_text(text: str) -> str | None:
    if not text:
        return None
    # Preferred pattern: outputs/<FEATURE_ID>; choose the last valid segment.
    matches = re.findall(r"(?:^|[\\/])outputs[\\/]+([A-Za-z0-9._-]+)", text)
    for candidate in reversed(matches):
        if _is_valid_feature_id(candidate):
            return candidate
    # Fallback ticket-like ID.
    ticket_ids = re.findall(r"\b([A-Z][A-Z0-9]+-\d+)\b", text)
    for candidate in reversed(ticket_ids):
        if _is_valid_feature_id(candidate):
            return candidate
    return None


def _extract_feature_id_from_payload(hook_input: dict, tool_input: dict, cwd: str) -> str | None:
    """Resolve feature id from payload hints before falling back to workspace scans."""
    output_hints = [
        get_field(hook_input, "outputFolder", "output_folder", "featureOutputDir", default=""),
        get_field(tool_input, "outputFolder", "output_folder", "featureOutputDir", default=""),
    ]
    for hint in output_hints:
        hint_text = str(hint).strip()
        if not hint_text:
            continue
        extracted = _extract_feature_id_from_text(hint_text)
        if extracted:
            return extracted

        hint_path = Path(hint_text)
        if not hint_path.is_absolute():
            hint_path = (Path(cwd).resolve() / hint_path).resolve()
        parts = [p.lower() for p in hint_path.parts]
        if "outputs" in parts:
            output_indices = [i for i, p in enumerate(parts) if p == "outputs"]
            for idx in reversed(output_indices):
                if len(hint_path.parts) > idx + 1:
                    candidate = hint_path.parts[idx + 1]
                    if _is_valid_feature_id(candidate):
                        return candidate

    # Prefer active feature marker before free-text parsing fallback.
    active_feature_file = STATE_DIR / "active_feature_id"
    if active_feature_file.exists():
        try:
            active_feature = active_feature_file.read_text().strip()
            if _is_valid_feature_id(active_feature):
                return active_feature
        except OSError:
            pass

    text_hints = [
        str(get_field(tool_input, "prompt", default="")),
        str(get_field(tool_input, "description", default="")),
        str(get_field(hook_input, "prompt", default="")),
        str(get_field(hook_input, "description", default="")),
    ]
    for text in text_hints:
        extracted = _extract_feature_id_from_text(text)
        if extracted:
            return extracted

    return find_feature_id(cwd)


def find_feature_id(cwd: str) -> str | None:
    """Try to find the active feature_id from the orchestrator's output folder."""
    # Check if there's a feature_id file in state dir
    fid_file = STATE_DIR / "active_feature_id"
    if fid_file.exists():
        try:
            fid = fid_file.read_text().strip()
            if _is_valid_feature_id(fid):
                log(f"Feature ID from state file: {fid}")
                return fid
        except OSError as e:
            log_error(f"Failed to read feature_id file: {fid_file}", e)

    # Try multiple candidate workspace roots (cwd may not be the repo root)
    candidates = [
        Path(cwd),
        Path(cwd).resolve(),
        # Walk up to find a directory containing .github/agents/
        *(p for p in Path(cwd).resolve().parents if (p / ".github" / "agents").is_dir()),
        # Also try SCRIPT_DIR-relative (script is at .github/hooks/)
        Path(__file__).resolve().parent.parent.parent,
    ]

    for root in candidates:
        output_roots = [
            root / ".github" / "agents" / "agents-workflow" / "outputs",
            root / "outputs",
        ]
        for outputs_dir in output_roots:
            if not outputs_dir.exists():
                continue

            trackers = list(outputs_dir.glob("*/orchestration_tracker.md"))
            if trackers:
                latest = max(trackers, key=lambda p: p.stat().st_mtime)
                fid = latest.parent.name
                if _is_valid_feature_id(fid):
                    log(f"Feature ID from tracker scan ({outputs_dir}): {fid}")
                    return fid

            feature_dirs = [p for p in outputs_dir.iterdir() if p.is_dir() and _is_valid_feature_id(p.name)]
            if feature_dirs:
                latest_dir = max(feature_dirs, key=lambda p: p.stat().st_mtime)
                fid = latest_dir.name
                log(f"Feature ID from latest output directory ({outputs_dir}): {fid}")
                return fid

    log(f"WARNING: Could not determine feature_id. cwd={cwd}, candidates={[str(c) for c in candidates[:3]]}")
    return None


def capture_baseline() -> dict:
    """Capture current metric values as a baseline for delta calculation.
    Runs metric discovery on the first call to resolve fallback metric names."""
    baseline = {
        "timestamp": now_epoch(),
        "iso": now_utc(),
    }
    if not check_stack():
        baseline["stack_available"] = False
        log("WARNING: Stack unavailable — baseline will have no metric data")
        return baseline

    baseline["stack_available"] = True

    # Run metric discovery if not already done (populates _resolved_metrics)
    if not _resolved_metrics:
        log("Running initial metric discovery...")
        categories = discover_metrics()
        if not categories:
            log("WARNING: Metric discovery found no copilot metrics — "
                "VS Code may not be sending OTel data to the collector")
            baseline["discovery_warning"] = "no_copilot_metrics_found"

    # Discover and cache the session_id for scoped queries
    session_id = load_or_discover_session_id()
    baseline["session_id"] = session_id
    sf = sid_filter(session_id)

    tool_count_metric = resolve_metric("copilot_copilot_chat_tool_call_count_total")
    agent_metric = resolve_metric("copilot_copilot_chat_agent_invocation_duration_count")

    baseline_tokens_by_model = prom_tokens_by_model(sf)
    baseline["tokens_by_model"] = baseline_tokens_by_model
    baseline["tokens_input"] = _sum_tokens_by_type(baseline_tokens_by_model, "input")
    baseline["tokens_output"] = _sum_tokens_by_type(baseline_tokens_by_model, "output")

    baseline["tool_calls"] = prom_scalar(
        f"sum({tool_count_metric}{{{sf.lstrip(',')}}})"
    )
    baseline["agent_invocations"] = prom_scalar(
        f"sum({agent_metric}{{{sf.lstrip(',')}}})"
    )
    baseline["tool_counts_by_tool"] = prom_tool_counts(sf)
    baseline["tool_duration_total"] = prom_tool_duration_total(sf)
    baseline["tool_duration_by_tool"] = prom_tool_duration_by_tool(sf)
    baseline["llm_calls_by_model"] = prom_llm_calls_by_model(sf)

    # Log baseline summary for diagnostics
    log(f"Baseline captured: tokens_in={baseline['tokens_input']}, "
        f"tokens_out={baseline['tokens_output']}, "
        f"tool_calls={baseline['tool_calls']}, "
        f"session_id={'set' if session_id else 'none'}, "
        f"models={list(baseline['tokens_by_model'].keys()) or 'none'}")

    return baseline


def compute_delta(baseline_val: str, current_val: str) -> str:
    """Compute delta between two metric values."""
    try:
        b = float(baseline_val) if baseline_val != "N/A" else 0
        c = float(current_val) if current_val != "N/A" else 0
        delta = c - b
        return f"{delta:,.0f}" if delta >= 0 else "N/A"
    except (ValueError, TypeError):
        return "N/A"




# ─── State Management ────────────────────────────────────────────────────────

def save_state(key: str, data: dict):
    """Save hook state to disk."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_file = STATE_DIR / f"{safe_filename(key)}.json"
    try:
        state_file.write_text(json.dumps(data, indent=2))
        log(f"State saved: {state_file.name}")
    except OSError as e:
        log_error(f"Failed to save state to {state_file}", e)


def load_state(key: str) -> dict | None:
    """Load hook state from disk."""
    state_file = STATE_DIR / f"{safe_filename(key)}.json"
    if state_file.exists():
        try:
            data = json.loads(state_file.read_text())
            state_file.unlink()  # Clean up after reading
            return data
        except json.JSONDecodeError as e:
            log_error(f"Corrupt state file {state_file} — removing", e)
            state_file.unlink(missing_ok=True)
        except OSError as e:
            log_error(f"Failed to read state file {state_file}", e)
    return None


def set_active_feature_id(feature_id: str):
    """Record the active feature_id for agent-scoped hooks to discover."""
    if not _is_valid_feature_id(feature_id):
        log(f"WARNING: refusing to set invalid active feature id: {feature_id}")
        return
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / "active_feature_id").write_text(feature_id)


def _load_fallback_tooluse_baseline(tool_use_id: str, agent_name: str, hook_session_id: str) -> dict | None:
    """Recover baseline by scanning state files when direct key lookup misses."""
    if not STATE_DIR.exists():
        return None

    candidates = []
    for p in STATE_DIR.glob("tooluse_*.json"):
        try:
            payload = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            continue

        score = 0
        if payload.get("tool_use_id") == tool_use_id:
            score += 5
        if agent_name and payload.get("agent_name") == agent_name:
            score += 2
        if hook_session_id and payload.get("hook_session_id") == hook_session_id:
            score += 2
        if score <= 0:
            continue
        candidates.append((score, payload.get("timestamp", 0), p, payload))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    _, _, chosen_path, chosen_payload = candidates[0]
    try:
        chosen_path.unlink(missing_ok=True)
    except OSError:
        pass

    log(
        f"Recovered tooluse baseline from fallback scan: file={chosen_path.name}, "
        f"tool_use_id={chosen_payload.get('tool_use_id', '')}"
    )
    return chosen_payload


def parse_iso8601_utc(value: str) -> datetime | None:
    """Parse the hook's UTC timestamps consistently."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def update_human_wait_json(outputs_dir: Path, feature_id: str, interaction_entry: dict):
    """Incrementally update telemetry JSON with human wait interactions."""
    json_file = outputs_dir / f"{feature_id}_telemetry_report.json"

    if json_file.exists():
        try:
            report = json.loads(json_file.read_text())
        except (json.JSONDecodeError, OSError) as e:
            log_error("Failed to read existing telemetry JSON for human wait update — starting fresh", e)
            report = {}
    else:
        report = {}

    report.setdefault("feature_id", feature_id)
    report.setdefault("service", OTEL_SERVICE)
    report.setdefault("prometheus_url", PROMETHEUS_URL)
    report.setdefault("cost_rates", MODEL_COST_RATES)
    report.setdefault("agents", [])
    report.setdefault("human_interactions", [])

    if not report.get("pipeline_started_at"):
        report["pipeline_started_at"] = interaction_entry.get("start_time", now_utc())

    report["human_interactions"].append(interaction_entry)
    report["last_updated"] = now_utc()

    interactions = report["human_interactions"]
    total_human_wait = sum(i.get("wait_duration_seconds", 0) for i in interactions)
    total_agent_duration = sum(a.get("duration_seconds", 0) for a in report.get("agents", []))

    report["human_interaction_count"] = len(interactions)
    report["total_human_wait_seconds"] = round(total_human_wait, 2)
    report["total_agent_execution_seconds"] = round(total_agent_duration, 2)
    report["pipeline_duration_seconds"] = round(total_agent_duration, 2)

    start_dt = parse_iso8601_utc(report.get("pipeline_started_at", ""))
    end_candidates = [parse_iso8601_utc(a.get("end_time", "")) for a in report.get("agents", [])]
    end_candidates.extend(parse_iso8601_utc(i.get("end_time", "")) for i in interactions)
    end_candidates = [dt for dt in end_candidates if dt is not None]
    if start_dt and end_candidates:
        report["total_wall_clock_seconds"] = round((max(end_candidates) - start_dt).total_seconds(), 2)
    else:
        report["total_wall_clock_seconds"] = round(total_agent_duration + total_human_wait, 2)

    json_file.write_text(json.dumps(report, indent=2))
    log(f"Telemetry JSON human wait updated → {json_file}")


# ─── Telemetry Report Writer ────────────────────────────────────────────────

def resolve_outputs_dir(feature_id: str, cwd: str) -> Path:
    """Resolve the outputs directory for a feature."""
    resolved_feature_id = feature_id if _is_valid_feature_id(feature_id) else ""
    if not resolved_feature_id:
        resolved_feature_id = find_feature_id(cwd) or ""
    if not _is_valid_feature_id(resolved_feature_id):
        resolved_feature_id = "unknown-feature"

    cwd_path = Path(cwd).resolve()
    workspace_root = Path(__file__).resolve().parent.parent.parent
    selected_outputs_root: Path | None = None

    for candidate in [cwd_path, *cwd_path.parents, workspace_root]:
        modern_root = candidate / "outputs"
        legacy_root = candidate / ".github" / "agents" / "agents-workflow" / "outputs"

        if (modern_root / resolved_feature_id).is_dir() or modern_root.is_dir():
            workspace_root = candidate
            selected_outputs_root = modern_root
            break

        if (legacy_root / resolved_feature_id).is_dir() or legacy_root.is_dir():
            workspace_root = candidate
            selected_outputs_root = legacy_root
            break

    if selected_outputs_root is None:
        selected_outputs_root = workspace_root / "outputs"

    outputs_dir = selected_outputs_root / resolved_feature_id
    outputs_dir.mkdir(parents=True, exist_ok=True)
    return outputs_dir


def build_agent_json_entry(
    agent_name: str,
    start_iso: str,
    end_iso: str,
    duration_s: float,
    baseline: dict,
    stack_available: bool,
) -> dict:
    """Build a structured JSON entry for one agent run with all KPI data."""
    entry: dict = {
        "agent_name": agent_name,
        "start_time": start_iso,
        "end_time": end_iso,
        "duration_seconds": round(duration_s, 2),
        "stack_available": stack_available,
    }

    if not stack_available:
        return entry

    window = max(int(duration_s), 30)
    session_id = baseline.get("session_id", "")
    sf = sid_filter(session_id)
    entry["session_id"] = session_id

    # ── Token deltas (total) ──
    cur_tokens_by_model = prom_tokens_by_model(sf)
    cur_tokens_in = _sum_tokens_by_type(cur_tokens_by_model, "input")
    cur_tokens_out = _sum_tokens_by_type(cur_tokens_by_model, "output")
    delta_in = compute_delta_numeric(baseline.get("tokens_input", 0), cur_tokens_in)
    delta_out = compute_delta_numeric(baseline.get("tokens_output", 0), cur_tokens_out)

    entry["tokens"] = {
        "input": delta_in,
        "output": delta_out,
        "total": delta_in + delta_out,
    }

    # ── Token deltas by model ──
    cur_tokens_by_model = prom_tokens_by_model(sf)
    baseline_tokens_by_model = baseline.get("tokens_by_model", {})
    all_models = set(list(cur_tokens_by_model.keys()) + list(baseline_tokens_by_model.keys()))
    tokens_by_model = {}
    for model in sorted(all_models):
        cur = cur_tokens_by_model.get(model, {})
        base = baseline_tokens_by_model.get(model, {})
        d_in = compute_delta_numeric(base.get("input", "N/A"), cur.get("input", "N/A"))
        d_out = compute_delta_numeric(base.get("output", "N/A"), cur.get("output", "N/A"))
        if d_in > 0 or d_out > 0:
            tokens_by_model[model] = {
                "input": d_in,
                "output": d_out,
                "total": d_in + d_out,
            }
    entry["tokens_by_model"] = tokens_by_model

    # ── Cost by model (for this agent) ──
    cost_by_model = {}
    agent_cost_input_total = 0
    agent_cost_output_total = 0
    for model, toks in tokens_by_model.items():
        c_in = compute_cost(toks["input"], model, "input")
        c_out = compute_cost(toks["output"], model, "output")
        cost_by_model[model] = {
            "input_cost": round(c_in, 6),
            "output_cost": round(c_out, 6),
            "total_cost": round(c_in + c_out, 6),
        }
        agent_cost_input_total += c_in
        agent_cost_output_total += c_out
    entry["cost_by_model"] = cost_by_model
    entry["cost"] = {
        "input_cost": round(agent_cost_input_total, 6),
        "output_cost": round(agent_cost_output_total, 6),
        "total_cost": round(agent_cost_input_total + agent_cost_output_total, 6),
    }

    # ── Tool usage count (delta per tool) ──
    cur_tool_counts = prom_tool_counts(sf)
    baseline_tool_counts = baseline.get("tool_counts_by_tool", {})
    all_tools = set(list(cur_tool_counts.keys()) + list(baseline_tool_counts.keys()))
    tool_usage = {}
    tool_usage_total = 0
    for tool in sorted(all_tools):
        delta = compute_delta_numeric(baseline_tool_counts.get(tool, "0"), cur_tool_counts.get(tool, "0"))
        if delta > 0:
            tool_usage[tool] = int(delta)
            tool_usage_total += int(delta)
    entry["tool_usage"] = tool_usage
    entry["tool_usage_total"] = tool_usage_total

    # ── Tool call duration (delta per tool and total) ──
    cur_tool_dur_total = prom_tool_duration_total(sf)
    baseline_tool_dur_total = baseline.get("tool_duration_total", "0")
    entry["tool_call_duration_total"] = round(
        compute_delta_numeric(baseline_tool_dur_total, cur_tool_dur_total), 2
    )

    cur_tool_dur_by_tool = prom_tool_duration_by_tool(sf)
    baseline_tool_dur_by_tool = baseline.get("tool_duration_by_tool", {})
    all_dur_tools = set(list(cur_tool_dur_by_tool.keys()) + list(baseline_tool_dur_by_tool.keys()))
    tool_duration_by_tool = {}
    for tool in sorted(all_dur_tools):
        delta = compute_delta_numeric(
            baseline_tool_dur_by_tool.get(tool, "0"), cur_tool_dur_by_tool.get(tool, "0")
        )
        if delta > 0:
            tool_duration_by_tool[tool] = round(delta, 2)
    entry["tool_call_duration_by_tool"] = tool_duration_by_tool

    # ── LLM calls by model (delta) ──
    cur_llm_calls = prom_llm_calls_by_model(sf)
    baseline_llm_calls = baseline.get("llm_calls_by_model", {})
    all_llm_models = set(list(cur_llm_calls.keys()) + list(baseline_llm_calls.keys()))
    llm_calls = {}
    for model in sorted(all_llm_models):
        delta = compute_delta_numeric(baseline_llm_calls.get(model, "0"), cur_llm_calls.get(model, "0"))
        if delta > 0:
            llm_calls[model] = int(delta)
    entry["llm_calls_by_model"] = llm_calls

    # ── Latency percentiles ──
    sf_bare = sf.lstrip(',')
    op_dur_metric = resolve_metric("copilot_gen_ai_client_operation_duration_bucket")
    ttft_metric = resolve_metric("copilot_copilot_chat_time_to_first_token_bucket")
    entry["latency"] = {
        "llm_call_p50": prom_scalar(
            f"histogram_quantile(0.50, sum(rate({op_dur_metric}{{{sf_bare}}}[{window}s])) by (le))"
        ),
        "llm_call_p95": prom_scalar(
            f"histogram_quantile(0.95, sum(rate({op_dur_metric}{{{sf_bare}}}[{window}s])) by (le))"
        ),
        "ttft_p50": prom_scalar(
            f"histogram_quantile(0.50, sum(rate({ttft_metric}{{{sf_bare}}}[{window}s])) by (le))"
        ),
        "ttft_p95": prom_scalar(
            f"histogram_quantile(0.95, sum(rate({ttft_metric}{{{sf_bare}}}[{window}s])) by (le))"
        ),
    }

    return entry


def update_telemetry_json(outputs_dir: Path, feature_id: str, agent_entry: dict):
    """Incrementally update the telemetry JSON report with a new agent entry
    and recompute pipeline-level aggregations."""
    json_file = outputs_dir / f"{feature_id}_telemetry_report.json"

    # Load existing or create new
    if json_file.exists():
        try:
            report = json.loads(json_file.read_text())
        except (json.JSONDecodeError, OSError) as e:
            log_error(f"Failed to read existing telemetry JSON — starting fresh", e)
            report = {}
    else:
        report = {}

    # Ensure structure
    report.setdefault("feature_id", feature_id)
    report.setdefault("service", OTEL_SERVICE)
    report.setdefault("prometheus_url", PROMETHEUS_URL)
    report.setdefault("cost_rates", MODEL_COST_RATES)
    report.setdefault("agents", [])
    report.setdefault("human_interactions", [])

    # Capture session_id from agent entry if available
    entry_sid = agent_entry.get("session_id", "")
    if entry_sid and not report.get("session_id"):
        report["session_id"] = entry_sid

    if not report.get("pipeline_started_at"):
        report["pipeline_started_at"] = agent_entry.get("start_time", now_utc())

    # Append agent entry
    report["agents"].append(agent_entry)
    report["last_updated"] = now_utc()

    # ── Recompute pipeline-level aggregations ──
    agents = report["agents"]

    # Total duration
    total_duration = sum(a.get("duration_seconds", 0) for a in agents)
    report["pipeline_duration_seconds"] = round(total_duration, 2)
    report["total_agent_execution_seconds"] = round(total_duration, 2)

    human_interactions = report.get("human_interactions", [])
    total_human_wait = sum(i.get("wait_duration_seconds", 0) for i in human_interactions)
    report["human_interaction_count"] = len(human_interactions)
    report["total_human_wait_seconds"] = round(total_human_wait, 2)

    start_dt = parse_iso8601_utc(report.get("pipeline_started_at", ""))
    end_candidates = [parse_iso8601_utc(a.get("end_time", "")) for a in agents]
    end_candidates.extend(parse_iso8601_utc(i.get("end_time", "")) for i in human_interactions)
    end_candidates = [dt for dt in end_candidates if dt is not None]
    if start_dt and end_candidates:
        report["total_wall_clock_seconds"] = round((max(end_candidates) - start_dt).total_seconds(), 2)
    else:
        report["total_wall_clock_seconds"] = round(total_duration + total_human_wait, 2)

    # Duration by agent
    report["duration_by_agent"] = {
        a["agent_name"]: a.get("duration_seconds", 0) for a in agents
    }

    # Token consumption by agent
    tokens_by_agent = {}
    for a in agents:
        t = a.get("tokens", {})
        tokens_by_agent[a["agent_name"]] = {
            "input": t.get("input", 0),
            "output": t.get("output", 0),
            "total": t.get("total", 0),
        }
    report["token_consumption_by_agent"] = tokens_by_agent

    # Token consumption by model (aggregated across agents)
    model_tokens_agg: dict[str, dict[str, float]] = {}
    for a in agents:
        for model, toks in a.get("tokens_by_model", {}).items():
            agg = model_tokens_agg.setdefault(model, {"input": 0, "output": 0, "total": 0})
            agg["input"] += toks.get("input", 0)
            agg["output"] += toks.get("output", 0)
            agg["total"] += toks.get("total", 0)
    report["token_consumption_by_model"] = model_tokens_agg

    # Token consumption by agent and model
    tokens_by_agent_model = {}
    for a in agents:
        tokens_by_agent_model[a["agent_name"]] = a.get("tokens_by_model", {})
    report["token_consumption_by_agent_and_model"] = tokens_by_agent_model

    # Tool call duration overall
    total_tool_dur = sum(a.get("tool_call_duration_total", 0) for a in agents)
    report["tool_call_duration_overall"] = round(total_tool_dur, 2)

    # Tool call duration per agent
    report["tool_call_duration_by_agent"] = {
        a["agent_name"]: a.get("tool_call_duration_total", 0) for a in agents
    }

    # Tool usage count total
    total_tool_usage = sum(a.get("tool_usage_total", 0) for a in agents)
    report["tool_usage_count_total"] = total_tool_usage

    # Tool usage count by agent
    report["tool_usage_count_by_agent"] = {
        a["agent_name"]: a.get("tool_usage", {}) for a in agents
    }

    # Cost by model (aggregated)
    cost_by_model_agg: dict[str, dict[str, float]] = {}
    for a in agents:
        for model, costs in a.get("cost_by_model", {}).items():
            agg = cost_by_model_agg.setdefault(model, {"input_cost": 0, "output_cost": 0, "total_cost": 0})
            agg["input_cost"] += costs.get("input_cost", 0)
            agg["output_cost"] += costs.get("output_cost", 0)
            agg["total_cost"] += costs.get("total_cost", 0)
    # Round aggregated values
    for model in cost_by_model_agg:
        for k in cost_by_model_agg[model]:
            cost_by_model_agg[model][k] = round(cost_by_model_agg[model][k], 6)
    report["cost_by_model"] = cost_by_model_agg

    # Cost by agent
    cost_by_agent = {}
    for a in agents:
        c = a.get("cost", {})
        cost_by_agent[a["agent_name"]] = {
            "input_cost": c.get("input_cost", 0),
            "output_cost": c.get("output_cost", 0),
            "total_cost": c.get("total_cost", 0),
        }
    report["cost_by_agent"] = cost_by_agent

    # Pipeline cost totals
    pipeline_input_cost = sum(c.get("input_cost", 0) for c in cost_by_agent.values())
    pipeline_output_cost = sum(c.get("output_cost", 0) for c in cost_by_agent.values())
    report["pipeline_cost"] = {
        "input_cost": round(pipeline_input_cost, 6),
        "output_cost": round(pipeline_output_cost, 6),
        "total_cost": round(pipeline_input_cost + pipeline_output_cost, 6),
    }

    # Write
    json_file.write_text(json.dumps(report, indent=2))
    log(f"Telemetry JSON updated → {json_file}")


def write_telemetry_entry(
    feature_id: str,
    agent_name: str,
    start_iso: str,
    end_iso: str,
    duration_s: float,
    baseline: dict,
    cwd: str,
    usage_override: dict | None = None,
):
    """Query current metrics, compute deltas from baseline, write MD + JSON report entries."""
    try:
        return _write_telemetry_entry_impl(
            feature_id, agent_name, start_iso, end_iso, duration_s, baseline, cwd, usage_override
        )
    except Exception as e:
        log_error(f"Failed to write telemetry entry for {agent_name}", e)
        return f"⚠️ Telemetry write failed for {agent_name}: {e}"


def _write_telemetry_entry_impl(
    feature_id: str,
    agent_name: str,
    start_iso: str,
    end_iso: str,
    duration_s: float,
    baseline: dict,
    cwd: str,
    usage_override: dict | None = None,
):
    """Internal implementation of write_telemetry_entry."""
    outputs_dir = resolve_outputs_dir(feature_id, cwd)
    telemetry_file = outputs_dir / "telemetry_report.md"
    cost_file = outputs_dir / "cost_report.md"

    stack_available = baseline.get("stack_available", False) and check_stack()

    # ── Build structured JSON entry (source of truth) ──
    agent_entry = build_agent_json_entry(
        agent_name=agent_name,
        start_iso=start_iso,
        end_iso=end_iso,
        duration_s=duration_s,
        baseline=baseline,
        stack_available=stack_available,
    )

    # Primary token source is hook payload usage; Prometheus is fallback.
    if usage_override:
        usage_model = usage_override.get("model", "default")
        input_tokens = float(usage_override.get("input_tokens", 0))
        output_tokens = float(usage_override.get("output_tokens", 0))
        total_tokens = input_tokens + output_tokens

        agent_entry["tokens"] = {
            "input": input_tokens,
            "output": output_tokens,
            "total": total_tokens,
        }
        agent_entry["tokens_by_model"] = {
            usage_model: {
                "input": input_tokens,
                "output": output_tokens,
                "total": total_tokens,
            }
        }

        input_cost = compute_cost(input_tokens, usage_model, "input")
        output_cost = compute_cost(output_tokens, usage_model, "output")
        total_cost = input_cost + output_cost
        agent_entry["cost_by_model"] = {
            usage_model: {
                "input_cost": round(input_cost, 6),
                "output_cost": round(output_cost, 6),
                "total_cost": round(total_cost, 6),
            }
        }
        agent_entry["cost"] = {
            "input_cost": round(input_cost, 6),
            "output_cost": round(output_cost, 6),
            "total_cost": round(total_cost, 6),
        }
    else:
        log(
            "No usage payload in hook event; using Prometheus delta fallback "
            f"(session_id={baseline.get('session_id', '') or 'none'}, "
            f"baseline_in={baseline.get('tokens_input', 'N/A')}, "
            f"baseline_out={baseline.get('tokens_output', 'N/A')}, "
            f"agent={agent_name})"
        )

    # ── Write JSON report ──
    update_telemetry_json(outputs_dir, feature_id, agent_entry)

    # ── Extract values for MD report (from JSON entry) ──
    tokens = agent_entry.get("tokens", {})
    delta_tokens_input = f"{tokens.get('input', 0):,.0f}" if tokens else "N/A"
    delta_tokens_output = f"{tokens.get('output', 0):,.0f}" if tokens else "N/A"
    delta_tool_calls = str(agent_entry.get("tool_usage_total", "N/A"))

    latency = agent_entry.get("latency", {})
    llm_p50 = latency.get("llm_call_p50", "N/A")
    llm_p95 = latency.get("llm_call_p95", "N/A")
    ttft_p50 = latency.get("ttft_p50", "N/A")
    ttft_p95 = latency.get("ttft_p95", "N/A")

    # Tool rows
    tool_usage = agent_entry.get("tool_usage", {})
    tool_rows = "\n".join(f"| {name} | {val} |" for name, val in
                          sorted(tool_usage.items(), key=lambda x: x[1], reverse=True)) if tool_usage else ""

    # Tool duration rows
    tool_dur = agent_entry.get("tool_call_duration_by_tool", {})
    tool_dur_rows = "\n".join(f"| {name} | {val:.2f}s |" for name, val in
                              sorted(tool_dur.items(), key=lambda x: x[1], reverse=True)) if tool_dur else ""

    # Model token rows
    tokens_by_model = agent_entry.get("tokens_by_model", {})
    model_token_rows = "\n".join(
        f"| {model} | {toks['input']:,.0f} | {toks['output']:,.0f} |"
        for model, toks in sorted(tokens_by_model.items())
    ) if tokens_by_model else ""

    # LLM calls rows
    llm_calls = agent_entry.get("llm_calls_by_model", {})
    model_rows = "\n".join(f"| {name} | {val} |" for name, val in
                           sorted(llm_calls.items(), key=lambda x: x[1], reverse=True)) if llm_calls else ""

    # Cost rows
    cost_by_model = agent_entry.get("cost_by_model", {})
    cost_rows = "\n".join(
        f"| {model} | ${c['input_cost']:.4f} | ${c['output_cost']:.4f} | ${c['total_cost']:.4f} |"
        for model, c in sorted(cost_by_model.items())
    ) if cost_by_model else ""
    agent_cost = agent_entry.get("cost", {})

    def fmt_s(v):
        if v == "N/A" or v == "+Inf":
            return "N/A"
        try:
            return f"{float(v):.2f}s"
        except (ValueError, TypeError):
            return v

    # ── Build MD entry ──
    entry = f"""### Agent: {agent_name}

- **Window:** {start_iso} -> {end_iso} ({duration_s:.0f}s)
- **Metrics Source:** Prometheus @ {PROMETHEUS_URL}

#### Latency

| Metric | p50 | p95 |
|-|-|-|
| LLM Call Duration | {fmt_s(llm_p50)} | {fmt_s(llm_p95)} |
| Time to First Token | {fmt_s(ttft_p50)} | {fmt_s(ttft_p95)} |

#### Token Usage (delta for this agent run)

| Type | Count |
|-|-|
| Input Tokens (Δ) | {delta_tokens_input} |
| Output Tokens (Δ) | {delta_tokens_output} |

#### Token Usage by Model (Δ for this agent run)

| Model | Input Tokens (Δ) | Output Tokens (Δ) |
|-|-|-|
{model_token_rows if model_token_rows else "| (no data) | — | — |"}

#### Tool Calls (Δ {delta_tool_calls})

| Tool | Invocations |
|-|-|
{tool_rows if tool_rows else "| (no data) | — |"}

#### Tool Call Duration (Δ {fmt_s(agent_entry.get('tool_call_duration_total', 'N/A'))})

| Tool | Duration |
|-|-|
{tool_dur_rows if tool_dur_rows else "| (no data) | — |"}

#### LLM Calls by Model

| Model | Calls |
|-|-|
{model_rows if model_rows else "| (no data) | — |"}

#### Cost Estimate

| Model | Input Cost | Output Cost | Total Cost |
|-|-|-|-|
{cost_rows if cost_rows else "| (no data) | — | — | — |"}
| **Agent Total** | **${agent_cost.get('input_cost', 0):.4f}** | **${agent_cost.get('output_cost', 0):.4f}** | **${agent_cost.get('total_cost', 0):.4f}** |

---
"""

    # Write header if new file
    if not telemetry_file.exists():
        header = f"""# OpenTelemetry Telemetry Report

Auto-generated by VS Code agent hooks during the orchestrator pipeline.

- **Feature ID:** {feature_id}
- **Service:** {OTEL_SERVICE}
- **Prometheus:** {PROMETHEUS_URL}

---

"""
        telemetry_file.write_text(header, encoding="utf-8")

    with open(telemetry_file, "a", encoding="utf-8") as f:
        f.write(entry)

    log(f"Telemetry appended -> {telemetry_file}")

    if not cost_file.exists():
        cost_file.write_text(
            "# Cost Report\n\n"
            "Auto-generated by otel-hook.py from per-agent usage.\n\n"
            f"- Feature ID: {feature_id}\n"
            f"- Service: {OTEL_SERVICE}\n\n"
        )

    total_tokens_value = tokens.get("total", 0) if isinstance(tokens, dict) else 0
    try:
        total_tokens_int = int(float(total_tokens_value))
    except (TypeError, ValueError):
        total_tokens_int = 0

    summary_model = "default"
    if cost_by_model:
        summary_model = max(cost_by_model.items(), key=lambda item: item[1].get("total_cost", 0))[0]
    elif usage_override:
        summary_model = str(usage_override.get("model", "default"))

    with open(cost_file, "a", encoding="utf-8") as cf:
        cf.write(
            f"## Agent: {agent_name}\n"
            f"- Window: {start_iso} -> {end_iso} ({duration_s:.0f}s)\n"
            f"- Model: {summary_model}\n"
            f"- Tokens: {total_tokens_int:,}\n"
            f"- Cost: ${agent_cost.get('total_cost', 0):.4f}\n\n"
        )

    log(f"Cost report appended -> {cost_file}")

    return (
        f"[TELEMETRY] Agent: {agent_name} | "
        f"Model: {summary_model} | "
        f"Tokens: {total_tokens_int:,} | "
        f"Cost: ${agent_cost.get('total_cost', 0):.4f} | "
        f"Time: {duration_s:.0f}s"
    )


def _safe_read_text(path: Path) -> str:
    try:
        if path.exists():
            return path.read_text(encoding="utf-8")
    except OSError:
        return ""
    return ""


def _sum_report_tokens(report: dict) -> int:
    total = 0.0
    token_by_model = report.get("token_consumption_by_model", {})
    if isinstance(token_by_model, dict):
        for values in token_by_model.values():
            if isinstance(values, dict):
                try:
                    total += float(values.get("total", 0))
                except (TypeError, ValueError):
                    continue
    return int(total)


def finalize_stop_reports(feature_id: str | None, cwd: str) -> str:
    """Ensure telemetry and cost reports have a final summary at Stop."""
    resolved_feature_id = feature_id if _is_valid_feature_id(feature_id or "") else find_feature_id(cwd)
    if not resolved_feature_id:
        return "No feature_id available for finalization"

    outputs_dir = resolve_outputs_dir(resolved_feature_id, cwd)
    telemetry_file = outputs_dir / "telemetry_report.md"
    cost_file = outputs_dir / "cost_report.md"
    json_file = outputs_dir / f"{resolved_feature_id}_telemetry_report.json"

    report: dict = {}
    if json_file.exists():
        try:
            report = json.loads(json_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            report = {}

    agents = report.get("agents", []) if isinstance(report, dict) else []
    pipeline_cost = report.get("pipeline_cost", {}) if isinstance(report, dict) else {}
    total_cost = float(pipeline_cost.get("total_cost", 0) or 0)
    total_tokens = _sum_report_tokens(report)
    agent_count = len(agents) if isinstance(agents, list) else 0

    telemetry_marker = "<!-- OTel Stop Final Summary -->"
    cost_marker = "<!-- OTel Stop Cost Summary -->"

    telemetry_content = _safe_read_text(telemetry_file)
    if telemetry_marker not in telemetry_content:
        if not telemetry_content:
            telemetry_file.write_text(
                "# OpenTelemetry Telemetry Report\n\n"
                "Auto-generated by VS Code agent hooks during the orchestrator pipeline.\n\n"
                f"- Feature ID: {resolved_feature_id}\n"
                f"- Service: {OTEL_SERVICE}\n"
                f"- Prometheus: {PROMETHEUS_URL}\n\n"
                "---\n",
                encoding="utf-8",
            )
        with open(telemetry_file, "a", encoding="utf-8") as tf:
            tf.write(
                "\n## Final Summary (Stop)\n"
                f"{telemetry_marker}\n"
                f"- Feature ID: {resolved_feature_id}\n"
                f"- Agent runs captured: {agent_count}\n"
                f"- Total tokens: {total_tokens:,}\n"
                f"- Total estimated cost: ${total_cost:.4f}\n"
                f"- Finalized at: {now_utc()}\n"
            )

    cost_content = _safe_read_text(cost_file)
    if cost_marker not in cost_content:
        if not cost_content:
            cost_file.write_text(
                "# Cost Report\n\n"
                "Auto-generated by otel-hook.py from per-agent usage.\n\n"
                f"- Feature ID: {resolved_feature_id}\n"
                f"- Service: {OTEL_SERVICE}\n\n",
                encoding="utf-8",
            )
        with open(cost_file, "a", encoding="utf-8") as cf:
            cf.write(
                "\n## Final Summary (Stop)\n"
                f"{cost_marker}\n"
                f"- Feature ID: {resolved_feature_id}\n"
                f"- Agent runs captured: {agent_count}\n"
                f"- Total tokens: {total_tokens:,}\n"
                f"- Total estimated cost: ${total_cost:.4f}\n"
                f"- Finalized at: {now_utc()}\n"
            )

    return (
        f"Finalized reports for {resolved_feature_id} "
        f"(agents={agent_count}, tokens={total_tokens:,}, cost=${total_cost:.4f})"
    )


# ─── Hook Event Handlers ────────────────────────────────────────────────────

def handle_pre_tool_use(hook_input: dict) -> dict:
    """PreToolUse: capture baseline when runSubagent tool is about to be called.

    This is the primary mechanism for subagent telemetry since SubagentStart/
    SubagentStop events are not reliably fired for tool-based subagent spawning.
    We detect `tool_name == "runSubagent"` and extract the agent name from
    `tool_input.agentName`.
    """
    try:
        event_name = "PreToolUse"
        tool_name = get_field(hook_input, "tool_name", "toolName")
        log(f"PreToolUse: tool_name={tool_name}")
        if tool_name in ("vscode/askQuestions", "vscode_askQuestions"):
            tool_use_id = get_field(hook_input, "tool_use_id", "toolUseId")
            cwd = get_field(hook_input, "cwd", default=os.getcwd())
            feature_id = _extract_feature_id_from_payload(hook_input, {}, cwd)
            if feature_id and tool_use_id:
                save_state(f"ask_{tool_use_id}", {
                    "feature_id": feature_id,
                    "tool_use_id": tool_use_id,
                    "start_time": now_utc(),
                })
                log(f"Human wait baseline captured: tool_use_id={tool_use_id}, feature={feature_id}")
            return hook_response(event_name, "[OTel] Human wait baseline captured")

        if not _is_agent_tool(tool_name):
            return hook_response(event_name, f"[OTel] Ignored tool '{tool_name}'")

        tool_input = get_field(hook_input, "tool_input", "toolInput", default={})
        if isinstance(tool_input, str):
            try:
                tool_input = json.loads(tool_input)
            except (json.JSONDecodeError, TypeError):
                tool_input = {}
        agent_name = get_field(tool_input, "agentName", "agent_name", "agent")
        tool_use_id = get_field(hook_input, "tool_use_id", "toolUseId")
        cwd = get_field(hook_input, "cwd", default=os.getcwd())
        hook_session_id = get_field(hook_input, "session_id", "sessionId")

        log(f"PreToolUse/runSubagent: agent={agent_name}, tool_use_id={tool_use_id}")

        if not agent_name:
            log("WARNING: empty agent_name — capturing baseline anyway for correlation")

        feature_id = _extract_feature_id_from_payload(hook_input, tool_input, cwd)
        baseline = capture_baseline()
        baseline["agent_type"] = agent_name
        baseline["agent_name"] = agent_name
        baseline["tool_use_id"] = tool_use_id
        baseline["hook_session_id"] = hook_session_id
        baseline["feature_id"] = feature_id
        baseline["cwd"] = cwd

        # Key state by tool_use_id for Pre/Post correlation
        save_state(f"tooluse_{tool_use_id}", baseline)

        stack_status = "connected" if baseline.get("stack_available") else "unavailable"
        discovery_warning = baseline.get("discovery_warning", "")
        extra = f" | warning={discovery_warning}" if discovery_warning else ""
        log(f"Baseline captured (stack: {stack_status}, feature: {feature_id}{extra})")

        if not baseline.get("stack_available"):
            message = "Prometheus stack unavailable during baseline capture; telemetry deltas may be missing."
            record_failure(event_name, message, {"feature_id": feature_id, "tool_use_id": tool_use_id})
            return hook_response(
                event_name,
                f"[OTel][FAILED] {message} Check {LOG_DIR / 'otel-hook.log'}.",
            )

        clear_failure_marker("PreToolUse baseline captured")

        return hook_response(event_name, "[OTel] Baseline captured")

    except Exception as e:
        log_error("FATAL: PreToolUse handler crashed — continuing without telemetry", e)
        record_failure("PreToolUse", f"Handler crashed: {e}")
        return hook_response(
            "PreToolUse",
            f"[OTel][FAILED] Hook crashed in PreToolUse: {e}. Check {LOG_DIR / 'otel-hook.log'}.",
        )


def handle_post_tool_use(hook_input: dict) -> dict:
    """PostToolUse: compute metrics delta when runSubagent tool completes.

    Correlates with the PreToolUse baseline using `tool_use_id`.
    """
    try:
        event_name = "PostToolUse"
        tool_name = get_field(hook_input, "tool_name", "toolName")
        log(f"PostToolUse: tool_name={tool_name}")
        if tool_name in ("vscode/askQuestions", "vscode_askQuestions"):
            tool_use_id = get_field(hook_input, "tool_use_id", "toolUseId")
            cwd = get_field(hook_input, "cwd", default=os.getcwd())
            ask_state = load_state(f"ask_{tool_use_id}")
            if not ask_state:
                log(f"No human wait baseline for tool_use_id={tool_use_id}")
                return hook_response(event_name, "[OTel] No human wait baseline found")

            start_iso = ask_state.get("start_time", now_utc())
            end_iso = now_utc()
            start_dt = parse_iso8601_utc(start_iso)
            end_dt = parse_iso8601_utc(end_iso)
            wait_duration = 0.0
            if start_dt and end_dt and end_dt >= start_dt:
                wait_duration = (end_dt - start_dt).total_seconds()

            feature_id = ask_state.get("feature_id") or _extract_feature_id_from_payload(hook_input, {}, cwd)
            if not feature_id:
                log("WARNING: Could not determine feature_id for human wait telemetry")
                return {"continue": True}

            outputs_dir = resolve_outputs_dir(feature_id, cwd)
            interaction_entry = {
                "sequence": int(time.time() * 1000),
                "tool_name": tool_name,
                "start_time": start_iso,
                "end_time": end_iso,
                "wait_duration_seconds": round(wait_duration, 2),
            }
            update_human_wait_json(outputs_dir, feature_id, interaction_entry)
            log(f"Human wait recorded: tool_use_id={tool_use_id}, wait={wait_duration:.2f}s")
            return hook_response(event_name, "[OTel] Human wait telemetry updated")

        if not _is_agent_tool(tool_name):
            return hook_response(event_name, f"[OTel] Ignored tool '{tool_name}'")

        tool_input = get_field(hook_input, "tool_input", "toolInput", default={})
        if isinstance(tool_input, str):
            try:
                tool_input = json.loads(tool_input)
            except (json.JSONDecodeError, TypeError):
                tool_input = {}
        agent_name = get_field(tool_input, "agentName", "agent_name", "agent")
        tool_use_id = get_field(hook_input, "tool_use_id", "toolUseId")
        cwd = get_field(hook_input, "cwd", default=os.getcwd())
        hook_session_id = get_field(hook_input, "session_id", "sessionId")

        log(f"PostToolUse/runSubagent: agent={agent_name}, tool_use_id={tool_use_id}")

        if not agent_name:
            log("WARNING: empty agent_name in PostToolUse — attempting correlation by tool_use_id")

        baseline = load_state(f"tooluse_{tool_use_id}")
        if not baseline:
            baseline = _load_fallback_tooluse_baseline(tool_use_id, agent_name, hook_session_id)
        if not baseline:
            log(f"WARNING: No baseline found for tool_use_id={tool_use_id} — skipping telemetry")
            record_failure(
                event_name,
                "No baseline found for runSubagent PostToolUse correlation.",
                {"tool_use_id": tool_use_id, "agent_name": agent_name},
            )
            return hook_response(
                event_name,
                (
                    "[OTel][FAILED] No telemetry baseline found for this runSubagent call. "
                    f"Check {LOG_DIR / 'otel-hook.log'}."
                ),
            )

        end_iso = now_utc()
        start_iso = baseline.get("iso", end_iso)
        duration_s = now_epoch() - baseline.get("timestamp", now_epoch())
        feature_id = baseline.get("feature_id") or _extract_feature_id_from_payload(hook_input, tool_input, cwd)

        if not feature_id:
            log("WARNING: Could not determine feature_id — skipping telemetry write")
            record_failure(
                event_name,
                "Could not determine feature_id in PostToolUse.",
                {"tool_use_id": tool_use_id, "agent_name": agent_name},
            )
            return hook_response(
                event_name,
                f"[OTel][FAILED] Could not determine feature_id. Check {LOG_DIR / 'otel-hook.log'}.",
            )

        usage_override = _extract_usage_override(hook_input, tool_input)
        if not usage_override:
            log(
                "PostToolUse usage payload unavailable; Prometheus fallback will be used "
                f"(agent={agent_name}, tool_use_id={tool_use_id}, session_id={baseline.get('session_id', '') or 'none'})"
            )

        summary = write_telemetry_entry(
            feature_id=feature_id,
            agent_name=agent_name,
            start_iso=start_iso,
            end_iso=end_iso,
            duration_s=duration_s,
            baseline=baseline,
            cwd=cwd,
            usage_override=usage_override,
        )

        log(summary)
        if baseline.get("stack_available"):
            clear_failure_marker("PostToolUse telemetry updated")

        return hook_response(event_name, summary)

    except Exception as e:
        log_error("FATAL: PostToolUse handler crashed — continuing without telemetry", e)
        record_failure("PostToolUse", f"Handler crashed: {e}")
        return hook_response(
            "PostToolUse",
            f"[OTel][FAILED] Hook crashed in PostToolUse: {e}. Check {LOG_DIR / 'otel-hook.log'}.",
        )


def handle_session_start(hook_input: dict) -> dict:
    """SessionStart: agent-scoped hook for when an agent starts as a subagent."""
    event_name = "SessionStart"
    try:
        session_id = get_field(hook_input, "sessionId", "session_id")
        cwd = get_field(hook_input, "cwd", default=os.getcwd())

        log(f"SessionStart: session={session_id}")

        feature_id = find_feature_id(cwd)
        baseline = capture_baseline()
        baseline["session_id"] = session_id
        baseline["feature_id"] = feature_id
        baseline["cwd"] = cwd

        save_state(f"session_{session_id}", baseline)
        if baseline.get("stack_available"):
            clear_failure_marker("SessionStart baseline captured")

        return hook_response(event_name, "[OTel] Telemetry baseline recorded for this agent session.")

    except Exception as e:
        log_error("FATAL: SessionStart handler crashed", e)
        record_failure(event_name, f"Handler crashed: {e}")
        return hook_response(
            event_name,
            f"[OTel][FAILED] Hook crashed in SessionStart: {e}. Check {LOG_DIR / 'otel-hook.log'}.",
        )


def handle_stop(hook_input: dict) -> dict:
    """Stop: agent-scoped hook for when an agent completes as a subagent."""
    event_name = "Stop"
    try:
        session_id = get_field(hook_input, "sessionId", "session_id")
        cwd = get_field(hook_input, "cwd", default=os.getcwd())
        feature_id = _extract_feature_id_from_payload(hook_input, {}, cwd)

        log(f"Stop: session={session_id}")

        baseline = load_state(f"session_{session_id}")
        if baseline and not feature_id:
            feature_id = baseline.get("feature_id")

        finalization_summary = finalize_stop_reports(feature_id, cwd)
        log(finalization_summary)

        if not baseline:
            log(f"No session baseline for {session_id} — likely handled by PostToolUse")
            return hook_response(event_name, f"[OTel] Stop finalized. {finalization_summary}")

        # Don't double-write if PostToolUse already handled this
        log("Session stop — deferring to PostToolUse hook")
        clear_failure_marker("Stop processed")
        return hook_response(event_name, f"[OTel] Stop processed. {finalization_summary}")

    except Exception as e:
        log_error("FATAL: Stop handler crashed", e)
        record_failure(event_name, f"Handler crashed: {e}")
        return hook_response(
            event_name,
            f"[OTel][FAILED] Hook crashed in Stop: {e}. Check {LOG_DIR / 'otel-hook.log'}.",
        )


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    global MODEL_COST_RATES

    # Initialize persistent file logger (rotate old logs, keep MAX_LOG_RUNS)
    try:
        _init_file_logger()
    except Exception as e:
        # File logging is best-effort — don't block the hook
        print(f"[otel-hook] WARNING: File logger init failed: {e}", file=sys.stderr)

    # Load pricing once per hook process so all cost calculations use the same table.
    if not MODEL_COST_RATES:
        MODEL_COST_RATES = load_model_cost_rates()

    try:
        raw_input = sys.stdin.read()
        hook_input = json.loads(raw_input) if raw_input.strip() else {}
    except json.JSONDecodeError as e:
        log_error("Failed to parse hook input", e)
        record_failure("Unknown", f"Failed to parse hook input: {e}")
        print(json.dumps({"continue": True}))
        return

    event = get_field(hook_input, "hookEventName", "hook_event_name", "event", "eventName")
    log(f"Event: {event}")

    handlers = {
        "PreToolUse": handle_pre_tool_use,
        "PostToolUse": handle_post_tool_use,
        "SessionStart": handle_session_start,
        "Stop": handle_stop,
    }

    handler = handlers.get(event)
    if handler:
        try:
            result = handler(hook_input)
        except Exception as e:
            # Top-level safety net — ensure hooks NEVER block VS Code
            log_error(f"FATAL: Unhandled exception in {event} handler", e)
            record_failure(event or "Unknown", f"Unhandled exception: {e}")
            result = hook_response(
                event or "Unknown",
                f"[OTel][FAILED] Unhandled hook exception: {e}. Check {LOG_DIR / 'otel-hook.log'}.",
            )
    else:
        log(f"Unknown event: {event}")
        result = hook_response(event or "Unknown", "[OTel] Unsupported event; no action taken")

    if result.get("continue") is True and not isinstance(result.get("hookSpecificOutput"), dict):
        result = hook_response(event or "Unknown", "[OTel] Hook completed")

    print(json.dumps(result))

    # Close file logger
    if _log_file:
        try:
            _log_file.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
