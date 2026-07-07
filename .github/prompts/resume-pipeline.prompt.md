---
description: "Resume a paused SDLC Preflight or Pipeline Generator run from the last checkpoint"
mode: "agent"
tools:
  - execute
  - read
  - edit
  - search
  - vscode/askQuestions
  - runSubagent
---

# /resume-pipeline

Resume a previously paused SDLC Pipeline workflow from its last checkpoint.

## Instructions

1. Read the checkpoint state at `onboarding-utilities/output_repos/agents-repo/.github/sdlc-pipeline/checkpoint_state.json`
2. Determine which agent was last active (`preflight` or `generator`)
3. Load the corresponding agent instructions:
   - If `preflight`: follow `.github/agents/sdlc-preflight.agent.md`
   - If `generator`: follow `.github/agents/sdlc-pipeline-generator.agent.md`
4. Resume from the last completed phase
5. If there is `pending_feedback`, incorporate it into the next phase
6. If there are `errors` marked as recoverable, attempt recovery

**If no checkpoint exists:** Tell the user no paused run was found and suggest running `/preflight` to start fresh.
