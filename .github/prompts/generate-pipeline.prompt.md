---
description: "Run the SDLC Pipeline Generator - generates customer-specific agents, skills, hooks, and orchestrator into outputs/agents-repo/.github, reads shared preflight artifacts from outputs/agents-repo/.github/sdlc-pipeline, and writes runtime-only temporary artifacts to .github/sdlc-pipeline-runtime."
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
3. Determines connector integration mode per platform (MCP vs API-based from `.mcp.json` and `connector_config.md`)
4. Asks clarification questions about tools, ways of working, and standards
5. Maps contract model tiers (reasoning/coding/fast) to customer's approved models
6. Generates agent definitions (`outputs/agents-repo/.github/agents/agent<N>_<name>.md`) with full metadata, inputs/outputs, validation, checkpointing, hooks, connector integration, and completion criteria
7. Generates connector skill definitions only for API-based platforms (`outputs/agents-repo/.github/skills/<skill>/SKILL.md`)
8. Generates cross-platform hook scripts (`outputs/agents-repo/.github/hooks/<hook>.py`) and `hooks.json`
9. Creates custom client context templates for each agent
10. Generates workflow README and repository index
11. Self-validates all outputs against contracts via `onboarding-utilities/scripts/outcome-inspector.py`

## Prerequisites

The `/preflight` command must have completed successfully first. Required outputs:

- `outputs/agents-repo/.github/sdlc-pipeline/preflight_report.md`
- `outputs/agents-repo/.github/sdlc-pipeline/codebase_scan_results.md`
- `outputs/agents-repo/.github/instructions/*.instructions.md`
- `outputs/agents-repo/index.md` (repository catalog with Service Catalogue)

## Instructions

Read and follow the full agent instructions at `.github/agents/sdlc-pipeline-generator.agent.md`.

**Output path rule (MANDATORY):**
- Final generated artifacts (agents, hooks, skills, docs) must be created under `outputs/agents-repo/.github/`.
- Reusable/shared state artifacts consumed by other agents (for example checkpoint_state, preflight_report, onboarding_context, connector_config) must be created under `outputs/agents-repo/.github/sdlc-pipeline/`.
- Non-reused runtime artifacts (for example generation_report, pipeline_config, runtime scratch files) may be created under `.github/sdlc-pipeline-runtime/`.
- Use `workspace_mode` from preflight context to resolve repository paths in generated content (default submodules vs custom parallel app repos).

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

**Start by verifying** the preflight outputs exist. If they don't, tell the user to run `/preflight` first.

**Fresh Start:** When running `/generate-pipeline`, always start fresh from Phase 1. Reset any existing generator checkpoint state first.

**On completion:** Display the Next Steps section with instructions on how to use the generated pipeline.



