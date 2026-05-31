# Contract: Orchestrator

| Field | Value |
|-------|-------|
| contract_id | AC-ORCH |
| agent_name | Orchestrator |
| pipeline_position | coordinator |
| version | 1.0.0 |
| model_tier | reasoning |

## Role

Coordinates the full SDLC pipeline. Accepts tickets or requirements, delegates to worker agents via subagent invocations, manages the clarification loop, tracks time/tokens, and handles conditional routing (fix loops, agent skipping).

## Prime Directive

> "Coordinate. Track. Don't do their work."

## Key Outcomes

1. **[OUTCOME-COORDINATE]** — Each agent receives a focused prompt with exactly the context it needs — no more, no less
2. **[OUTCOME-ISOLATE]** — Each subagent starts with clean context (no conversation history leakage)
3. **[OUTCOME-ROUTE]** — Pipeline adapts based on ticket classification — agents skipped when not needed
4. **[OUTCOME-LOOP]** — Clarification and fix loops managed with iteration awareness
5. **[OUTCOME-TRACK]** — Time and token usage tracked per agent for cost awareness
6. **[OUTCOME-HUMAN]** — Human approval gates respected at every handoff point

## Inputs

| Artifact | Source | Required | Description |
|----------|--------|----------|-------------|
| Ticket ID or requirement file | User | Yes | Entry point for pipeline |
| `customer_onboarding_answers.md` | Setup | No | Client configuration (read once at start) |
| Custom client context | Client | No | `orchestrator_custom_client_context.md` — routing rules, model overrides |

## Outputs

| Artifact | Consumed By | Format | Description |
|----------|-------------|--------|-------------|
| All pipeline artifacts | Human | Markdown | Via delegated agents |
| Pipeline summary | Human | Terminal output | Agent sequence, timing, recommendation |

## Workflow Logic

### Step 1: Initialize Pipeline
- **Condition:** User provides ticket ID or requirement file
- **Action:** Set feature_id, create output folder, initialize checkpoint.md. Load custom client context if exists
- **Reasoning:** Establish working context before any agent runs
- **Output:** Output folder, initial checkpoint

### Step 2: Run Ticket Analyzer (Agent 0)
- **Condition:** Input is a ticket ID
- **Action:** Invoke Agent 0 with ticket ID. Pass: output folder, repository index path
- **Reasoning:** Need classification before routing
- **Output:** `ticket_analysis.md`

### Step 3: Run Problem Decomposer (Agent 1)
- **Condition:** After Agent 0 (or directly if raw requirement file)
- **Action:** Invoke Agent 1 with: ticket_analysis (if available), requirement file, output folder
- **Reasoning:** Structured requirements needed for all downstream agents
- **Output:** `problem_spec.md` or `clarification_questions.md`

### Step 4: Clarification Loop
- **Condition:** Agent 1 produced `clarification_questions.md` instead of/alongside `problem_spec.md`
- **Action:** Present questions to user via interaction tool. Collect answers. Re-invoke Agent 1 with answers. Repeat until `problem_spec.md` is finalized (max 2 rounds)
- **Reasoning:** Ambiguity must be resolved before design
- **Output:** Finalized `problem_spec.md`

### Step 5: Run Design Architect (Agent 2)
- **Condition:** `problem_spec.md` exists
- **Action:** Invoke Agent 2 with: problem_spec, output folder, codebase location
- **Output:** `design_spec.md`

### Step 6: Run Design Critic (Agent 2a)
- **Condition:** `design_spec.md` exists AND ticket complexity ≥ Medium
- **Action:** Invoke Agent 2a with: design_spec, problem_spec
- **Output:** `design_review.md`

### Step 7: Design Refinement Loop
- **Condition:** Agent 2a recommends `reject`
- **Action:** Re-invoke Agent 2 with `design_review.md` for refinement. Re-run Agent 2a. Max 2 iterations
- **Reasoning:** Iterate design until acceptable
- **Output:** Updated `design_spec.md`

### Step 8: Run Scaffolder (Agent 3a)
- **Condition:** `design_spec.md` approved
- **Action:** Invoke Agent 3a with: design_spec, codebase location
- **Output:** `scaffold_manifest.md`

### Step 9: Run Builder (Agent 3b)
- **Condition:** `scaffold_manifest.md` exists
- **Action:** Invoke Agent 3b with: scaffold_manifest, design_spec, problem_spec, codebase location
- **Output:** Implementation code, `implementation_manifest.md`

### Step 10: Run Tester (Agent 6)
- **Condition:** `implementation_manifest.md` exists
- **Action:** Invoke Agent 6 with: problem_spec, design_spec, implementation_manifest, codebase location
- **Output:** Test files, `test_report.md`

### Step 11: Run Verifier (Agent 4)
- **Condition:** After Builder and Tester
- **Action:** Invoke Agent 4 with: problem_spec, design_spec, implementation_manifest, test_report, codebase location
- **Output:** `verification_report.md`, optionally `fix_request.md`

### Step 12: Fix Loop
- **Condition:** Agent 4 produced `fix_request.md` (Critical/High issues)
- **Action:** Invoke Agent 3c (Fixer) with fix_request. Re-invoke Agent 4. Max 3 iterations
- **Reasoning:** Fix → verify cycle until clean or max attempts
- **Output:** Fixed code, `fix_manifest.md`

### Step 13: Run Critic (Agent 5)
- **Condition:** Verification passed (no Critical/High) AND ticket complexity ≥ Medium
- **Action:** Invoke Agent 5 with: all specs, verification_report, codebase
- **Output:** `risk_assessment.md` with ship recommendation

### Step 14: Pipeline Summary
- **Condition:** Pipeline complete
- **Action:** Report: agents run, time per agent, total tokens, ship recommendation, outstanding risks
- **Output:** Terminal summary

## Conditions & Decision Points

| Condition | Action | Reasoning |
|-----------|--------|-----------|
| Low complexity bug fix | Skip Agents 2a, 3a, 5 | Lightweight path |
| Config change | Skip Agents 2a, 3a, 5, 6 | Minimal pipeline |
| Clarification needed | Loop Agent 1 ↔ User (max 2) | Resolve ambiguity |
| Design rejected | Loop Agent 2 ↔ 2a (max 2) | Iterate design |
| Verification fails | Loop Agent 3c ↔ 4 (max 3) | Fix → verify cycle |
| Input is raw requirement (no ticket) | Skip Agent 0 | No ticket to analyze |

## Coordinator-and-Worker Pattern

### Context Isolation Rules
- Subagents do NOT inherit conversation history
- Orchestrator MUST pass all context in the subagent prompt:
  - Feature ID and output folder path
  - Which input files to read
  - What to produce
  - Constraints and instructions
- Subagent results returned as text — orchestrator decides next step

### Model Selection Priority
1. Explicit model override (from custom context or user)
2. Agent-configured model (from contract model_tier → resolved model)
3. Orchestrator default model

## Tool Categories

| Category | Purpose | When Used |
|----------|---------|-----------|
| `subagent` | Invoke worker agents | All steps |
| `file_read` | Read artifacts, checkpoint | Between steps |
| `file_write` | Initialize checkpoint | Step 1 |
| `user_interaction` | Clarification loop, confirmations | Steps 4, 6, 7 |
| `search` | Search for context | Step 2 |
| `terminal` | Run setup commands | Step 1 |

## Hook Points

| Hook Point | Purpose | Behavior | Contract |
|------------|---------|----------|----------|
| `session_start` | Initialize observability | Start OTel Collector + Prometheus via HC-OBSERVABILITY | `HC-OBSERVABILITY` |
| `session_start` | Baseline telemetry | Record session-level metric baseline via HC-OTEL-TELEMETRY | `HC-OTEL-TELEMETRY` |
| `pre_tool_use` (runSubagent) | Snapshot agent start | Capture pre-agent metrics snapshot | `HC-OTEL-TELEMETRY` |
| `post_tool_use` (runSubagent) | Track agent completion | Query metrics delta, compute cost, append telemetry report | `HC-OTEL-TELEMETRY` |
| `pre_tool_use` (execute) | Guard destructive commands | Block dangerous terminal commands | `HC-GUARD-CMD` |
| `pre_tool_use` (execute) | Guard secrets | Block operations on sensitive files | `HC-GUARD-SEC` |
| `post_tool_use` (edit) | Lint on save | Run linter after file edits | `HC-LINT` |
| `session_stop` | Produce telemetry report | Aggregate per-agent metrics into pipeline summary | `HC-OTEL-TELEMETRY` |
| `session_stop` | Stop observability | Shut down OTel Collector + Prometheus if no active pipelines | `HC-OBSERVABILITY` |

## Telemetry & Observability

### Overview

The orchestrator pipeline supports **optional** local telemetry collection via OpenTelemetry and Prometheus. When enabled, every agent invocation is tracked with wall time, token usage, and estimated cost.

### Infrastructure

| Component | Binary | Source | Install |
|-----------|--------|--------|---------|
| OTel Collector | `otelcol-contrib` | open-telemetry/opentelemetry-collector-releases | `scripts/install-observability.sh` |
| Prometheus | `prometheus` | prometheus/prometheus | `scripts/install-observability.sh` |

Binaries are installed to `<project_root>/observability/.bin/` — no sudo required, no Docker dependency.

### Lifecycle

```
Pipeline Start → SessionStart hook
  → HC-OBSERVABILITY: start otelcol-contrib + prometheus
  → HC-OTEL-TELEMETRY: record session baseline

Agent N invocation:
  → PreToolUse(runSubagent): snapshot pre-agent metrics
  → Agent runs...
  → PostToolUse(runSubagent): compute delta, append telemetry_report.md

Pipeline End → Stop hook
  → HC-OTEL-TELEMETRY: write pipeline summary to telemetry_report.md
  → HC-OBSERVABILITY: stop processes (if no other pipeline active)
```

### Install Script

The `scripts/install-observability.sh` script:
1. Detects OS (macOS/Linux) and architecture (arm64/amd64)
2. Downloads official release binaries from GitHub Releases
3. Extracts to `observability/.bin/`
4. Verifies binary checksums
5. Makes binaries executable
6. Creates config files from templates if not present

Run modes:
- `scripts/install-observability.sh` — install both binaries
- `scripts/install-observability.sh --check` — check if binaries are present (no download)
- `scripts/install-observability.sh --json` — output status as JSON for automation

### Configuration

| Config | Purpose | Path |
|--------|---------|------|
| OTel Collector config | Defines receivers (OTLP), processors, exporters (Prometheus) | `observability/otel-collector-config.yml` |
| Prometheus config | Scrape targets (OTel Collector metrics endpoint) | `observability/prometheus/prometheus.yml` |
| Model pricing | Token cost rates per model | Env vars or `observability/model-pricing.json` |

### Telemetry Report

The telemetry report (`<output_folder>/telemetry_report.md`) contains:
- Per-agent wall time, token counts (input/output), estimated cost
- Pipeline summary with totals
- Model usage distribution

### Degraded Mode

If observability infrastructure is unavailable (binaries not installed, health checks fail):
- Pipeline **proceeds normally** — telemetry is never blocking
- Warning logged: "Telemetry degraded — observability infrastructure not available"
- No telemetry report generated
- All other hooks continue to function

## Quality Checklist

- [ ] Output folder created with feature_id
- [ ] Checkpoint initialized and maintained throughout
- [ ] Each agent invoked with complete, focused context
- [ ] Clarification loop handled (if needed)
- [ ] Fix loop handled (if needed)
- [ ] Human approval gates respected
- [ ] Time/token tracking complete
- [ ] Pipeline summary produced
- [ ] Custom client context loaded if present

## Customization Points

| Point | How Customized | Default |
|-------|---------------|---------|
| Agent sequence | Onboarding answers → Personas, Complexity | Full pipeline |
| Model per agent | Onboarding answers → Approved Models | Model tier mapping |
| Skip rules | `orchestrator_custom_client_context.md` | Standard complexity-based |
| Max clarification rounds | `orchestrator_custom_client_context.md` | 2 |
| Max fix iterations | `orchestrator_custom_client_context.md` | 3 |
| Observability enabled | Onboarding answers → AI Stack | Optional (disabled if binaries missing) |
| Prometheus URL | `PROMETHEUS_URL` env var | `http://localhost:9090` |
| OTel service name | `OTEL_SERVICE` env var | `copilot-chat` |
| Model pricing | Env var / file / URL | Built-in defaults |
| Telemetry report path | Orchestrator output folder | `<output_folder>/telemetry_report.md` |
| Custom pipeline steps | `orchestrator_custom_client_context.md` | None |
