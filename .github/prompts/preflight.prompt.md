---
description: "Run the SDLC Preflight Agent — validates onboarding answers, asks workspace mode (Default/Custom), bootstraps selected repository layout, scans repositories, and generates preflight outputs into onboarding-utilities/output_repos/agents-repo"
mode: "agent"
tools:
  - execute
  - read
  - edit
  - search
  - vscode/askQuestions
  - runSubagent
---

# /preflight

Run the **SDLC Preflight Agent** to prepare a customer's project for the SDLC Pipeline.

## What This Does

1. Validates `intake-sources.md` against the schema
2. Reads integration mechanism per platform from `intake-sources.md` (MCP vs API-based Connector Skills) and MUST NOT ask again in chat unless a platform value is missing/ambiguous
3. Generates `.mcp.json` for MCP-selected platforms
4. Asks for workspace structure and applies one mutually exclusive mode:
  - Default: Agents Monorepo and Submodules
  - Custom: Agents and Repositories in Parallel Workspace
5. Collects the customer's repository list
6. Bootstraps workspace under `onboarding-utilities/output_repos/` via `onboarding-utilities/scripts/workspace-bootstrap.py`
7. Smart-scans each repo for structure, dependencies, and patterns via `onboarding-utilities/scripts/repo-scanner.py`
8. Incrementally maintains `index.md` with repository catalog and Service Catalogue
9. Generates `.github/instructions/<repo>.instructions.md` per repo under `onboarding-utilities/output_repos/agents-repo/.github/instructions/` via `onboarding-utilities/scripts/instructions-generator.py`
10. Generates `copilot-instructions.md` using scanned repository context
11. Generates `setup.sh` (macOS/Linux) and `setup.ps1` (Windows) — both include prerequisite installation, workspace config, submodule init, and validation
12. Generates connector configs, `.env.template`, and `.gitmodules` (if default workspace)
13. Runs the appropriate setup script to install all prerequisites
14. Self-validates all outputs via `onboarding-utilities/scripts/outcome-inspector.py`
15. Writes `preflight_report.md` with results and next steps

## Instructions

Read and follow the full agent instructions at `.github/agents/sdlc-preflight.agent.md`.

**Output path rule (MANDATORY):**
- The onboarding repository root `.github/` folder must remain unchanged.
- All preflight-generated pipeline artifacts must be written in the selected workspace under `onboarding-utilities/output_repos/agents-repo` (especially `onboarding-utilities/output_repos/agents-repo/.github/...`).

**IMPORTANT — Execution Format:**
- You MUST announce each phase with a visible heading before starting it (single separator line above the heading only, no line below)
- You MUST show a completion status after each phase
- You MUST execute all phases sequentially (Phase 1 through Phase 10)
- You MUST NOT skip any phase unless resuming from a checkpoint
- You MUST NOT ask "Continue/Pause/Re-run" between phases — auto-continue to the next phase immediately
- You MUST display "Next Steps" at the end

**Start by reading** `intake-sources.md` in the workspace root. If it doesn't exist, ask the user to provide it or point to its location.

**Fresh Start:** When running `/preflight`, always start fresh from Phase 1. Reset any existing checkpoint state first.

**On completion:** Display the Next Steps section telling the user to run `/generate-pipeline` next.
