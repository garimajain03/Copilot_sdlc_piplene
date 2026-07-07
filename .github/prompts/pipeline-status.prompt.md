---
description: "Check the current status of the SDLC Pipeline — show checkpoint state, completed phases, and pending work"
mode: "agent"
tools:
  - read
---

# /pipeline-status

Show the current status of the SDLC Pipeline workflow.

## Instructions

1. Read `onboarding-utilities/output_repos/agents-repo/.github/sdlc-pipeline/checkpoint_state.json`
2. Display a summary:
   - **Active agent:** preflight or generator
   - **Completed phases:** list with timestamps
   - **Current phase:** what's next
   - **Pending feedback:** any re-run requests
   - **Errors:** any logged errors and recovery status
3. If no checkpoint file exists, report "No pipeline run in progress."

**Format the output** as a clear status table the user can quickly scan.
