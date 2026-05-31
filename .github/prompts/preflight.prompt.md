---
description: "Run the SDLC Preflight Agent — validates onboarding answers, clones and scans repositories, generates setup scripts and instruction files"
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

1. Validates `customer_onboarding_answers.md` against the schema
2. Collects the customer's repository list
3. Clones repositories via `scripts/scm-bootstrap.py`
4. Smart-scans each repo for structure, dependencies, and patterns via `scripts/repo-scanner.py`
5. Generates `.github/instructions/<repo>.instructions.md` per repo via `scripts/instructions-generator.py`
6. Generates `setup.sh`, connector configs, hook scripts, and `hooks.json`
7. Self-validates all outputs via `scripts/outcome-inspector.py`
8. Writes `preflight_report.md` with results and next steps

## Instructions

Read and follow the full agent instructions at `.github/agents/sdlc-preflight.agent.md`.

**Start by reading** `customer_onboarding_answers.md` in the workspace root. If it doesn't exist, ask the user to provide it or point to its location.

**Checkpoint:** Check for existing state at `.github/sdlc-pipeline/checkpoint_state.json`. If found, resume from the last completed phase. If not, start fresh from Phase 1.

**On completion:** Tell the user to run `/generate-pipeline` next.
