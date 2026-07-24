---
description: "Run the SDLC Pipeline Generator - generates customer-specific agents, skills, hooks, and orchestrator from contracts. Checks for existing agents and reuses/enhances them."
mode: "agent"
tools:
  - execute
  - read
  - edit
  - search
  - vscode/askQuestions
  - runSubagent
---

# /generate-agents

Run the **SDLC Pipeline Generator** to create customer-specific SDLC agents from reusable contracts.

## What This Does

1. Loads all contracts from `onboarding-utilities/contracts/` and customer context from preflight outputs
2. Checks `intake-sources.md` for existing customer-defined agents - reuses and enhances where applicable
3. Determines connector integration mode per platform (MCP vs API-based from `.mcp.json` and `connector_config.md`)
5. Maps contract model tiers (reasoning/coding/fast) to customer's approved models
6. Generates agent definitions (`outputs/agents-repo/.github/agents/agent<N>_<name>.md`) with full metadata, inputs/outputs, validation, checkpointing, hooks, connector integration, and completion criteria
7. Reuses connector skills generated during preflight (`outputs/agents-repo/.github/skills/<skill>/SKILL.md` and `.github/skills/<skill>/SKILL.md`) and only regenerates if missing
8. Generates cross-platform hook scripts (`outputs/agents-repo/.github/hooks/<hook>.py`) and `hooks.json`
9. Creates custom client context templates for each agent
10. Generates workflow README, repository index, and PR reporting artifacts (`PR.md` and `pr_creation_report.md`)
11. Reuses reference implementations for observability/telemetry hooks and utilities from `onboarding-utilities/scripts/` (without modifying those source files)
12. Self-validates all outputs against contracts via `onboarding-utilities/scripts/outcome-inspector.py`

## Prerequisites

The `/preflight` command must have completed successfully first. Required outputs:

- `.github/sdlc-pipeline/preflight_report.md`
- `.github/sdlc-pipeline/codebase_scan_results.md`
- `outputs/agents-repo/.github/instructions/*.instructions.md`
- `outputs/agents-repo/index.md` (repository catalog with Service Catalogue)

## Instructions

Read and follow the full agent instructions at `.github/agents/sdlc-pipeline-generator.agent.md`.

**IMPORTANT - Execution Format:**
- You MUST announce each phase with a visible heading before starting it (single separator line above the heading only, no line below)
- You MUST show a completion status after each phase
- You MUST execute all phases sequentially (Phase 1 through Phase 9)
- You MUST NOT skip any phase unless resuming from a checkpoint
- You MUST NOT ask "Continue/Pause/Re-run" between phases - auto-continue to the next phase immediately
- You MUST display "Next Steps" at the end

**Content Quality - CRITICAL:**
- Generated agent Instructions sections MUST contain ALL steps from the contract's Workflow Logic (not generic boilerplate)
- Generated Inputs/Outputs tables MUST list the EXACT artifacts from each contract (not generic placeholders)
- Generated Quality Checklists MUST include full descriptive text from contract Key Outcomes
- The Orchestrator MUST include pipeline sequence, routing table, finalization protocol, and re-run boundaries from its contract
- Sub-agent generation framework MUST remain artifact-agnostic (agents/hooks/skills/docs/future artifact types)

**Telemetry + Hooks - CRITICAL:**
- Generated orchestrator frontmatter MUST include lifecycle hooks for `SessionStart`, `PreToolUse`, `PostToolUse`, and `Stop` exactly once each.
- Each hook entry MUST include `type`, `command`, and `timeout`.
- `observability-hook.py` is responsible only for observability process lifecycle (start/stop/health checks), not telemetry accounting.
- `otel-hook.py` is responsible only for telemetry/cost/reporting (`telemetry_report.md`, `cost_report.md`) and hook output debug context.
- Generated hooks MUST emit hook output JSON so "Hook Output" appears in debug logs.
- Complex observability/telemetry hooks and helper scripts MUST be copied/adapted from references in `onboarding-utilities/scripts/`; do not regenerate from scratch.

**Start by verifying** the preflight outputs exist. If they don't, tell the user to run `/preflight` first.

**Fresh Start:** When running `/generate-pipeline`, always start fresh from Phase 1. Reset any existing generator checkpoint state first.

**On completion:** Display the Next Steps section with instructions on how to use the generated pipeline.


