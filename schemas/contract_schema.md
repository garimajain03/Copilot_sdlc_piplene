# Contract Schema — SDLC Pipeline Bundle

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
| `model_tier` | Enum | Yes | `reasoning` / `coding` / `fast` — resolved to specific model at generation time |

### 2. Role & Prime Directive

- **Role:** One-paragraph summary of what this agent does
- **Prime Directive:** Single imperative sentence — the agent's north star

### 3. Key Outcomes

What this agent MUST achieve (not how). List of outcome statements:

```markdown
## Key Outcomes
1. [OUTCOME-1] — Description
2. [OUTCOME-2] — Description
```

### 4. Inputs

| Artifact | Source | Required | Description |
|----------|--------|----------|-------------|
| Name | Which agent/user provides it | Yes/No | What it contains |

### 5. Outputs

| Artifact | Consumed By | Format | Description |
|----------|-------------|--------|-------------|
| Name | Which agents use it | Markdown/Code/etc. | What it contains |

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

NOT specific tools — categories of capabilities needed:

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

### 12. Customization Points

Where client-specific context can modify behavior:

| Point | How Customized | Default |
|-------|---------------|---------|
| Description | Via onboarding answers or custom context file | Default value |

---

## Skill Contract Schema

| Field | Type | Required |
|-------|------|----------|
| `contract_id` | String | Yes |
| `skill_name` | String | Yes |
| `category` | Enum | Yes — `ticket_management`, `scm`, `design`, `testing`, `observability` |
| `version` | SemVer | Yes |

Sections: Role, Capabilities (abstract), Commands (generic), Input/Output, Customization Points.

---

## Hook Contract Schema

| Field | Type | Required |
|-------|------|----------|
| `contract_id` | String | Yes |
| `hook_name` | String | Yes |
| `event` | Enum | Yes — `pre_tool_use`, `post_tool_use`, `session_start`, `session_stop`, `user_prompt` |
| `version` | SemVer | Yes |

Sections: Purpose, Trigger Conditions, Guard Logic, Exit Codes, Customization Points.

---

## Exit Code Convention (Hooks)

| Code | Meaning |
|------|---------|
| `0` | Passed — proceed normally |
| `1` | Error — log but don't block |
| `2` | Blocked — stop tool execution, feed error to agent |
