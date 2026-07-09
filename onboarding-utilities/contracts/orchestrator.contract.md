# Contract: Orchestrator

| Field | Value |
|-------|-------|
| contract_id | AC-ORCH |
| agent_name | Orchestrator |
| pipeline_position | coordinator |
| version | 1.0.0 |
| model_tier | reasoning |
| argument_hint | Ticket ID, requirement file path, or 'resume' to continue from checkpoint |

## Role

Coordinates the full SDLC pipeline. Accepts tickets or requirements, delegates to worker agents via subagent invocations, manages the clarification loop, tracks time/tokens, and handles conditional routing (fix loops, agent skipping).

## Prime Directive

> "Coordinate. Track. Don't do their work."

## Key Outcomes

1. **[OUTCOME-COORDINATE]** - Each agent receives a focused prompt with exactly the context it needs - no more, no less
2. **[OUTCOME-ISOLATE]** - Each subagent starts with clean context (no conversation history leakage)
3. **[OUTCOME-ROUTE]** - Pipeline adapts based on ticket classification - agents skipped when not needed
4. **[OUTCOME-LOOP]** - Clarification and fix loops managed with iteration awareness
5. **[OUTCOME-TRACK]** - Time and token usage tracked per agent for cost awareness
6. **[OUTCOME-HUMAN]** - Human approval gates respected at every handoff point

## Inputs

| Artifact | Source | Required | Description |
|----------|--------|----------|-------------|
| Ticket ID or requirement file | User | Yes | Entry point for pipeline |
| `intake-sources.md` | Setup | No | Client configuration (read once at start) |
| Custom client context | Client | No | `orchestrator_custom_client_context.md` - routing rules, model overrides |
| `index.md` | Preflight | No | Repository catalog and Service Catalogue for routing |
| `.mcp.json` | Preflight | No | MCP server definitions (if MCP integration selected) |
| `connector_config.md` | Preflight | No | API-based connector configuration |

### Input Validation

1. **Ticket ID or requirement file** - Must be non-empty; if ticket ID, must match ticket prefix regex from onboarding
2. **`intake-sources.md`** - If present, validate against onboarding schema (Organisation, LLM Models, Constraints sections required)
3. **Custom client context** - If present, validate structure (expected sections: routing rules, model overrides)
4. **`index.md`** - If present, verify at least one repository is listed
5. **`.mcp.json`** - If present, validate JSON structure with `mcpServers` key
6. **`connector_config.md`** - If present, verify at least one connector section exists

If validation fails for a required input, **halt and report the error** to the user.
If validation fails for an optional input, **log a warning** and proceed without it.

## Outputs

| Artifact | Consumed By | Format | Description |
|----------|-------------|--------|-------------|
| All pipeline artifacts | Human | Markdown | Via delegated agents |
| Pipeline summary | Human | Terminal output | Agent sequence, timing, recommendation |
| `telemetry_report.md` | Human | Markdown | Per-agent time, tokens, cost |
| `checkpoint.md` | Self (resume) | Markdown | Pipeline state for resume/re-run |
| `pipeline_log.md` | Human | Markdown | Full execution log with decisions |

### Output Validation

After pipeline completion, validate:
1. All expected artifacts exist in the output folder
2. No artifact is empty or contains only placeholders
3. Pipeline summary includes all required sections (agents run, timing, recommendation)
4. Telemetry report (if observability enabled) contains entries for each agent executed
5. Checkpoint reflects final completed state

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
- **Reasoning:** Fix -> verify cycle until clean or max attempts
- **Output:** Fixed code, `fix_manifest.md`

### Step 13: Run Critic (Agent 5)
- **Condition:** Verification passed (no Critical/High) AND ticket complexity ≥ Medium
- **Action:** Invoke Agent 5 with: all specs, verification_report, codebase
- **Output:** `risk_assessment.md` with ship recommendation

### Step 14: Run Documentation Generator (Agent 7)
- **Condition:** Verification passed AND ticket is not config-only
- **Action:** Invoke Agent 7 with: problem_spec, design_spec, implementation_manifest, verification_report, test_report, risk_assessment
- **Output:** `documentation_manifest.md`, `pr_description.md`, `commit_messages.md`, updated API docs, changelog, ADRs

### Step 15: Run IaC/DevOps Specialist (Agent 8)
- **Condition:** Ticket classified as infrastructure/devops change
- **Action:** Invoke Agent 8 with: problem_spec, design_spec, ticket_analysis
- **Output:** `iac_manifest.md`, `blast_radius_assessment.md`, `rollback_plan.md`, `iac_plan_output.md`

### Step 16: Pipeline Summary
- **Condition:** Pipeline complete
- **Action:** Report: agents run, time per agent, total tokens, ship recommendation, outstanding risks, documentation generated, IaC changes (if any)
- **Output:** Terminal summary

### Step 17: Finalization
- **Condition:** Pipeline summary produced
- **Action:** Execute finalization protocol:
  1. Validate all expected outputs exist and are non-empty
  2. Verify checkpoint reflects completed state
  3. Generate final telemetry summary (if observability enabled)
  4. Archive pipeline state for audit/reference
  5. Clean up temporary working files
  6. Present final ship recommendation with confidence score
- **Output:** Finalized pipeline state, archived artifacts

## Checkpointing Strategy

### What Is Saved

| Data | When Saved | Purpose |
|------|-----------|---------|
| Current step number | After each step | Resume point |
| Completed agents list | After each agent completes | Skip on resume |
| Agent outputs (file paths) | After each agent produces output | Avoid re-generation |
| Clarification answers | After user provides answers | Avoid re-asking |
| Fix loop iteration count | After each fix attempt | Enforce max iterations |
| Pipeline routing decisions | After classification | Consistent routing on resume |
| Error state | On failure | Recovery on resume |

### Checkpoint Format

```json
{
  "feature_id": "<feature-id>",
  "pipeline_started": "<timestamp>",
  "current_step": 5,
  "completed_steps": [1, 2, 3, 4],
  "completed_agents": ["agent0", "agent1"],
  "agent_outputs": {"agent0": "ticket_analysis.md", "agent1": "problem_spec.md"},
  "routing_decisions": {"complexity": "High", "type": "feature", "skip": []},
  "clarification_answers": {},
  "fix_loop_count": 0,
  "errors": [],
  "status": "in_progress"
}
```

### Save Frequency

- Save **after every step completion** (not mid-step)
- Save **before user interaction** (in case user abandons session)
- Save **on error** (capture failure state for recovery)

## Resume Protocol

On every run, **FIRST** check for an existing checkpoint:

1. Load checkpoint from `<output_folder>/checkpoint.md` or `outputs/agents-repo/.github/sdlc-pipeline/checkpoint_state.json`
2. If checkpoint exists and `status != "completed"`:
   - Read `current_step` - resume from this step
   - Read `completed_agents` - skip already-completed agents
   - Read `agent_outputs` - verify files still exist (re-run agent if output missing)
   - Read `routing_decisions` - use same routing (don't re-classify)
   - Read `errors` - attempt recovery for recoverable errors
   - Inform user: "Resuming pipeline from Step X. Steps 1-(X-1) already completed."
3. If no checkpoint exists or `status == "completed"`:
   - Start fresh from Step 1
4. If checkpoint is corrupted:
   - Log warning, start fresh, inform user

## Re-run Protocol

When user requests re-run of a specific step or agent:

1. **Validate request** - confirm which step/agent to re-run
2. **Load checkpoint** - get current pipeline state
3. **Accept feedback** - collect user feedback for the re-run (e.g., "Use stricter type checking")
4. **Reset step** - mark the target step as incomplete in checkpoint
5. **Cascade resets** - mark all downstream steps as incomplete (they depend on re-run output)
6. **Re-execute** - run the target step with feedback incorporated
7. **Continue pipeline** - proceed from re-run step through remaining steps
8. **Update checkpoint** - save new state after re-run

### Re-run Boundaries

| Re-run Target | Cascade Resets | Reasoning |
|---------------|---------------|-----------|
| Agent 0 (Ticket Analyzer) | All downstream | Classification affects routing |
| Agent 1 (Problem Decomposer) | Agent 2+ | New requirements affect everything |
| Agent 2 (Design Architect) | Agent 3a+ | New design affects implementation |
| Agent 3b (Builder) | Agent 4, 6 | New code needs re-verification |
| Agent 4 (Verifier) | Agent 5, 7 | New verification may change risk/docs |
| Agent 8 (IaC) | None | Independent path |

## Finalization Protocol

When the pipeline reaches completion:

1. **Verify all outputs** - check every expected artifact exists and is valid
2. **Produce final telemetry** - aggregate all per-agent metrics into pipeline summary
3. **Archive state** - save final checkpoint with `status: "completed"`
4. **Generate ship recommendation** - combine Critic's risk assessment with verification results
5. **Present deliverables** - list all generated artifacts with locations
6. **Suggest next actions** - based on pipeline results (e.g., "Create PR", "Run integration tests", "Review IaC plan")
7. **Clean up** - remove temporary files, close telemetry backends if no other pipelines active

## Conditions & Decision Points

| Condition | Action | Reasoning |
|-----------|--------|-----------|
| Low complexity bug fix | Skip Agents 2a, 3a, 5 | Lightweight path |
| Config change | Skip Agents 2a, 3a, 5, 6, 7 | Minimal pipeline |
| Infrastructure/DevOps change | Route to Agent 8 (skip 3a/3b/3c/6) | IaC-specific pipeline |
| Clarification needed | Loop Agent 1 ↔ User (max 2) | Resolve ambiguity |
| Design rejected | Loop Agent 2 ↔ 2a (max 2) | Iterate design |
| Verification fails | Loop Agent 3c ↔ 4 (max 3) | Fix -> verify cycle |
| Input is raw requirement (no ticket) | Skip Agent 0 | No ticket to analyze |
| Multi-repo feature | Multi-repo orchestration | Coordinate across repos |

## Coordinator-and-Worker Pattern

### Context Isolation Rules
- Subagents do NOT inherit conversation history
- Orchestrator MUST pass all context in the subagent prompt:
  - Feature ID and output folder path
  - Which input files to read
  - What to produce
  - Constraints and instructions
- Subagent results returned as text - orchestrator decides next step

### Model Selection Priority
1. Explicit model override (from custom context or user)
2. Agent-configured model (from contract model_tier -> resolved model)
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

Binaries are installed to `<project_root>/observability/.bin/` - no sudo required, no Docker dependency.

### Lifecycle

```
Pipeline Start -> SessionStart hook
  -> HC-OBSERVABILITY: start otelcol-contrib + prometheus
  -> HC-OTEL-TELEMETRY: record session baseline

Agent N invocation:
  -> PreToolUse(runSubagent): snapshot pre-agent metrics
  -> Agent runs...
  -> PostToolUse(runSubagent): compute delta, append telemetry_report.md

Pipeline End -> Stop hook
  -> HC-OTEL-TELEMETRY: write pipeline summary to telemetry_report.md
  -> HC-OBSERVABILITY: stop processes (if no other pipeline active)
```

### Install Scripts (Cross-Platform)

**macOS/Linux:** `scripts/install-observability.sh`
1. Detects OS (macOS/Linux) and architecture (arm64/amd64)
2. Downloads official release binaries from GitHub Releases
3. Extracts to `observability/.bin/`
4. Verifies binary checksums
5. Makes binaries executable
6. Creates config files from templates if not present

Run modes:
- `scripts/install-observability.sh` - install both binaries
- `scripts/install-observability.sh --check` - check if binaries are present (no download)
- `scripts/install-observability.sh --json` - output status as JSON for automation

**Windows:** `scripts/install-observability.ps1`
1. Detects architecture (amd64)
2. Downloads official release binaries (`.exe`) from GitHub Releases
3. Extracts to `observability/.bin/`
4. Verifies binary presence
5. Creates config files from templates if not present

Run modes:
- `.\scripts\install-observability.ps1` - install both binaries
- `.\scripts\install-observability.ps1 -Check` - check if binaries are present
- `.\scripts\install-observability.ps1 -Json` - output status as JSON for automation

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
- Pipeline **proceeds normally** - telemetry is never blocking
- Warning logged: "Telemetry degraded - observability infrastructure not available"
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

## Approval Gate Strategy

The orchestrator supports three configurable approval gate modes, set via `orchestrator_custom_client_context.md` or onboarding answers.

| Mode | Behavior | Best For |
|------|----------|----------|
| `strict` | Human approval required at every agent handoff | Regulated industries, early adoption |
| `batch` | Approval required only at phase boundaries (design -> implementation, implementation -> verification) | Balanced teams |
| `auto` | Automatic progression, human approval only for ship recommendation (Agent 5) and destructive changes | High-trust teams, rapid iteration |

### Gate Decision Points

| Gate | `strict` | `batch` | `auto` |
|------|----------|---------|--------|
| After Ticket Analysis (Agent 0) | Ask | Auto | Auto |
| After Problem Decomposition (Agent 1) | Ask | Ask | Auto |
| After Design (Agent 2 + 2a) | Ask | Ask | Auto |
| After Scaffolding (Agent 3a) | Ask | Auto | Auto |
| After Build (Agent 3b) | Ask | Ask | Auto |
| After Testing (Agent 6) | Ask | Auto | Auto |
| After Verification (Agent 4) | Ask | Ask | Auto |
| After Fix Loop (Agent 3c) | Ask | Auto | Auto |
| Ship Recommendation (Agent 5) | Ask | Ask | Ask |
| Destructive IaC Changes (Agent 8) | Ask | Ask | Ask |

### Configuration

```markdown
## Approval Gate Strategy

approval_mode: batch   # strict | batch | auto
```

Default: `batch` (if not specified in onboarding or custom context).

## Multi-Repository Orchestration

When a feature spans multiple repositories, the orchestrator coordinates cross-repo work.

### Multi-Repo Strategy

| Phase | Strategy |
|-------|----------|
| **Dependency Ordering** | Analyze repo dependencies (shared-libs first, then services, then UI). Run pipeline in dependency order |
| **Parallel Where Safe** | Independent repos (e.g., frontend + backend with stable API contract) can run in parallel |
| **Cross-Repo Verification** | After all repos pass individual verification, run cross-repo integration check |
| **Coordinated PRs** | Group related PRs with cross-references. Link PRs via "Part of feature-X" labels |
| **Partial Failure Rollback** | If repo B fails after repo A succeeded: pause, report, ask human whether to rollback A or fix B |

### Multi-Repo Workflow

1. **Analyze repo graph** - identify which repos are affected and their dependencies
2. **Order execution** - topological sort: shared libraries -> services -> consumers -> UI
3. **Run pipeline per repo** - each repo gets its own agent pipeline (Agents 0-6)
4. **Cross-repo verification** - after individual pipelines complete:
   - Verify API contract compatibility (OpenAPI spec diffing)
   - Verify shared type/schema consistency
   - Run integration test suite (if available)
5. **Coordinated PR creation** - create linked PRs across repos with:
   - Cross-references (e.g., "Depends on org/shared-lib#42")
   - Merge order instructions
   - Combined changelog entry
6. **Rollback on partial failure** - if any repo fails:
   - Pause all in-progress repos
   - Report failure with blast radius
   - Present options: fix failed repo, rollback completed repos, or proceed with partial delivery

### Multi-Repo Conditions

| Condition | Action |
|-----------|--------|
| Single repo feature | Standard pipeline, no multi-repo overhead |
| Multi-repo, independent | Run pipelines in parallel |
| Multi-repo, dependent | Run in dependency order |
| Cross-repo API change | Add API compatibility verification step |
| Partial failure | Pause, report, ask human for decision |

## Customization Points

| Point | How Customized | Default |
|-------|---------------|---------|
| Agent sequence | Onboarding answers -> Personas, Complexity | Full pipeline |
| Model per agent | Onboarding answers -> Approved Models | Model tier mapping |
| Skip rules | `orchestrator_custom_client_context.md` | Standard complexity-based |
| Max clarification rounds | `orchestrator_custom_client_context.md` | 2 |
| Max fix iterations | `orchestrator_custom_client_context.md` | 3 |
| Observability enabled | Onboarding answers -> AI Stack | Optional (disabled if binaries missing) |
| Prometheus URL | `PROMETHEUS_URL` env var | `http://localhost:9090` |
| OTel service name | `OTEL_SERVICE` env var | `copilot-chat` |
| Model pricing | Env var / file / URL | Built-in defaults |
| Telemetry report path | Orchestrator output folder | `<output_folder>/telemetry_report.md` |
| Custom pipeline steps | `orchestrator_custom_client_context.md` | None |

