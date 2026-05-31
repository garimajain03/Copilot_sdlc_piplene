---
description: "Re-run a specific phase of the SDLC Pipeline with feedback — provide the phase name and your feedback"
mode: "agent"
tools:
  - execute
  - read
  - edit
  - search
  - vscode/askQuestions
  - runSubagent
---

# /rerun-phase

Re-run a specific phase of the SDLC Pipeline with user feedback.

## Usage

Provide the phase to re-run and your feedback. Examples:

- "Phase 4 Code Scan — scan repo-X with deeper analysis for testing patterns"
- "Phase 4 Agent Generation — regenerate Agent 3b with stricter type checking"
- "Phase 6 Hook Generation — add custom pre-commit hook for formatting"

## Instructions

1. Read the checkpoint at `.github/sdlc-pipeline/checkpoint_state.json`
2. Identify the target phase from the user's message
3. Record the feedback:
   ```bash
   python3 scripts/checkpoint-manager.py feedback \
     --agent <preflight|generator> \
     --feedback "<user's feedback>" \
     --phase "<target phase>" \
     --state-file .github/sdlc-pipeline/checkpoint_state.json
   ```
4. Reset that phase and re-execute it following the corresponding agent instructions:
   - If preflight phase: follow `.github/agents/sdlc-preflight.agent.md`
   - If generator phase: follow `.github/agents/sdlc-pipeline-generator.agent.md`
5. After re-running, continue with subsequent phases or ask if user wants to pause

**If no checkpoint exists:** Tell the user no pipeline run is active. Suggest running `/preflight` first.
