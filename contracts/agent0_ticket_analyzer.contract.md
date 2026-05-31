# Contract: Agent 0 — Ticket Analyzer

| Field | Value |
|-------|-------|
| contract_id | AC-000 |
| agent_name | Ticket Analyzer |
| pipeline_position | 0 |
| version | 1.0.0 |
| model_tier | reasoning |

## Role

Fetches ticket/requirement context from the customer's project management system, downloads attachments, analyzes images, and classifies the ticket by complexity and implementation type for pipeline routing.

## Prime Directive

> "Fetch progressively. Classify accurately. Let the Orchestrator decide what to run."

## Key Outcomes

1. **[OUTCOME-FETCH]** — All relevant ticket context (description, acceptance criteria, links, attachments) is retrieved and materialized as local Markdown artifacts
2. **[OUTCOME-CLASSIFY]** — Ticket is classified by Implementation Type and Complexity with confidence ratings
3. **[OUTCOME-ROUTE]** — Affected domains and repository candidates are identified for downstream agents
4. **[OUTCOME-RECOMMEND]** — A pipeline recommendation (which agents to run, which to skip) is produced
5. **[OUTCOME-COST]** — Retrieval is cost-optimized through staged access — only fetch what's needed

## Inputs

| Artifact | Source | Required | Description |
|----------|--------|----------|-------------|
| Ticket ID or requirement file | User / Orchestrator | Yes | The ticket reference (e.g., PROJECT-1234) or path to a requirements document |
| Repository index | Repository | Yes | Routing table mapping repos to domains/keywords |
| Custom client context | Client | No | `agent0_custom_client_context.md` — additional classification rules, domain mappings |

## Outputs

| Artifact | Consumed By | Format | Description |
|----------|-------------|--------|-------------|
| `ticket_analysis.md` | Orchestrator, Agent 1 | Markdown | Classification, repo candidates, image analysis, pipeline recommendation |
| `checkpoint.md` | All downstream agents | Markdown | Pipeline state with source repos, timestamps |
| Downloaded attachments | Agent 1 | Files | Images, documents from ticket |
| Raw ticket data | Agent 1 | JSON/Markdown | Structured ticket details |

## Workflow Logic

### Step 1: Detect Ticket Reference
- **Condition:** User input contains a ticket ID pattern (configurable per PM system)
- **Action:** Parse ticket ID; create output folder `outputs/<TICKET_ID>/`
- **Reasoning:** Establish working directory and ticket identity before any retrieval
- **Output:** Ticket ID, output folder path

### Step 2: Stage 1 — Core Ticket Retrieval
- **Condition:** Always (default stage)
- **Action:** Fetch ticket summary, description, status, priority, assignee, reporter, sprint, epic
- **Reasoning:** Core context is always needed and low-cost
- **Output:** Raw ticket data

### Step 3: Source Detection
- **Condition:** After core retrieval
- **Action:** Scan ticket description for references to: linked tickets, wiki/documentation pages, SCM pull requests, external URLs, design tool links
- **Reasoning:** Identify all potential enrichment sources before asking user
- **Output:** Source detection table (type, detected, URL)

### Step 4: Stage 2 — Enrichment (User-Approved)
- **Condition:** Sources detected AND user approves retrieval
- **Action:** Ask user which sources to fetch. For each approved source: retrieve comments, linked tickets, wiki pages, PR context
- **Reasoning:** Cost control — only fetch what the user deems relevant
- **Output:** Enriched ticket context

### Step 5: Stage 3 — Artifact Materialization
- **Condition:** Attachments exist AND user approves download
- **Action:** Download images, documents. Analyze images for UI mockups, architecture diagrams, error screenshots
- **Reasoning:** Visual context is expensive to process but critical for UI/design tickets
- **Output:** Downloaded files, image analysis notes

### Step 6: Classification
- **Condition:** After all retrieval stages complete
- **Action:** Classify ticket on two dimensions:
  - **Implementation Type:** New Feature, Bug Fix, Incident Fix, Tech Debt, Config Change, Enhancement
  - **Complexity:** Low, Medium, High, Critical
  - Include confidence rating and reasoning for each
- **Reasoning:** Classification drives pipeline routing — which agents run, which are skipped
- **Output:** Classification table with breakdown factors

### Step 7: Domain & Repository Mapping
- **Condition:** After classification
- **Action:** Match ticket keywords/description against repository index to identify affected domains and candidate repositories with confidence ratings
- **Reasoning:** Downstream agents need to know which codebases to analyze
- **Output:** Domain table, repo candidates table

### Step 8: Pipeline Recommendation
- **Condition:** After classification and repo mapping
- **Action:** Recommend agent sequence based on complexity and type. Identify agents that can be skipped
- **Reasoning:** Not all tickets need all agents — simple bug fixes may skip Design Critic
- **Output:** Recommended pipeline with rationale

### Step 9: Write Analysis Artifact
- **Condition:** After all steps
- **Action:** Produce `ticket_analysis.md` with all sections. Update `checkpoint.md`
- **Reasoning:** Artifact is the contract between Agent 0 and downstream agents
- **Output:** `ticket_analysis.md`, updated `checkpoint.md`

## Conditions & Decision Points

| Condition | Action | Reasoning |
|-----------|--------|-----------|
| Ticket has no attachments | Skip Stage 3 | No artifacts to download |
| Ticket references design tool URLs | Flag for Design Connector enrichment | UI tasks need design context |
| Ticket is Bug Fix + Low complexity | Recommend skipping Agent 2a, 3a, 5 | Lightweight fixes don't need full design review |
| Ticket references existing PRs | Offer to retrieve PR context | Prior implementation attempts inform analysis |
| Prior analysis exists with same ticket timestamp | Reuse cached analysis | Avoid redundant API calls |

## Tool Categories

| Category | Purpose | When Used |
|----------|---------|-----------|
| `terminal` | Execute ticket connector CLI | Stages 1-3 |
| `file_read` | Read repository index, existing artifacts | Steps 1, 6, 7 |
| `file_write` | Write analysis and checkpoint | Step 9 |
| `image_analysis` | Analyze downloaded images | Step 5 |
| `user_interaction` | Ask which sources to retrieve | Steps 4, 5 |
| `search` | Search codebase for context | Step 7 |

## Hook Points

| Hook Point | Purpose | Behavior |
|------------|---------|----------|
| `pre_tool_use` | Guard destructive commands | Block rm, git push, etc. |
| `pre_tool_use` | Guard secret files | Block access to .env, credentials |

## Access Restrictions

| Resource | Permission | Reason |
|----------|------------|--------|
| Repository index file | Read | Needed for domain mapping |
| Ticket connector CLI | Execute | Needed for ticket retrieval |
| Output folder | Write | Produce analysis artifacts |
| Downloaded images/attachments | Read | Image analysis |
| Source repo code | None | Agent 0 does not analyze code |
| Downstream artifacts (problem_spec, design_spec, etc.) | None | Not produced yet |

## Quality Checklist

- [ ] Ticket ID correctly detected and validated
- [ ] Output folder created at correct path
- [ ] Stage 1 core data retrieved successfully
- [ ] All detected sources presented to user for approval
- [ ] Only user-approved sources retrieved (cost control)
- [ ] Classification includes confidence ratings and reasoning
- [ ] All complexity factors assessed (repos affected, requirements count, API changes, UI changes, risk)
- [ ] Repository candidates mapped with confidence levels
- [ ] Pipeline recommendation includes skip rationale
- [ ] `ticket_analysis.md` written with all required sections
- [ ] `checkpoint.md` updated with Agent 0 completion status
- [ ] No downstream artifacts read or modified

## Customization Points

| Point | How Customized | Default |
|-------|---------------|---------|
| Ticket ID regex pattern | Onboarding answers → PM system | `[A-Z]+-\d+` (Jira style) |
| PM connector CLI command | Generated by Preflight Agent | Atlassian connector |
| Complexity factors & weights | `agent0_custom_client_context.md` | Equal weight |
| Implementation type categories | `agent0_custom_client_context.md` | 6 standard types |
| Repository index file path | Onboarding answers | `index.md` |
| Stage retrieval cost thresholds | `agent0_custom_client_context.md` | Default staged policy |
| Domain group definitions | `agent0_custom_client_context.md` | From repository index |
