# Contract Schema - SDLC Pipeline Bundle

> Defines the required structure for all Agent, Skill, and Hook contracts.
> Contracts are the reusable, tools-agnostic blueprints that the Pipeline Generator uses to produce customer-specific agent definitions.

## Agent Contract Schema

Every agent contract MUST contain the following sections in order:

### 1. Header Table

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `contract_id` | String | Yes | Unique ID (e.g., `AC-001`) |
| `agent_name` | String | Yes | Human-readable name |
| `pipeline_position` | Number | Yes | Order in pipeline (0-6, with sub-positions like 2a, 3a) |
| `version` | SemVer | Yes | Contract version |
| `model_tier` | Enum | Yes | `reasoning` / `coding` / `fast` - resolved to specific model at generation time |
| `argument_hint` | String | Yes | Brief description of expected agent arguments/inputs |

### 2. Role & Prime Directive

- **Role:** One-paragraph summary of what this agent does
- **Prime Directive:** Single imperative sentence - the agent's north star

### 3. Key Outcomes

What this agent MUST achieve (not how). List of outcome statements:

```markdown
## Key Outcomes
1. [OUTCOME-1] - Description
2. [OUTCOME-2] - Description
```

### 4. Inputs

| Artifact | Source | Required | Description |
|----------|--------|----------|-------------|
| Name | Which agent/user provides it | Yes/No | What it contains |

#### Input Validation

Define validation rules for each input:
- Required inputs: verify existence and non-empty content
- Format validation: check expected structure (Markdown sections, JSON schema, etc.)
- Cross-reference validation: verify referenced artifacts exist
- On validation failure: halt with clear error message (required) or warn and continue (optional)

### 5. Outputs

| Artifact | Consumed By | Format | Description |
|----------|-------------|--------|-------------|
| Name | Which agents use it | Markdown/Code/etc. | What it contains |

#### Output Handling

Define how outputs are managed:
- Write location: exact path where output is written
- Validation: how to verify output quality before handoff
- Error handling: what happens if output generation fails
- Downstream notification: how consuming agents know output is ready

### 6. Workflow Logic

Step-by-step reasoning flow. Technology-agnostic instructions for what the agent should do:

```markdown
## Workflow Logic
### Step 1: [Name]
- **Condition:** When/If statement
- **Action:** What to do
- **Reasoning:** Why this step matters
- **Output:** What this step produces
```

### 7. Conditions & Decision Points

Explicit branching logic:

```markdown
## Conditions & Decision Points
| Condition | Action | Reasoning |
|-----------|--------|-----------|
| If X | Do Y | Because Z |
```

### 8. Tool Categories

NOT specific tools - categories of capabilities needed:

| Category | Purpose | Examples |
|----------|---------|----------|
| `file_read` | Read source files | read_file, cat, etc. |
| `file_write` | Create/edit files | create_file, edit, etc. |
| `terminal` | Execute commands | run_in_terminal, exec, etc. |
| `search` | Search codebase | grep, semantic_search, etc. |
| `user_interaction` | Ask user questions | askQuestions, prompt, etc. |
| `image_analysis` | Analyze images | viewImage, etc. |

### 9. Hook Points

Where hooks should fire (not which specific hooks):

| Hook Point | Purpose | Behavior |
|------------|---------|----------|
| `pre_tool_use` | Before any tool execution | Guard, validate, block |
| `post_tool_use` | After tool execution | Lint, format, validate |
| `pre_agent` | Before agent starts | Setup, context loading |
| `post_agent` | After agent completes | Cleanup, metrics |

### 10. Access Restrictions

| Resource | Permission | Reason |
|----------|------------|--------|
| What files/artifacts | read/write/none | Why |

### 11. Quality Checklist

Pre-completion checklist items. Agent MUST verify all before declaring done.

### 12. Checkpointing Strategy

Define what state is saved and when for resume/re-run support:

| Data | When Saved | Purpose |
|------|-----------|---------|
| What is saved | When (after step X, on error, etc.) | Why it needs persisting |

### 13. Resume Protocol

Define how the agent resumes from a saved checkpoint:
- How to detect existing checkpoint
- Which steps to skip on resume
- How to validate previously produced outputs still exist
- How to inform the user about resume state

### 14. Re-run Protocol

Define how the agent handles a re-run with customer feedback:
- How to accept feedback for the re-run
- Which state to reset
- Which downstream artifacts to invalidate
- How to incorporate feedback into re-execution

### 15. Completion Criteria

Explicit conditions that must ALL be true for the agent to be considered done:
- All outputs exist and are non-empty
- Quality checklist fully satisfied
- No blocking errors remain
- Output validation passed

### 16. Customization Points

Where client-specific context can modify behavior:

| Point | How Customized | Default |
|-------|---------------|---------|
| Description | Via onboarding answers or custom context file | Default value |

### 17. Hook Points (with Configuration)

Where hooks should fire, including full hook configuration:

| Hook Point | Purpose | Behavior | Contract Reference |
|------------|---------|----------|--------------------|
| `pre_tool_use` | Before any tool execution | Guard, validate, block | HC-GUARD-CMD |
| `post_tool_use` | After tool execution | Lint, format, validate | HC-LINT |

---

## Skill Contract Schema

| Field | Type | Required |
|-------|------|----------|
| `contract_id` | String | Yes |
| `skill_name` | String | Yes |
| `category` | Enum | Yes - `ticket_management`, `scm`, `design`, `testing`, `observability` |
| `version` | SemVer | Yes |

Sections: Role, Capabilities (abstract), Commands (generic), Input/Output, Customization Points.

---

## Hook Contract Schema

| Field | Type | Required |
|-------|------|----------|
| `contract_id` | String | Yes |
| `hook_name` | String | Yes |
| `event` | Enum | Yes - `pre_tool_use`, `post_tool_use`, `session_start`, `session_stop`, `user_prompt` |
| `version` | SemVer | Yes |

Sections: Purpose, Trigger Conditions, Guard Logic, Exit Codes, Customization Points.

---

## Exit Code Convention (Hooks)

| Code | Meaning |
|------|---------|
| `0` | Passed - proceed normally |
| `1` | Error - log but don't block |
| `2` | Blocked - stop tool execution, feed error to agent |

