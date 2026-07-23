---
description: "Run the SDLC Preflight Agent - validates onboarding answers, asks workspace mode (Default/Custom), bootstraps selected repository layout, scans repositories, writes pipeline state artifacts to root .github/sdlc-pipeline, and writes runtime-only temporary artifacts to root .github/sdlc-pipeline-runtime"
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
2. Treats `intake-sources.md` as read-only and MUST NOT modify the file; uses values as provided
3. Reads integration mechanism per platform from `intake-sources.md` (MCP vs API-based Connector Skills) and MUST NOT ask again in chat unless a platform value is missing/ambiguous
4. If PM system is `Other`, reads `PM/Requirements Name` and uses that exact connector name during preflight generation
5. Generates connector artifacts in preflight (`.mcp.json`, connector inventory/config, connector skills, API connector bundles)
6. Detects MCP auth mechanism (OAuth or token) and generates authentication instructions
7. Securely collects API connector tokens, encrypts them, and stores encrypted env values
8. Runs mandatory connector auth verification and blocks Phase 2 completion until authentication is ready
9. Provides explicit API/MCP authentication instructions and pauses cleanly when auth is incomplete
10. Resumes from Phase 2 after user completes token/OAuth steps and runs `/resume-pipeline`
11. Asks for workspace structure and applies one mutually exclusive mode:
  - Default: Agents Monorepo and Submodules
  - Custom: Agents and Repositories in Parallel Workspace
11. Collects the customer's repository list
12. Bootstraps workspace under `outputs/` via `onboarding-utilities/scripts/workspace-bootstrap.py`
13. Smart-scans each repo for structure, dependencies, and patterns via `onboarding-utilities/scripts/repo-scanner.py`
14. Incrementally maintains `index.md` with repository catalog and Service Catalogue
15. Generates `outputs/agents-repo/.github/instructions/<repo>.instructions.md` per repo via `onboarding-utilities/scripts/instructions-generator.py`
16. Generates `copilot-instructions.md` using scanned repository context, including per-repo files in each cloned repo at `<repo>/.github/copilot-instructions.md`
17. Generates `setup.sh` (macOS/Linux) and `setup.ps1` (Windows) - both include prerequisite installation, workspace config, submodule init, and validation
18. Renders setup scripts from `templates/setup_template.sh.hbs` and `templates/setup_template.ps1.hbs` (no minimal synthesized replacements), preserving observability install and config copy behavior
19. Generates `.env.template` in `outputs/agents-repo`, writes `.env` and `.env.encrypted` at repository root, and generates `.gitmodules` (if default workspace)
20. Runs the appropriate setup script to install all prerequisites
21. Self-validates all outputs via `onboarding-utilities/scripts/outcome-inspector.py`
22. Writes `preflight_report.md` with results and next steps

## Instructions

Read and follow the full agent instructions at `.github/agents/sdlc-preflight.agent.md`.

**Output path rule (MANDATORY):**
- Generate pipeline state only under root `.github/sdlc-pipeline/`.
- Generate connector skills under both `outputs/agents-repo/.github/skills/` and root `.github/skills/`.
- Keep generated agents/hooks/instructions under `outputs/agents-repo/.github/...`.
- Generate setup scripts only at `outputs/agents-repo/setup.sh` and `outputs/agents-repo/setup.ps1`.
- Do NOT generate `setup.sh` or `setup.ps1` in any other path.

**IMPORTANT - Execution Format:**
- You MUST announce each phase with a visible bold heading before starting it, using `## Phase N: <Phase Name>`
- You MUST show phase status lines (`in_progress`, `completed`, or `blocked`) for each phase
- Completed phases should include `✅`; blocked phases should include `⏸️`
- You MUST print phase updates in real time (do not print all phase status lines only after the full run)
- You MUST print `Phase Status: in_progress` immediately after each phase heading, before running phase work
- You MUST print `Phase Status: completed` (or `blocked`) for that same phase before printing the next phase heading
- You MUST execute all phases sequentially (Phase 1 through Phase 10)
- You MUST NOT skip any phase unless resuming from a checkpoint
- You MUST NOT ask "Continue/Pause/Re-run" between phases - auto-continue to the next phase immediately
- You MUST display a phase summary ledger and then "Next Steps" at the end
- The final phase summary ledger is supplemental and MUST NOT replace real-time per-phase status output

**Start by reading** `intake-sources.md` in the workspace root. If it doesn't exist, ask the user to provide it or point to its location.

**Intake Source Rule (MANDATORY):**
- `intake-sources.md` is read-only input.
- Do NOT edit, rewrite, or auto-correct the file.
- Use values as present; if something is missing/ambiguous, ask clarifying questions and store resolved data in generated artifacts instead.

**Fresh Start:** When running `/preflight`, always start fresh from Phase 1. Reset any existing checkpoint state first.

**Connector Auth Gate (MANDATORY):**
- Run `python onboarding-utilities/scripts/connector-bootstrap.py verify-auth --output-root outputs/agents-repo --allow-dotenv-fallback --fail-on-missing` during Phase 2.
- If blocked, do not mark Phase 2 complete; show auth instructions (`api_auth_instructions.md` and/or `mcp_auth_instructions.md`) and pause with checkpoint.
- On `/resume-pipeline`, re-run Phase 2 verification first, then continue to Phase 3 only when it returns unblocked.
- If user has provided tokens in root `.env` (fallback) or root `.env.encrypted` (preferred), verification should recognize readiness.

**Secret handling (MANDATORY):**
- Never ask for token values in chat popups.
- Token values must be entered only through secure terminal prompts (for example `getpass` in `collect-token`).

**On completion:** Display the Next Steps section telling the user to run `/generate-pipeline` next.


