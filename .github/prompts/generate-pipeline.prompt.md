---
description: "Run the SDLC Pipeline Generator - generates customer-specific agents, skills, hooks, and orchestrator into outputs/agents-repo/.github, reads preflight pipeline-state artifacts from root .github/sdlc-pipeline, and writes runtime-only temporary artifacts to root .github/sdlc-pipeline-runtime."
mode: "agent"
tools:
  - execute
  - read
  - edit
  - search
  - vscode/askQuestions
  - runSubagent
---

# /generate-pipeline

Run the **SDLC Pipeline Generator** to create customer-specific SDLC agents from reusable contracts.

## What This Does

1. Loads all contracts from `onboarding-utilities/contracts/` and customer context from preflight outputs
2. Checks `intake-sources.md` for existing customer-defined agents - reuses and enhances where applicable
3. Determines connector integration mode per platform from preflight connector inventory (`connector_inventory.json`)
4. Asks clarification questions about tools, ways of working, and standards
5. Maps contract model tiers (reasoning/coding/fast) to customer's approved models
6. Generates agent definitions (`outputs/agents-repo/.github/agents/agent<N>_<name>.md`) with full metadata, inputs/outputs, validation, checkpointing, hooks, connector integration, and completion criteria
7. Reuses preflight-generated connector skills (`outputs/agents-repo/.github/skills/<skill>/SKILL.md`) and uses sub-agents to generate any other missing required skills for the pipeline run (code/agent/test/docs/ops), without duplicating existing valid skills
8. Generates cross-platform hook scripts (`outputs/agents-repo/.github/hooks/<hook>.py`) and `hooks.json`
9. Generates `outputs/agents-repo/.github/scripts/pipeline-preflight.py` to validate connector readiness and latest Agents Repo remote code
  - Script must compute repo root from `.github/scripts` using `Path(__file__).resolve().parents[2]` (never brittle `parents[4]` assumptions)
  - Script must halt pipeline start when required credentials are missing, print missing token variables, and instruct the user to: copy `.env.template` to `.env`, fill the listed values, then rerun `start <ISSUE_ID>`
10. Ensures generated orchestrator invokes `pipeline-preflight.py` before every pipeline run, resume, and rerun continuation
11. Creates custom client context templates for each agent
12. Generates workflow README, repository index, and PR reporting artifacts (`PR.md` and `pr_creation_report.md`)
13. Reuses reference implementations for observability/telemetry hooks and utilities from `onboarding-utilities/scripts/` (without modifying those source files)
14. Self-validates all outputs against contracts via `onboarding-utilities/scripts/outcome-inspector.py`

## Prerequisites

The `/preflight` command must have completed successfully first. Required outputs:

- `.github/sdlc-pipeline/preflight_report.md`
- `.github/sdlc-pipeline/codebase_scan_results.md`
- `outputs/agents-repo/.github/instructions/*.instructions.md`
- `.github/sdlc-pipeline/connector_inventory.json`
- `outputs/agents-repo/.github/skills/**/SKILL.md`
- `.github/skills/**/SKILL.md`
- `outputs/agents-repo/index.md` (repository catalog with Service Catalogue)
- Connector auth must be ready (API encrypted tokens present; MCP OAuth/token prerequisites completed)

## Instructions

Read and follow the full agent instructions at `.github/agents/sdlc-pipeline-generator.agent.md`.

**Output path rule (MANDATORY):**
- Generated agents/hooks/docs must be created under `outputs/agents-repo/.github/`.
- Pipeline state artifacts must be written under root `.github/sdlc-pipeline/`.
- Skills may be reused from both `outputs/agents-repo/.github/skills/` and root `.github/skills/`; generate only the missing required set.
- Do NOT create or write `outputs/agents-repo/.github/sdlc-pipeline/`.
- If `outputs/agents-repo/.github/sdlc-pipeline/` is produced during generation, treat it as a generation failure and regenerate until all pipeline-state artifacts are only under root `.github/sdlc-pipeline/`.
- Use `workspace_mode` from preflight context to resolve repository paths in generated content (default submodules vs custom parallel app repos).

**IMPORTANT - Execution Format:**
- You MUST announce each phase with a visible heading before starting it (single separator line above the heading only, no line below)
- You MUST show a completion status after each phase
- You MUST print phase updates in real time (do not print all phase status lines only after the full run)
- You MUST print `Phase Status: in_progress` immediately after each phase heading, before doing phase work
- You MUST print `Phase Status: completed` (or `blocked`) for that same phase before printing the next phase heading
- You MUST execute all phases sequentially (Phase 1 through Phase 9)
- You MUST NOT skip any phase unless resuming from a checkpoint
- You MUST NOT ask "Continue/Pause/Re-run" between phases - auto-continue to the next phase immediately
- You MUST display "Next Steps" at the end
- You MUST NOT emit a batched phase completion list at the end as a substitute for real-time phase logs

**Content Quality - CRITICAL:**
- Generated agent Instructions sections MUST contain ALL steps from the contract's Workflow Logic (not generic boilerplate)
- Generated Inputs/Outputs tables MUST list the EXACT artifacts from each contract (not generic placeholders)
- Generated Quality Checklists MUST include full descriptive text from contract Key Outcomes
- The Orchestrator MUST include pipeline sequence, routing table, finalization protocol, and re-run boundaries from its contract
- Sub-agent generation framework MUST remain artifact-agnostic (agents/hooks/skills/docs/future artifact types)
- Generated outputs for each run MUST be created under `outputs/agents-repo/outputs/<FEATURE_ID>/` (for example: checkpoint, tracker, telemetry_report.md, cost_report.md)
- Do NOT allow placeholder signatures in generated agents/orchestrator (for example: "The following workflow logic is applied exactly from the contract:" or "Key Outcomes to satisfy:")

**Telemetry + Hooks - CRITICAL:**
- Generated orchestrator frontmatter MUST include lifecycle hooks for `SessionStart`, `PreToolUse`, `PostToolUse`, and `Stop` exactly once each.
- Each hook entry MUST include `type`, `command`, and `timeout`.
- `observability-hook.py` is responsible only for observability process lifecycle (start/stop/health checks), not telemetry accounting.
- `otel-hook.py` is responsible only for telemetry/cost/reporting (`telemetry_report.md`, `cost_report.md`) and hook output debug context.
- Generated hooks MUST emit hook output JSON so "Hook Output" appears in debug logs.
- Complex observability/telemetry hooks and helper scripts MUST be copied/adapted from references in `onboarding-utilities/scripts/`; do not regenerate from scratch.
- Generated `outputs/agents-repo/.github/scripts/install-observability.sh` and `outputs/agents-repo/.github/scripts/install-observability.ps1` MUST be copied from `onboarding-utilities/scripts/` as full installers with download/extract/verify behavior (no placeholders or thin wrappers).

**Start by verifying** the preflight outputs exist. If they don't, tell the user to run `/preflight` first.

**Fresh Start:** When running `/generate-pipeline`, always start fresh from Phase 1. Reset any existing generator checkpoint state first.

**Mandatory Pre-checks before Phase 1 work:**
- Verify connector auth readiness:
  - `python onboarding-utilities/scripts/connector-bootstrap.py verify-auth --output-root outputs/agents-repo --allow-dotenv-fallback --fail-on-missing`
- Verify latest remote code is fetched and workspace is up to date:
  - `git fetch --all --prune`
  - Submodule fetch must be guarded: skip when `.gitmodules` is absent/empty, and treat recursive nested fetch failures as warnings unless top-level submodule metadata is invalid
- If these checks fail, stop and show remediation before generating any files.

**Generated orchestrator requirement (MANDATORY):**
- Generated orchestrator instructions must call `.github/scripts/pipeline-preflight.py` via Python before any run starts, before resume execution, and before continuing after rerun reset.
- That preflight call must initialize `outputs/<FEATURE_ID>/` with `checkpoint.md` and `orchestration_tracker.md` so `start <ISSUE_ID>` immediately routes agents and telemetry to the ticket-specific output folder.

**On completion:** Display the Next Steps section with instructions on how to use the generated pipeline.



