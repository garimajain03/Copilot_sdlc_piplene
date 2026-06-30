---
description: "Run the SDLC Pipeline Generator — generates customer-specific agents, skills, hooks, and orchestrator from contracts. Checks for existing agents and reuses/enhances them."
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

1. Loads all contracts from `contracts/` and customer context from preflight outputs
2. Checks `intake-sources.md` for existing customer-defined agents — reuses and enhances where applicable
3. Determines connector integration mode per platform (MCP vs API-based from `.mcp.json` and `connector_config.md`)
4. Asks clarification questions about tools, ways of working, and standards
5. Maps contract model tiers (reasoning/coding/fast) to customer's approved models
6. Generates agent definitions (`.github/agents/agent<N>_<name>.md`) with full metadata, inputs/outputs, validation, checkpointing, and completion criteria
7. Generates connector skill definitions only for API-based platforms (`.github/skills/<skill>/SKILL.md`)
8. Generates cross-platform hook scripts (`.github/hooks/<hook>.py`) and `hooks.json`
9. Creates custom client context templates for each agent
10. Generates workflow README and repository index
11. Self-validates all outputs against contracts via `scripts/outcome-inspector.py`

## Prerequisites

The `/preflight` command must have completed successfully first. Required outputs:

- `.github/sdlc-pipeline/preflight_report.md`
- `.github/sdlc-pipeline/codebase_scan_results.md`
- `.github/instructions/*.instructions.md`
- `index.md` (repository catalog with Service Catalogue)

## Instructions

Read and follow the full agent instructions at `.github/agents/sdlc-pipeline-generator.agent.md`.

**Start by verifying** the preflight outputs exist. If they don't, tell the user to run `/preflight` first.

**Checkpoint:** Check for existing state at `.github/sdlc-pipeline/checkpoint_state.json`. If found for agent `generator`, resume from the last completed phase. If not, start fresh from Phase 1.

**On completion:** Report the generation summary and tell the user their SDLC pipeline is ready.
