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
SCRIPT_DIR = Path(__file__).resolve().parent
OBSERVABILITY_DIR = SCRIPT_DIR.parent / "observability"
COST_PRECISION = 12
OTEL_DIAGNOSTIC_LOGGING = os.environ.get("OTEL_DIAGNOSTIC_LOGGING", "1").strip() not in ("0", "false", "False")

# IST timezone for log timestamps
IST = timezone(timedelta(hours=5, minutes=30))

# Cost rates per 1M tokens (USD).
# These defaults can be overridden from external pricing sources (URL/file/env JSON).
DEFAULT_MODEL_COST_RATES = {
    "claude-opus-4.6": {"input": 5.00, "cached_input": 5.00, "output": 25.00},
    "claude-sonnet-4": {"input": 3.00, "cached_input": 3.00, "output": 15.00},
    "gpt-5.2": {"input": 1.75, "cached_input": 1.75, "output": 14.00},
    # Baseline default for the new pipeline model. Override via pricing source when needed.
    "gpt-5.3-codex": {"input": 1.75, "cached_input": 1.75, "output": 14.00},
    # Non-zero fallback defaults prevent silent $0 totals when external pricing is unavailable.
    "gpt-4.1": {"input": 0.15, "cached_input": 0.15, "output": 0.60},
    "gpt-4o-mini": {"input": 0.15, "cached_input": 0.15, "output": 0.60},
    "gpt-4o-mini-2024-07-18": {"input": 0.15, "cached_input": 0.15, "output": 0.60},
    "copilot-nes-oct": {"input": 0.15, "cached_input": 0.15, "output": 0.60},
    "copilot-suggestions-himalia-001": {"input": 0.15, "cached_input": 0.15, "output": 0.60},
}

# Optional pricing source configuration (first non-empty source wins and merges over defaults).
# JSON format for all sources: {"model-name": {"input": <usd_per_1m>, "output": <usd_per_1m>}, ...}
# URL/file can also wrap this map inside a "models" key.
MODEL_PRICING_URL = os.environ.get("OTEL_MODEL_PRICING_URL", "").strip()
MODEL_PRICING_FILE = os.environ.get(
    "OTEL_MODEL_PRICING_FILE",
    str(OBSERVABILITY_DIR / "model-pricing.json"),
).strip()
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
    str(OBSERVABILITY_DIR / ".hook-state")
))

# Log directory for persistent otel-hook logs
LOG_DIR = OBSERVABILITY_DIR / ".logs"
HOOK_FAILURE_FILE = STATE_DIR / "otel_hook_last_failure.json"
HOOK_FAILURE_EVENTS_FILE = STATE_DIR / "hook_failures.ndjson"

# Maximum number of otel-hook log files to retain.
# Keep enough history to trace SessionStart → baseline → PreToolUse → PostToolUse → Stop.
MAX_LOG_RUNS = int(os.environ.get("OTEL_HOOK_LOG_RETENTION", "8"))

# Rotate only when the active log reaches this size (bytes).
MAX_LOG_SIZE_BYTES = int(os.environ.get("OTEL_HOOK_LOG_MAX_BYTES", str(64 * 1024)))

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


def normalize_feature_id(value: str) -> str:
    """Return a canonical feature id used for paths and JSON keys."""
    candidate = str(value or "").strip()
    while candidate.endswith("."):
        candidate = candidate[:-1].rstrip()
    return candidate


def _is_valid_feature_id(value: str) -> bool:
    candidate = normalize_feature_id(value)
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


def _looks_like_usage_dict(value: dict) -> bool:
    return isinstance(value, dict) and any(
        key in value
        for key in (
            "input_tokens",
            "inputTokens",
            "prompt_tokens",
            "promptTokens",
            "output_tokens",
            "outputTokens",
            "completion_tokens",
            "completionTokens",
            "total_tokens",
            "totalTokens",
            "cached_input_tokens",
            "cachedInputTokens",
            "cached_tokens",
            "cachedTokens",
        )
    )


def _iter_dicts_recursive(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _iter_dicts_recursive(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_dicts_recursive(child)


def _extract_usage_dict_from_object(value: object) -> dict:
    for node in _iter_dicts_recursive(value):
        usage = _to_dict(get_field(node, "usage", default={}))
        if _looks_like_usage_dict(usage):
            return usage
        if _looks_like_usage_dict(node):
            return node
    return {}


def _tool_use_id_variants(tool_use_id: str) -> list[str]:
    raw = str(tool_use_id or "").strip()
    if not raw:
        return []
    variants = [raw]
    if "__" in raw:
        variants.append(raw.split("__", 1)[0])
    return [v for v in variants if v]


def _raw_token_usage_from_text(raw: str) -> dict:
    if not raw:
        return {}

    patterns = {
        "input_tokens": [
            r"Input\s*tokens\s*[:=]\s*(\d+)",
            r'"inputTokens"\s*:\s*(\d+)',
            r'"input_tokens"\s*:\s*(\d+)',
        ],
        "cached_input_tokens": [
            r"Cached\s*tokens\s*[:=]\s*(\d+)",
            r'"cachedTokens"\s*:\s*(\d+)',
            r'"cached_input_tokens"\s*:\s*(\d+)',
            r'"cachedInputTokens"\s*:\s*(\d+)',
        ],
        "output_tokens": [
            r"Output\s*tokens\s*[:=]\s*(\d+)",
            r'"outputTokens"\s*:\s*(\d+)',
            r'"output_tokens"\s*:\s*(\d+)',
        ],
    }

    result = {}
    for key, regexes in patterns.items():
        for rgx in regexes:
            m = re.search(rgx, raw)
            if m:
                result[key] = _to_int(m.group(1))
                break

    if result:
        return result
    return {}


def _extract_child_session_id(value: object) -> str:
    """Extract a child VS Code session id from an arbitrary JSON object."""
    possible_keys = (
        "childSessionId",
        "child_session_id",
        "childSessionRef",
        "child_session_ref",
        "childSession",
        "child_session",
        "subagentSessionId",
        "subagent_session_id",
    )

    for node in _iter_dicts_recursive(value):
        for key in possible_keys:
            if key not in node:
                continue

            candidate = node.get(key)
            if isinstance(candidate, dict):
                candidate = (
                    candidate.get("sessionId")
                    or candidate.get("session_id")
                    or candidate.get("id")
                    or candidate.get("value")
                )

            if candidate:
                return str(candidate).strip()

    return ""


def _extract_model_from_object(value: object) -> str:
    """Extract a model name from an arbitrary JSON object."""
    model_keys = (
        "model",
        "model_name",
        "modelName",
        "gen_ai_request_model",
    )

    for node in _iter_dicts_recursive(value):
        for key in model_keys:
            candidate = node.get(key)
            if candidate:
                if isinstance(candidate, dict):
                    candidate = (
                        candidate.get("name")
                        or candidate.get("id")
                        or candidate.get("model")
                    )
                if candidate:
                    return str(candidate).strip()

    return ""


def _is_llm_request_record(value: object, raw: str = "") -> bool:
    """Return True when a JSON object/text represents an llm_request record."""
    if isinstance(value, dict):
        for node in _iter_dicts_recursive(value):
            for key in ("event", "eventName", "event_name", "type", "kind", "name", "operation"):
                candidate = str(node.get(key, "")).strip().lower()
                if candidate == "llm_request" or "llm_request" in candidate:
                    return True

    return "llm_request" in str(raw or "").lower()


def _extract_usage_from_jsonl_file(
    jsonl_path: Path,
    tool_use_id: str,
    session_id: str = "",
) -> tuple[str, dict, str]:
    """
    Correlate a runSubagent tool call to its child-session log and extract
    token usage from that child session's llm_request records.

    VS Code's debug main.jsonl normally contains a child_session_ref record
    such as:

        attrs.childSessionId = call_...
        attrs.childLogFile = runSubagent-...-call_....jsonl

    The actual llm_request records are then written to that child log file,
    not necessarily to the same main.jsonl line as the runSubagent call.
    """
    if not jsonl_path.exists() or not jsonl_path.is_file():
        return ("", {}, "")

    tool_use_id = str(tool_use_id or "").strip()
    session_id = str(session_id or "").strip()
    variants = _tool_use_id_variants(tool_use_id)
    if not variants:
        return ("", {}, "")

    try:
        raw_lines = jsonl_path.read_text(
            encoding="utf-8",
            errors="ignore",
        ).splitlines()
    except OSError as e:
        log(f"Usage correlation: failed to read {jsonl_path}: {e}")
        return ("", {}, "")

    scan_start = max(len(raw_lines) - 6000, 0)
    scanned = raw_lines[scan_start:]

    # The tool_use_id has a runtime suffix after "__". The child-session
    # reference normally uses the base id, so search for both variants.
    base_tool_use_id = variants[0].split("__", 1)[0]

    child_session_id = ""
    child_log_file = ""
    child_ref_line = None
    runsubagent_line = None

    # ---------------------------------------------------------------
    # 1. Find the child_session_ref created for this runSubagent call.
    # ---------------------------------------------------------------
    for offset, raw in enumerate(scanned):
        if base_tool_use_id not in raw and not any(v in raw for v in variants):
            continue

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None

        raw_lower = raw.lower()
        is_child_ref = (
            "child_session_ref" in raw_lower
            or "child-session-ref" in raw_lower
            or "childsessionref" in raw_lower
        )

        if parsed is not None:
            candidate_child = _extract_child_session_id(parsed)
            if candidate_child:
                child_session_id = candidate_child

            for node in _iter_dicts_recursive(parsed):
                value = node.get("childLogFile") or node.get("child_log_file")
                if value:
                    child_log_file = str(value).strip()
                    break

        if is_child_ref and (child_session_id or child_log_file):
            child_ref_line = scan_start + offset
            break

        # A generic runSubagent/tool record may still be useful as a marker.
        if runsubagent_line is None:
            runsubagent_line = scan_start + offset

    # ---------------------------------------------------------------
    # 2. If the child ref wasn't found by the tool id, scan child_session_ref
    #    records and match childSessionId against the base id.
    # ---------------------------------------------------------------
    if not child_session_id or not child_log_file:
        for offset, raw in enumerate(scanned):
            if "child_session_ref" not in raw.lower() and "childsessionref" not in raw.lower():
                continue

            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                continue

            candidate_child = _extract_child_session_id(parsed)
            candidate_log = ""
            for node in _iter_dicts_recursive(parsed):
                value = node.get("childLogFile") or node.get("child_log_file")
                if value:
                    candidate_log = str(value).strip()
                    break

            # childSessionId is normally exactly the base runSubagent id.
            if candidate_child == base_tool_use_id:
                child_session_id = candidate_child
                child_log_file = candidate_log or child_log_file
                child_ref_line = scan_start + offset
                break

            # Some records expose the id in spanId/child-ref-call_<id>.
            raw_compact = raw.replace(" ", "")
            if base_tool_use_id and base_tool_use_id in raw_compact:
                child_session_id = candidate_child or child_session_id
                child_log_file = candidate_log or child_log_file
                child_ref_line = scan_start + offset
                break

    log(
        "Usage correlation: "
        f"tool_use_id={tool_use_id}, "
        f"base_tool_use_id={base_tool_use_id}, "
        f"child_session_id={child_session_id or 'none'}, "
        f"child_log_file={child_log_file or 'none'}, "
        f"child_ref_line={child_ref_line if child_ref_line is not None else 'none'}"
    )

    # ---------------------------------------------------------------
    # 3. Prefer the dedicated child log. It is the strongest correlation
    #    boundary because every llm_request in it belongs to this subagent.
    # ---------------------------------------------------------------
    child_log_candidates: list[Path] = []
    if child_log_file:
        child_log_path = Path(child_log_file)
        if not child_log_path.is_absolute():
            child_log_path = jsonl_path.parent / child_log_path
        child_log_candidates.append(child_log_path)

    # If childLogFile wasn't exposed, try the conventional VS Code naming
    # pattern in the same debug-log directory.
    if child_session_id:
        for candidate in jsonl_path.parent.glob("*.jsonl"):
            if candidate.name == jsonl_path.name:
                continue
            if child_session_id in candidate.name:
                child_log_candidates.append(candidate)

    # De-duplicate child-log candidates.
    seen_child_logs = set()
    unique_child_logs: list[Path] = []
    for candidate in child_log_candidates:
        key = str(candidate.resolve())
        if key in seen_child_logs:
            continue
        seen_child_logs.add(key)
        unique_child_logs.append(candidate)

    def collect_usage_from_log(log_path: Path) -> tuple[dict, list[tuple]]:
        """Read a child log and return aggregated usage plus individual records."""
        if not log_path.exists() or not log_path.is_file():
            return ({}, [])

        try:
            lines = log_path.read_text(
                encoding="utf-8",
                errors="ignore",
            ).splitlines()
        except OSError as e:
            log(f"Usage correlation: failed to read child log {log_path}: {e}")
            return ({}, [])

        records = []
        model_totals: dict[str, dict[str, int]] = {}

        for line_number, raw in enumerate(lines, start=1):
            if "llm_request" not in raw.lower():
                continue

            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = None

            if parsed is not None and not _is_llm_request_record(parsed, raw):
                continue

            usage = _extract_usage_dict_from_object(parsed) if parsed is not None else {}
            if not usage:
                usage = _raw_token_usage_from_text(raw)
            if not usage:
                continue

            input_tokens = _to_int(
                get_field(
                    usage,
                    "input_tokens",
                    "inputTokens",
                    "prompt_tokens",
                    "promptTokens",
                    default=0,
                )
            )
            output_tokens = _to_int(
                get_field(
                    usage,
                    "output_tokens",
                    "outputTokens",
                    "completion_tokens",
                    "completionTokens",
                    default=0,
                )
            )
            cached_tokens = _extract_cached_tokens_from_usage(usage)

            total_tokens = _to_int(
                get_field(usage, "total_tokens", "totalTokens", default=0)
            )
            if total_tokens > 0 and input_tokens <= 0 and output_tokens <= 0:
                input_tokens = max(total_tokens - output_tokens, 0)

            if input_tokens <= 0 and output_tokens <= 0:
                continue

            model = _extract_model_from_object(parsed) if parsed is not None else ""
            if not model:
                model = str(get_field(usage, "model", default="") or "").strip()
            model = model or "default"

            records.append(
                (
                    line_number,
                    input_tokens,
                    cached_tokens,
                    output_tokens,
                    model,
                )
            )

            bucket = model_totals.setdefault(
                model,
                {"input": 0, "cached": 0, "output": 0},
            )
            bucket["input"] += input_tokens
            bucket["cached"] += cached_tokens
            bucket["output"] += output_tokens

        return (model_totals, records)

    selected_log = None
    model_totals: dict[str, dict[str, int]] = {}
    usage_records: list[tuple] = []

    for candidate in unique_child_logs:
        model_totals, usage_records = collect_usage_from_log(candidate)
        if usage_records:
            selected_log = candidate
            break

    # ---------------------------------------------------------------
    # 4. Last-resort fallback: inspect main.jsonl only when the dedicated
    #    child log is unavailable. In this fallback, use llm_request records
    #    after the child_session_ref and before the next child_session_ref.
    #    This is deliberately bounded to avoid attributing unrelated agents.
    # ---------------------------------------------------------------
    if not usage_records:
        start_offset = (
            max(child_ref_line - scan_start, 0) + 1
            if child_ref_line is not None
            else 0
        )
        end_offset = len(scanned)

        if child_ref_line is not None:
            for offset in range(start_offset, len(scanned)):
                raw = scanned[offset]
                if offset == start_offset:
                    continue
                if "child_session_ref" in raw.lower() or "childsessionref" in raw.lower():
                    end_offset = offset
                    break

        fallback_lines = scanned[start_offset:end_offset]
        fallback_models: dict[str, dict[str, int]] = {}

        for offset, raw in enumerate(fallback_lines, start=start_offset):
            if "llm_request" not in raw.lower():
                continue

            # A child session id in the llm_request is an even stronger match
            # when a provider includes it directly.
            if child_session_id and child_session_id in raw:
                pass
            elif not child_session_id and not any(v in raw for v in variants):
                continue

            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = None

            usage = _extract_usage_dict_from_object(parsed) if parsed is not None else {}
            if not usage:
                usage = _raw_token_usage_from_text(raw)
            if not usage:
                continue

            input_tokens = _to_int(
                get_field(usage, "input_tokens", "inputTokens", "prompt_tokens", "promptTokens", default=0)
            )
            output_tokens = _to_int(
                get_field(usage, "output_tokens", "outputTokens", "completion_tokens", "completionTokens", default=0)
            )
            cached_tokens = _extract_cached_tokens_from_usage(usage)

            if input_tokens <= 0 and output_tokens <= 0:
                continue

            model = _extract_model_from_object(parsed) if parsed is not None else ""
            model = model or str(get_field(usage, "model", default="") or "").strip() or "default"

            usage_records.append((scan_start + offset, input_tokens, cached_tokens, output_tokens, model))
            bucket = fallback_models.setdefault(model, {"input": 0, "cached": 0, "output": 0})
            bucket["input"] += input_tokens
            bucket["cached"] += cached_tokens
            bucket["output"] += output_tokens

        if usage_records:
            model_totals = fallback_models
            selected_log = jsonl_path

    if not usage_records:
        log(
            "Usage correlation: no matching llm_request records found "
            f"for tool_use_id={tool_use_id}, child_session_id={child_session_id or 'none'}"
        )
        return ("", {}, "")

    # ---------------------------------------------------------------
    # 5. Aggregate usage and select the model with the largest token volume.
    #    Normal runSubagent executions use one model; this also remains
    #    deterministic if a log contains multiple model records.
    # ---------------------------------------------------------------
    total_input = sum(r[1] for r in usage_records)
    total_cached = sum(r[2] for r in usage_records)
    total_output = sum(r[3] for r in usage_records)

    selected_model = max(
        model_totals.items(),
        key=lambda item: (
            item[1]["input"] + item[1]["output"],
            item[0],
        ),
    )[0]

    if len(model_totals) > 1:
        log(
            "WARNING: Multiple models found in child usage log; "
            f"aggregating tokens under dominant model={selected_model}. "
            f"models={list(model_totals.keys())}"
        )

    result = {
        "model": selected_model,
        "inputTokens": total_input,
        "cachedTokens": total_cached,
        "outputTokens": total_output,
    }

    match_identifier = (
        f"tool_use_id={tool_use_id},"
        f"child_session_id={child_session_id or 'none'},"
        f"child_log={selected_log.name if selected_log else 'none'},"
        f"llm_request_count={len(usage_records)}"
    )

    log(
        "Usage correlation SUCCESS: "
        f"tool_use_id={tool_use_id}, "
        f"child_session_id={child_session_id or 'none'}, "
        f"child_log={selected_log or 'none'}, "
        f"llm_requests={len(usage_records)}, "
        f"input={total_input}, cached={total_cached}, output={total_output}, "
        f"selected_model={selected_model}"
    )

    return (
        f"{selected_log or jsonl_path}#llm_request",
        result,
        match_identifier,
    )


def _lookup_usage_from_copilot_artifacts(hook_input: dict, tool_input: dict) -> tuple[str, dict, str]:
    tool_use_id = str(get_field(hook_input, "tool_use_id", "toolUseId", default="") or "").strip()
    session_id = str(get_field(hook_input, "session_id", "sessionId", default="") or "").strip()
    transcript_path_raw = str(get_field(hook_input, "transcript_path", "transcriptPath", default="") or "").strip()
    if not tool_use_id:
        return ("", {}, "")

    candidates: list[Path] = []

    if transcript_path_raw:
        transcript_path = Path(transcript_path_raw)
        candidates.append(transcript_path)

        transcript_str = str(transcript_path)
        m = re.search(r"[\\/]transcripts[\\/]([^\\/]+)\.jsonl$", transcript_str)
        if m:
            sid = m.group(1)
            debug_str = re.sub(r"[\\/]transcripts[\\/][^\\/]+\.jsonl$", "", transcript_str)
            debug_path = Path(debug_str) / "debug-logs" / sid / "main.jsonl"
            candidates.append(debug_path)

    target_debug = os.environ.get("VSCODE_TARGET_SESSION_LOG", "").strip()
    if target_debug:
        candidates.append(Path(target_debug) / "main.jsonl")

    seen = set()
    unique_candidates = []
    for candidate in candidates:
        resolved = str(candidate)
        if resolved in seen:
            continue
        seen.add(resolved)
        unique_candidates.append(candidate)

    for candidate in unique_candidates:
        source, usage, match_identifier = _extract_usage_from_jsonl_file(candidate, tool_use_id, session_id)
        if usage:
            return (source, usage, match_identifier)

    return ("", {}, "")


def _extract_cached_tokens_from_usage(usage: dict) -> int:
    direct = _to_int(
        get_field(
            usage,
            "cached_input_tokens",
            "cachedInputTokens",
            "cached_tokens",
            "cachedTokens",
            "cache_input_tokens",
            "cacheInputTokens",
            "input_cached_tokens",
            "inputCachedTokens",
            default=0,
        )
    )
    if direct > 0:
        return direct

    prompt_details = _to_dict(get_field(usage, "prompt_tokens_details", "promptTokensDetails", default={}))
    return _to_int(
        get_field(
            prompt_details,
            "cached_tokens",
            "cachedTokens",
            "cache_tokens",
            "cacheTokens",
            default=0,
        )
    )


def _extract_non_cached_tokens_from_usage(usage: dict) -> int:
    return _to_int(
        get_field(
            usage,
            "non_cached_input_tokens",
            "nonCachedInputTokens",
            "uncached_input_tokens",
            "uncachedInputTokens",
            default=0,
        )
    )


def _extract_usage_override(hook_input: dict, tool_input: dict) -> dict:
    """Extract usage tokens from hook payload first; return empty dict when unavailable."""
    def _candidate(path: str, value: object) -> tuple[str, dict]:
        return (path, _to_dict(value))

    usage_candidates = []
    usage_candidates.append(_candidate("hook_input.usage", get_field(hook_input, "usage", default={})))
    usage_candidates.append(_candidate("tool_input.usage", get_field(tool_input, "usage", default={})))

    tool_output = _to_dict(get_field(hook_input, "toolOutput", "tool_output", default={}))
    usage_candidates.append(_candidate("hook_input.toolOutput.usage", get_field(tool_output, "usage", default={})))

    tool_response = _to_dict(get_field(hook_input, "tool_response", "toolResponse", default={}))
    usage_candidates.append(_candidate("hook_input.toolResponse.usage", get_field(tool_response, "usage", default={})))

    # Some runtimes surface usage directly under tool response/output payloads.
    usage_candidates.append(_candidate("hook_input.toolOutput", tool_output))
    usage_candidates.append(_candidate("hook_input.toolResponse", tool_response))

    tool_result = _to_dict(get_field(hook_input, "toolResult", "tool_result", default={}))
    usage_candidates.append(_candidate("hook_input.toolResult.usage", get_field(tool_result, "usage", default={})))
    usage_candidates.append(_candidate("hook_input.toolResult", tool_result))

    usage = {}
    usage_source = ""
    for source, candidate in usage_candidates:
        if candidate:
            usage = candidate
            usage_source = source
            break

    tool_use_id = str(get_field(hook_input, "tool_use_id", "toolUseId", default="") or "").strip()
    transcript_path = str(get_field(hook_input, "transcript_path", "transcriptPath", default="") or "").strip()
    correlation_identifier = ""

    if not usage:
        artifact_source, artifact_usage, correlation_identifier = _lookup_usage_from_copilot_artifacts(hook_input, tool_input)
        if artifact_usage:
            usage = artifact_usage
            usage_source = f"copilot_artifact:{artifact_source}"

    if not usage:
        top_level_keys = sorted([str(k) for k in hook_input.keys()]) if isinstance(hook_input, dict) else []
        tool_output_keys = sorted([str(k) for k in tool_output.keys()]) if tool_output else []
        tool_response_keys = sorted([str(k) for k in tool_response.keys()]) if tool_response else []
        tool_result_keys = sorted([str(k) for k in tool_result.keys()]) if tool_result else []
        log(
            "Usage extraction: no payload usage found "
            f"(top_keys={top_level_keys}, toolOutput_keys={tool_output_keys}, "
            f"toolResponse_keys={tool_response_keys}, toolResult_keys={tool_result_keys}, "
            f"tool_use_id={tool_use_id or 'none'}, transcript_path={transcript_path or 'none'}, "
            "source=prometheus_fallback)"
        )
        return {}

    log(f"Usage extraction source: {usage_source}")

    input_tokens = _to_int(
        get_field(usage, "input_tokens", "inputTokens", "prompt_tokens", "promptTokens", default=0)
    )
    output_tokens = _to_int(
        get_field(usage, "output_tokens", "outputTokens", "completion_tokens", "completionTokens", default=0)
    )
    cached_input_tokens = _extract_cached_tokens_from_usage(usage)
    non_cached_input_tokens_reported = _extract_non_cached_tokens_from_usage(usage)
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

    # Copilot payload input is total input; derive non-cached as input - cached.
    # Keep reported non-cached only as a diagnostic reference.
    effective_cached_input_tokens = max(min(cached_input_tokens, input_tokens), 0)
    effective_non_cached_input_tokens = max(input_tokens - effective_cached_input_tokens, 0)

    selected_artifact = "none"
    if usage_source.startswith("copilot_artifact:"):
        selected_artifact = usage_source.split("copilot_artifact:", 1)[1]

    log(
        "Usage correlation details: "
        f"tool_use_id={tool_use_id or 'none'}, "
        f"transcript_path={transcript_path or 'none'}, "
        f"artifact={selected_artifact}, "
        f"match={correlation_identifier or 'none'}, "
        f"input_tokens={input_tokens}, "
        f"cached_tokens={effective_cached_input_tokens}, "
        f"non_cached_input_tokens={effective_non_cached_input_tokens}, "
        f"output_tokens={output_tokens}, "
        f"source={'copilot_artifact' if usage_source.startswith('copilot_artifact:') else 'prometheus_fallback'}"
    )

    return {
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_input_tokens": effective_cached_input_tokens,
        "non_cached_input_tokens": effective_non_cached_input_tokens,
        "non_cached_input_tokens_reported": max(non_cached_input_tokens_reported, 0),
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
    """Coerce arbitrary pricing JSON into canonical {model: {input, cached_input, output}}."""
    pricing_map = _extract_pricing_map(raw)
    if not pricing_map:
        return {}

    coerced: dict[str, dict[str, float]] = {}

    def _rate(d: dict, *keys: str, default: float = 0.0) -> float:
        for key in keys:
            if key in d:
                try:
                    return float(d.get(key, default))
                except (TypeError, ValueError):
                    return default
        return default

    for model_name, rates in pricing_map.items():
        if not isinstance(rates, dict):
            continue
        try:
            input_rate = _rate(
                rates,
                "input",
                "input_per_1m_tokens",
                "input_per_1m",
                "inputPer1MTokens",
                "inputPer1M",
                default=0.0,
            )
            cached_input_rate = _rate(
                rates,
                "cached_input",
                "cached_input_per_1m_tokens",
                "cached_input_per_1m",
                "cachedInput",
                "cachedInputPer1MTokens",
                "cachedInputPer1M",
                default=input_rate,
            )
            output_rate = _rate(
                rates,
                "output",
                "output_per_1m_tokens",
                "output_per_1m",
                "outputPer1MTokens",
                "outputPer1M",
                default=0.0,
            )
        except (TypeError, ValueError):
            log(f"WARNING: Invalid pricing entry for model='{model_name}' from {source_name} — skipping")
            continue

        canonical_model = resolve_pricing_model(str(model_name))
        if canonical_model:
            coerced[canonical_model] = {
                "input": input_rate,
                "cached_input": cached_input_rate,
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
    """Initialize the persistent file logger with size-based rotation."""
    global _log_file
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / "otel-hook.log"

    # Rotate only when the current log is large enough; avoid per-invocation churn.
    if log_path.exists() and log_path.stat().st_size >= MAX_LOG_SIZE_BYTES:
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

    if OTEL_DIAGNOSTIC_LOGGING:
        log(f"PROMQL query: {query}")

    result = http_get(url)
    if OTEL_DIAGNOSTIC_LOGGING:
        if result is None:
            log("PROMQL result: none (request failed)")
        else:
            status = result.get("status", "unknown")
            result_count = len(result.get("data", {}).get("result", []) or [])
            log(f"PROMQL result: status={status}, count={result_count}")
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


def _query_session_id(query: str) -> str | None:
    """Return a session_id label from the first Prometheus result row for a query."""
    result = prom_query(query)
    if not result:
        return None
    try:
        rows = result.get("data", {}).get("result", [])
        if not rows:
            return None
        sid = rows[0].get("metric", {}).get("session_id")
        return sid or None
    except (AttributeError, KeyError, IndexError, TypeError):
        return None


def _session_has_token_metric_series(session_id: str) -> bool:
    """Check if a session currently has any token metric time series in Prometheus."""
    sid = str(session_id or "").strip()
    if not sid:
        return False

    metric = resolve_metric("copilot_gen_ai_client_token_usage_sum")
    value = prom_scalar(f'count({metric}{{session_id="{sid}"}})')
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def discover_active_session_id(preferred_session_id: str = "") -> str | None:
    """Discover the most active Prometheus session_id for the current hook invocation.

    Strategy order:
    1) Prefer the hook payload session_id if it already has token metric series.
    2) Find the session with recent metric increase over a short window.
    3) Fallback to the latest observed session sample timestamp.
    4) Fallback to payload session_id, then legacy discovery.
    """
    preferred = str(preferred_session_id or "").strip()
    if preferred and _session_has_token_metric_series(preferred):
        log(f"Active session_id resolved from hook payload: {preferred}")
        return preferred

    activity_metrics = [
        resolve_metric("copilot_gen_ai_client_operation_duration_count"),
        resolve_metric("copilot_gen_ai_client_token_usage_sum"),
    ]

    for metric in activity_metrics:
        sid = _query_session_id(
            f'topk(1, sum by (session_id) (increase({metric}{{session_id!=""}}[5m])))'
        )
        if sid:
            log(f"Active session_id resolved by recent activity via {metric}: {sid}")
            return sid

    for metric in activity_metrics:
        sid = _query_session_id(
            f'topk(1, max by (session_id) (timestamp({metric}{{session_id!=""}})))'
        )
        if sid:
            log(f"Active session_id resolved by latest sample via {metric}: {sid}")
            return sid

    if preferred:
        log(
            "No Prometheus-confirmed active session_id; falling back to hook payload "
            f"session_id={preferred}"
        )
        return preferred

    return discover_session_id()


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


def load_or_discover_session_id(preferred_session_id: str = "", force_refresh: bool = False) -> str:
    """Resolve session_id without blindly reusing stale cache entries."""
    sid_file = STATE_DIR / "pipeline_session_id"
    cached_sid = ""
    if sid_file.exists():
        try:
            cached_sid = sid_file.read_text().strip()
        except OSError:
            cached_sid = ""

    if force_refresh:
        sid = discover_active_session_id(preferred_session_id) or ""
    else:
        sid = ""
        if cached_sid and _session_has_token_metric_series(cached_sid):
            sid = cached_sid
        if not sid:
            sid = discover_active_session_id(preferred_session_id) or cached_sid or ""

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
            if OTEL_DIAGNOSTIC_LOGGING:
                log(f"Token metric label sample: model={model}, token_type={token_type}, value={val}")
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
        f"sum({metric}{{{sf.lstrip(',')}}}) / 1000", ts
    )


def prom_tool_duration_by_tool(sf: str = "", ts: float | None = None) -> dict[str, str]:
    """Get tool call duration sum grouped by tool name.
    Returns: {tool_name: duration_seconds_str}"""
    metric = resolve_metric("copilot_copilot_chat_tool_call_duration_sum")
    result = prom_query(
        f"sum by (gen_ai_tool_name) ({metric}{{{sf.lstrip(',')}}}) / 1000",
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


def _get_model_rates(model: str) -> dict[str, float]:
    """Resolve model pricing rates with safe fallback."""
    global MODEL_COST_RATES
    if not MODEL_COST_RATES:
        MODEL_COST_RATES = load_model_cost_rates()

    canonical_model = resolve_pricing_model(model)
    rates = MODEL_COST_RATES.get(canonical_model)
    if not rates:
        # Preserve fallback behavior but log unknown model keys once.
        if canonical_model not in _UNKNOWN_PRICING_MODELS:
            _UNKNOWN_PRICING_MODELS.add(canonical_model)
            log(
                "WARNING: No pricing configured for model "
                f"'{model}' (canonical='{canonical_model}'). Using fallback rates."
            )
        rates = {"input": 0.15, "cached_input": 0.15, "output": 0.60}

    if "cached_input" not in rates:
        rates["cached_input"] = rates.get("input", 0.0)

    return rates


def _round_cost(value: float, *, tokens: float, rate_per_million: float) -> float:
    rounded = round(float(value), COST_PRECISION)
    if tokens > 0 and rate_per_million > 0 and rounded == 0:
        return round(10 ** (-COST_PRECISION), COST_PRECISION)
    return rounded


def compute_cost(tokens: float, model: str, token_type: str) -> float:
    """Compute cost in USD for one token category (input/cached_input/output)."""
    rates = _get_model_rates(model)
    rate_per_million = float(rates.get(token_type, 0) or 0)
    value = (float(tokens) / 1_000_000) * rate_per_million
    return _round_cost(value, tokens=float(tokens), rate_per_million=rate_per_million)


def resolve_input_token_split(
    input_tokens: float,
    cached_input_tokens: float,
    non_cached_input_tokens: float,
) -> tuple[float, float, float]:
    """Return (effective_input_tokens, effective_cached_input_tokens, effective_non_cached_input_tokens)."""
    input_tokens = max(float(input_tokens), 0.0)
    cached_input_tokens = max(float(cached_input_tokens), 0.0)
    non_cached_input_tokens = max(float(non_cached_input_tokens), 0.0)

    if non_cached_input_tokens > 0:
        # Explicit non-cached value already supplied by telemetry payload.
        effective_non_cached = non_cached_input_tokens
        effective_cached = cached_input_tokens
        effective_input = max(input_tokens, effective_non_cached + effective_cached)
        return effective_input, effective_cached, effective_non_cached

    if input_tokens >= cached_input_tokens:
        effective_non_cached = input_tokens - cached_input_tokens
        effective_cached = cached_input_tokens
    else:
        # Guard malformed payloads where cached > input; avoid negative non-cached tokens.
        effective_non_cached = input_tokens
        effective_cached = 0.0

    return input_tokens, effective_cached, effective_non_cached


def compute_cost_breakdown(
    model: str,
    input_tokens: float,
    output_tokens: float,
    cached_input_tokens: float = 0.0,
    non_cached_input_tokens: float = 0.0,
) -> dict[str, float]:
    """Compute split token/cost breakdown with cached-input aware pricing."""
    rates = _get_model_rates(model)

    effective_input, effective_cached, effective_non_cached = resolve_input_token_split(
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        non_cached_input_tokens=non_cached_input_tokens,
    )

    non_cached_rate = float(rates.get("input", 0) or 0)
    cached_rate = float(rates.get("cached_input", non_cached_rate) or 0)
    output_rate = float(rates.get("output", 0) or 0)

    non_cached_input_cost_raw = (effective_non_cached / 1_000_000) * non_cached_rate
    cached_input_cost_raw = (effective_cached / 1_000_000) * cached_rate
    output_cost_raw = (max(float(output_tokens), 0.0) / 1_000_000) * output_rate

    non_cached_input_cost = _round_cost(
        non_cached_input_cost_raw,
        tokens=effective_non_cached,
        rate_per_million=non_cached_rate,
    )
    cached_input_cost = _round_cost(
        cached_input_cost_raw,
        tokens=effective_cached,
        rate_per_million=cached_rate,
    )
    output_cost = _round_cost(
        output_cost_raw,
        tokens=max(float(output_tokens), 0.0),
        rate_per_million=output_rate,
    )
    input_cost = _round_cost(
        non_cached_input_cost + cached_input_cost,
        tokens=effective_non_cached + effective_cached,
        rate_per_million=max(non_cached_rate, cached_rate),
    )
    total_cost = _round_cost(
        input_cost + output_cost,
        tokens=effective_non_cached + effective_cached + max(float(output_tokens), 0.0),
        rate_per_million=max(non_cached_rate, cached_rate, output_rate),
    )

    return {
        "input_tokens": round(effective_input, 6),
        "cached_input_tokens": round(effective_cached, 6),
        "non_cached_input_tokens": round(effective_non_cached, 6),
        "output_tokens": round(max(float(output_tokens), 0.0), 6),
        "non_cached_input_cost": non_cached_input_cost,
        "cached_input_cost": cached_input_cost,
        "input_cost": input_cost,
        "output_cost": output_cost,
        "total_cost": total_cost,
    }


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
        canonical = normalize_feature_id(candidate)
        if _is_valid_feature_id(canonical):
            return canonical
    # Fallback ticket-like ID.
    ticket_ids = re.findall(r"\b([A-Z][A-Z0-9]+-\d+)\b", text)
    for candidate in reversed(ticket_ids):
        canonical = normalize_feature_id(candidate)
        if _is_valid_feature_id(canonical):
            return canonical
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
                    candidate = normalize_feature_id(hint_path.parts[idx + 1])
                    if _is_valid_feature_id(candidate):
                        return candidate

    # Prefer active feature marker before free-text parsing fallback.
    active_feature_file = STATE_DIR / "active_feature_id"
    if active_feature_file.exists():
        try:
            active_feature = normalize_feature_id(active_feature_file.read_text())
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
            fid = normalize_feature_id(fid_file.read_text())
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
                fid = normalize_feature_id(latest.parent.name)
                if _is_valid_feature_id(fid):
                    log(f"Feature ID from tracker scan ({outputs_dir}): {fid}")
                    return fid

            feature_dirs = [p for p in outputs_dir.iterdir() if p.is_dir() and _is_valid_feature_id(p.name)]
            if feature_dirs:
                latest_dir = max(feature_dirs, key=lambda p: p.stat().st_mtime)
                fid = normalize_feature_id(latest_dir.name)
                log(f"Feature ID from latest output directory ({outputs_dir}): {fid}")
                return fid

    log(f"WARNING: Could not determine feature_id. cwd={cwd}, candidates={[str(c) for c in candidates[:3]]}")
    return None


def capture_baseline(preferred_session_id: str = "", force_refresh_session: bool = False) -> dict:
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
            baseline["stack_available"] = False
            baseline["telemetry_failure_reason"] = (
                "No copilot/gen_ai metrics discovered in Prometheus. "
                "Verify VS Code OTEL export settings and collector endpoint."
            )
            return baseline

    # Resolve the current active session_id for scoped queries.
    session_id = load_or_discover_session_id(
        preferred_session_id=preferred_session_id,
        force_refresh=force_refresh_session,
    )
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


def write_telemetry_failure(feature_id: str, agent_name: str, start_iso: str, end_iso: str, duration_s: float, cwd: str, reason: str) -> str:
    """Write explicit telemetry ingestion failure artifacts instead of zero-value success reports."""
    outputs_dir = resolve_outputs_dir(feature_id, cwd)
    telemetry_file = outputs_dir / "telemetry_report.md"
    cost_file = outputs_dir / "cost_report.md"

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
        f.write(
            f"### Agent: {agent_name}\n\n"
            f"- **Window:** {start_iso} -> {end_iso} ({duration_s:.0f}s)\n"
            f"- **Telemetry Status:** FAILED\n"
            f"- **Failure Reason:** {reason}\n\n"
            "---\n"
        )

    if not cost_file.exists():
        cost_file.write_text(
            "# Cost Report\n\n"
            "Auto-generated by otel-hook.py from per-agent usage.\n\n"
            f"- Feature ID: {feature_id}\n"
            f"- Service: {OTEL_SERVICE}\n\n",
            encoding="utf-8",
        )
    with open(cost_file, "a", encoding="utf-8") as cf:
        cf.write(
            f"## Agent: {agent_name}\n"
            f"- Window: {start_iso} -> {end_iso} ({duration_s:.0f}s)\n"
            "- Telemetry Status: FAILED\n"
            f"- Failure Reason: {reason}\n\n"
        )

    return f"[TELEMETRY][FAILED] Agent: {agent_name} | Reason: {reason}"


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
    feature_id = normalize_feature_id(feature_id)
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
    canonical_feature_id = normalize_feature_id(feature_id)
    json_file = outputs_dir / f"{canonical_feature_id}_telemetry_report.json"

    if json_file.exists():
        try:
            report = json.loads(json_file.read_text())
        except (json.JSONDecodeError, OSError) as e:
            log_error("Failed to read existing telemetry JSON for human wait update — starting fresh", e)
            report = {}
    else:
        report = {}

    report.setdefault("feature_id", canonical_feature_id)
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
    feature_id = normalize_feature_id(feature_id)
    resolved_feature_id = feature_id if _is_valid_feature_id(feature_id) else ""
    if not resolved_feature_id:
        resolved_feature_id = normalize_feature_id(find_feature_id(cwd) or "")
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
        "non_cached_input": delta_in,
        "cached_input": 0.0,
        "output": delta_out,
        "total": delta_in + delta_out,
    }
    entry["token_source"] = "prometheus_fallback"
    entry["token_split_exact"] = False

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
                "non_cached_input": d_in,
                "cached_input": 0.0,
                "output": d_out,
                "total": d_in + d_out,
            }
    entry["tokens_by_model"] = tokens_by_model

    # ── Cost by model (for this agent) ──
    cost_by_model = {}
    agent_cost_non_cached_total = 0.0
    agent_cost_cached_total = 0.0
    agent_cost_input_total = 0.0
    agent_cost_output_total = 0.0
    for model, toks in tokens_by_model.items():
        breakdown = compute_cost_breakdown(
            model=model,
            input_tokens=toks.get("input", 0),
            output_tokens=toks.get("output", 0),
            cached_input_tokens=toks.get("cached_input", 0),
            non_cached_input_tokens=toks.get("non_cached_input", 0),
        )
        cost_by_model[model] = {
            "non_cached_input_cost": breakdown["non_cached_input_cost"],
            "cached_input_cost": breakdown["cached_input_cost"],
            "input_cost": breakdown["input_cost"],
            "output_cost": breakdown["output_cost"],
            "total_cost": breakdown["total_cost"],
        }
        agent_cost_non_cached_total += breakdown["non_cached_input_cost"]
        agent_cost_cached_total += breakdown["cached_input_cost"]
        agent_cost_input_total += breakdown["input_cost"]
        agent_cost_output_total += breakdown["output_cost"]
    entry["cost_by_model"] = cost_by_model
    entry["cost"] = {
        "non_cached_input_cost": round(agent_cost_non_cached_total, COST_PRECISION),
        "cached_input_cost": round(agent_cost_cached_total, COST_PRECISION),
        "input_cost": round(agent_cost_input_total, COST_PRECISION),
        "output_cost": round(agent_cost_output_total, COST_PRECISION),
        "total_cost": round(agent_cost_input_total + agent_cost_output_total, COST_PRECISION),
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
    canonical_feature_id = normalize_feature_id(feature_id)
    json_file = outputs_dir / f"{canonical_feature_id}_telemetry_report.json"

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
    report.setdefault("feature_id", canonical_feature_id)
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
            "non_cached_input": t.get("non_cached_input", t.get("input", 0)),
            "cached_input": t.get("cached_input", 0),
            "output": t.get("output", 0),
            "total": t.get("total", 0),
        }
    report["token_consumption_by_agent"] = tokens_by_agent

    # Token consumption by model (aggregated across agents)
    model_tokens_agg: dict[str, dict[str, float]] = {}
    for a in agents:
        for model, toks in a.get("tokens_by_model", {}).items():
            agg = model_tokens_agg.setdefault(
                model,
                {"input": 0, "non_cached_input": 0, "cached_input": 0, "output": 0, "total": 0},
            )
            agg["input"] += toks.get("input", 0)
            agg["non_cached_input"] += toks.get("non_cached_input", toks.get("input", 0))
            agg["cached_input"] += toks.get("cached_input", 0)
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
            agg = cost_by_model_agg.setdefault(
                model,
                {
                    "non_cached_input_cost": 0,
                    "cached_input_cost": 0,
                    "input_cost": 0,
                    "output_cost": 0,
                    "total_cost": 0,
                },
            )
            agg["non_cached_input_cost"] += costs.get("non_cached_input_cost", 0)
            agg["cached_input_cost"] += costs.get("cached_input_cost", 0)
            agg["input_cost"] += costs.get("input_cost", 0)
            agg["output_cost"] += costs.get("output_cost", 0)
            agg["total_cost"] += costs.get("total_cost", 0)
    # Round aggregated values
    for model in cost_by_model_agg:
        for k in cost_by_model_agg[model]:
            cost_by_model_agg[model][k] = round(cost_by_model_agg[model][k], COST_PRECISION)
    report["cost_by_model"] = cost_by_model_agg

    # Cost by agent
    cost_by_agent = {}
    for a in agents:
        c = a.get("cost", {})
        cost_by_agent[a["agent_name"]] = {
            "non_cached_input_cost": c.get("non_cached_input_cost", 0),
            "cached_input_cost": c.get("cached_input_cost", 0),
            "input_cost": c.get("input_cost", 0),
            "output_cost": c.get("output_cost", 0),
            "total_cost": c.get("total_cost", 0),
        }
    report["cost_by_agent"] = cost_by_agent

    # Pipeline cost totals
    pipeline_non_cached_input_cost = sum(c.get("non_cached_input_cost", 0) for c in cost_by_agent.values())
    pipeline_cached_input_cost = sum(c.get("cached_input_cost", 0) for c in cost_by_agent.values())
    pipeline_input_cost = sum(c.get("input_cost", 0) for c in cost_by_agent.values())
    pipeline_output_cost = sum(c.get("output_cost", 0) for c in cost_by_agent.values())
    report["pipeline_cost"] = {
        "non_cached_input_cost": round(pipeline_non_cached_input_cost, COST_PRECISION),
        "cached_input_cost": round(pipeline_cached_input_cost, COST_PRECISION),
        "input_cost": round(pipeline_input_cost, COST_PRECISION),
        "output_cost": round(pipeline_output_cost, COST_PRECISION),
        "total_cost": round(pipeline_input_cost + pipeline_output_cost, COST_PRECISION),
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

    if not stack_available and not usage_override:
        reason = baseline.get("telemetry_failure_reason", "Telemetry source unavailable (Prometheus metrics missing)")
        return write_telemetry_failure(feature_id, agent_name, start_iso, end_iso, duration_s, cwd, reason)

    # Primary token source is hook payload usage; Prometheus is fallback.
    if usage_override:
        usage_model = usage_override.get("model", "default")
        input_tokens = float(usage_override.get("input_tokens", 0) or 0)
        output_tokens = float(usage_override.get("output_tokens", 0) or 0)
        cached_input_tokens = float(usage_override.get("cached_input_tokens", 0) or 0)
        non_cached_input_tokens = float(usage_override.get("non_cached_input_tokens", 0) or 0)
        non_cached_input_tokens_reported = float(usage_override.get("non_cached_input_tokens_reported", 0) or 0)

        log(
            "Token source: usage payload "
            f"(model={usage_model}, input={input_tokens:.0f}, cached={cached_input_tokens:.0f}, "
            f"non_cached_derived={non_cached_input_tokens:.0f}, output={output_tokens:.0f}, "
            f"non_cached_reported={non_cached_input_tokens_reported:.0f})"
        )

        breakdown = compute_cost_breakdown(
            model=usage_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_input_tokens,
            non_cached_input_tokens=non_cached_input_tokens,
        )
        effective_input_tokens = breakdown["input_tokens"]
        effective_cached_input_tokens = breakdown["cached_input_tokens"]
        effective_non_cached_input_tokens = breakdown["non_cached_input_tokens"]
        total_tokens = effective_input_tokens + output_tokens

        agent_entry["tokens"] = {
            "input": effective_input_tokens,
            "non_cached_input": effective_non_cached_input_tokens,
            "cached_input": effective_cached_input_tokens,
            "output": output_tokens,
            "total": total_tokens,
        }
        agent_entry["token_source"] = "usage_payload"
        agent_entry["token_split_exact"] = True
        agent_entry["tokens_by_model"] = {
            usage_model: {
                "input": effective_input_tokens,
                "non_cached_input": effective_non_cached_input_tokens,
                "cached_input": effective_cached_input_tokens,
                "output": output_tokens,
                "total": total_tokens,
            }
        }
        agent_entry["cost_by_model"] = {
            usage_model: {
                "non_cached_input_cost": breakdown["non_cached_input_cost"],
                "cached_input_cost": breakdown["cached_input_cost"],
                "input_cost": breakdown["input_cost"],
                "output_cost": breakdown["output_cost"],
                "total_cost": breakdown["total_cost"],
            }
        }
        agent_entry["cost"] = {
            "non_cached_input_cost": breakdown["non_cached_input_cost"],
            "cached_input_cost": breakdown["cached_input_cost"],
            "input_cost": breakdown["input_cost"],
            "output_cost": breakdown["output_cost"],
            "total_cost": breakdown["total_cost"],
        }
    else:
        log(
            "Token source: Prometheus fallback (cached split unavailable; non-cached shown as estimated from total input) "
            f"(session_id={baseline.get('session_id', '') or 'none'}, "
            f"baseline_in={baseline.get('tokens_input', 'N/A')}, "
            f"baseline_out={baseline.get('tokens_output', 'N/A')}, "
            f"agent={agent_name})"
        )

    if not usage_override and not agent_entry.get("tokens_by_model"):
        reason = (
            "Prometheus returned no gen_ai token metrics for this runSubagent invocation "
            f"(session_id={baseline.get('session_id', '') or 'none'})."
        )
        return write_telemetry_failure(feature_id, agent_name, start_iso, end_iso, duration_s, cwd, reason)

    # ── Write JSON report ──
    update_telemetry_json(outputs_dir, feature_id, agent_entry)

    # ── Extract values for MD report (from JSON entry) ──
    tokens = agent_entry.get("tokens", {})
    delta_tokens_input = f"{tokens.get('input', 0):,.0f}" if tokens else "N/A"
    delta_tokens_non_cached_input = f"{tokens.get('non_cached_input', tokens.get('input', 0)):,.0f}" if tokens else "N/A"
    delta_tokens_cached_input = f"{tokens.get('cached_input', 0):,.0f}" if tokens else "N/A"
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
        f"| {model} | {toks.get('non_cached_input', toks.get('input', 0)):,.0f} | {toks.get('cached_input', 0):,.0f} | {toks['output']:,.0f} |"
        for model, toks in sorted(tokens_by_model.items())
    ) if tokens_by_model else ""

    # LLM calls rows
    llm_calls = agent_entry.get("llm_calls_by_model", {})
    model_rows = "\n".join(f"| {name} | {val} |" for name, val in
                           sorted(llm_calls.items(), key=lambda x: x[1], reverse=True)) if llm_calls else ""

    # Cost rows
    cost_by_model = agent_entry.get("cost_by_model", {})
    cost_rows = "\n".join(
        f"| {model} | ${c.get('non_cached_input_cost', 0):.8f} | ${c.get('cached_input_cost', 0):.8f} | ${c['output_cost']:.8f} | ${c['total_cost']:.8f} |"
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
| Non-Cached Input Tokens (Δ) | {delta_tokens_non_cached_input} |
| Cached Input Tokens (Δ) | {delta_tokens_cached_input} |
| Output Tokens (Δ) | {delta_tokens_output} |

#### Token Usage by Model (Δ for this agent run)

| Model | Non-Cached Input Tokens (Δ) | Cached Input Tokens (Δ) | Output Tokens (Δ) |
|-|-|-|-|
{model_token_rows if model_token_rows else "| (no data) | — | — | — |"}

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

| Model | Non-Cached Input Cost | Cached Input Cost | Output Cost | Total Cost |
|-|-|-|-|-|
{cost_rows if cost_rows else "| (no data) | — | — | — | — |"}
| **Agent Total** | **${agent_cost.get('non_cached_input_cost', 0):.8f}** | **${agent_cost.get('cached_input_cost', 0):.8f}** | **${agent_cost.get('output_cost', 0):.8f}** | **${agent_cost.get('total_cost', 0):.8f}** |

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
            f"- Cost: ${agent_cost.get('total_cost', 0):.8f}\n\n"
        )

    log(f"Cost report appended -> {cost_file}")

    return (
        f"[TELEMETRY] Agent: {agent_name} | "
        f"Model: {summary_model} | "
        f"Tokens: {total_tokens_int:,} | "
        f"Cost: ${agent_cost.get('total_cost', 0):.8f} | "
        f"Non-Cached Input Cost: ${agent_cost.get('non_cached_input_cost', 0):.8f} | "
        f"Cached Input Cost: ${agent_cost.get('cached_input_cost', 0):.8f} | "
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
    raw_feature_id = normalize_feature_id(feature_id or "")
    resolved_feature_id = raw_feature_id if _is_valid_feature_id(raw_feature_id) else find_feature_id(cwd)
    resolved_feature_id = normalize_feature_id(resolved_feature_id or "")
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

    def _upsert_stop_summary(content: str, marker: str, block: str, next_headings_pattern: str) -> str:
        pattern = re.compile(
            rf"(?:^|\n)## Final Summary \(Stop\)\n{re.escape(marker)}\n.*?(?={next_headings_pattern}|\Z)",
            re.DOTALL,
        )
        match = pattern.search(content)
        if match:
            prefix = "" if match.start() == 0 else "\n"
            return content[:match.start()] + prefix + block + content[match.end():]

        if content and not content.endswith("\n"):
            content += "\n"
        separator = "\n" if content else ""
        return content + separator + block

    telemetry_summary_block = (
        "## Final Summary (Stop)\n"
        f"{telemetry_marker}\n"
        f"- Feature ID: {resolved_feature_id}\n"
        f"- Agent runs captured: {agent_count}\n"
        f"- Total tokens: {total_tokens:,}\n"
        f"- Total estimated cost: ${total_cost:.4f}\n"
        f"- Finalized at: {now_utc()}\n"
    )

    telemetry_content = _safe_read_text(telemetry_file)
    if not telemetry_content:
        telemetry_content = (
            "# OpenTelemetry Telemetry Report\n\n"
            "Auto-generated by VS Code agent hooks during the orchestrator pipeline.\n\n"
            f"- Feature ID: {resolved_feature_id}\n"
            f"- Service: {OTEL_SERVICE}\n"
            f"- Prometheus: {PROMETHEUS_URL}\n\n"
            "---\n"
        )
    telemetry_content = _upsert_stop_summary(
        telemetry_content,
        telemetry_marker,
        telemetry_summary_block,
        r"\n## |\n### ",
    )
    telemetry_file.write_text(telemetry_content, encoding="utf-8")

    cost_summary_block = (
        "## Final Summary (Stop)\n"
        f"{cost_marker}\n"
        f"- Feature ID: {resolved_feature_id}\n"
        f"- Agent runs captured: {agent_count}\n"
        f"- Total tokens: {total_tokens:,}\n"
        f"- Total estimated cost: ${total_cost:.4f}\n"
        f"- Finalized at: {now_utc()}\n"
    )

    cost_content = _safe_read_text(cost_file)
    if not cost_content:
        cost_content = (
            "# Cost Report\n\n"
            "Auto-generated by otel-hook.py from per-agent usage.\n\n"
            f"- Feature ID: {resolved_feature_id}\n"
            f"- Service: {OTEL_SERVICE}\n\n"
        )
    cost_content = _upsert_stop_summary(
        cost_content,
        cost_marker,
        cost_summary_block,
        r"\n## ",
    )
    cost_file.write_text(cost_content, encoding="utf-8")

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
        baseline = capture_baseline(
            preferred_session_id=str(hook_session_id or ""),
            force_refresh_session=True,
        )
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
