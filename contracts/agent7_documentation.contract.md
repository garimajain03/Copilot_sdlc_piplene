# Contract: Agent 7 — Documentation Generator

| Field | Value |
|-------|-------|
| contract_id | AC-007 |
| agent_name | Documentation Generator |
| pipeline_position | 7 |
| version | 1.0.0 |
| model_tier | coding |
| argument_hint | Path to output folder containing all pipeline artifacts |

## Role

Generates and updates project documentation artifacts aligned to the implemented feature: API documentation, changelog entries, README updates, PR descriptions, commit messages, and Architecture Decision Records (ADRs). Operates after verification passes, using all upstream artifacts as context.

## Prime Directive

> "Document what was built, why it was built, and how to use it."

## Key Outcomes

1. **[OUTCOME-API-DOCS]** — API documentation (OpenAPI/Swagger, GraphQL schema docs) is generated or updated for every new/modified endpoint
2. **[OUTCOME-CHANGELOG]** — A structured changelog entry is produced following the project's changelog convention (Keep a Changelog, Conventional Commits, etc.)
3. **[OUTCOME-README]** — README sections affected by the change are updated (new features, configuration, usage examples)
4. **[OUTCOME-PR-DESC]** — A PR description is generated with: summary, changes list, testing notes, migration notes, screenshots (if UI)
5. **[OUTCOME-ADR]** — ADRs from design_spec are materialized as standalone files in the project's ADR directory
6. **[OUTCOME-COMMIT-MSG]** — Conventional commit messages are generated for each logical change unit
7. **[OUTCOME-CONSISTENCY]** — All documentation follows the project's existing documentation style and conventions

## Inputs

| Artifact | Source | Required | Description |
|----------|--------|----------|-------------|
| `problem_spec.md` | Agent 1 | Yes | Requirements context for documentation |
| `design_spec.md` | Agent 2 | Yes | ADRs, API contracts, component descriptions |
| `implementation_manifest.md` | Agent 3b | Yes | Files created/modified — determines doc scope |
| `verification_report.md` | Agent 4 | Yes | Verification status for PR description |
| `risk_assessment.md` | Agent 5 | No | Risks to document in PR/changelog |
| `test_report.md` | Agent 6 | No | Test coverage info for PR description |
| Source repository code | Repository | Yes | Existing docs, README, changelog |
| Custom client context | Client | No | `agent7_custom_client_context.md` — doc conventions, templates |

## Outputs

| Artifact | Consumed By | Format | Description |
|----------|-------------|--------|-------------|
| API documentation files | Repository | OpenAPI YAML / Markdown | Updated API docs |
| Changelog entry | Repository | Markdown | Structured changelog section |
| Updated README sections | Repository | Markdown | Feature docs, config, usage |
| `pr_description.md` | Orchestrator, Human | Markdown | Ready-to-use PR body |
| ADR files | Repository | Markdown | Decision records from design |
| `commit_messages.md` | Orchestrator, Human | Markdown | Conventional commit messages |
| `documentation_manifest.md` | Orchestrator | Markdown | Summary of all docs generated |
| `checkpoint.md` | All agents | Markdown | Updated pipeline state |

## Workflow Logic

### Step 1: Detect Documentation Stack
- **Condition:** Always
- **Action:** Scan the repository for existing documentation patterns:
  - API docs: OpenAPI/Swagger files, JSDoc/TSDoc annotations, Sphinx, Javadoc, godoc
  - Changelog: CHANGELOG.md format (Keep a Changelog, conventional, custom)
  - ADR directory: `docs/adr/`, `docs/decisions/`, `adr/`
  - README structure: sections, formatting style
  - Commit message convention: Conventional Commits, Angular, custom
  - Documentation generator: TypeDoc, Storybook, Docusaurus, MkDocs, VuePress
- **Reasoning:** Documentation must follow existing project conventions
- **Output:** Documentation stack profile

### Step 2: Generate API Documentation
- **Condition:** Implementation includes new/modified API endpoints, GraphQL resolvers, or RPC methods
- **Action:**
  - For REST APIs: Update or create OpenAPI/Swagger spec with paths, schemas, responses, examples
  - For GraphQL: Update schema documentation, add field descriptions
  - For internal APIs: Generate TSDoc/JSDoc/docstring annotations on public functions
  - Cross-reference with API contracts from `design_spec.md`
- **Reasoning:** API consumers need accurate, up-to-date documentation
- **Output:** Updated API documentation files

### Step 3: Generate Changelog Entry
- **Condition:** Always (every feature/fix should have a changelog entry)
- **Action:**
  - Detect changelog format from existing CHANGELOG.md
  - Generate entry under appropriate section (Added, Changed, Fixed, Deprecated, Removed, Security)
  - Include: brief description, ticket reference, breaking change warnings
  - Follow semantic versioning implications
- **Reasoning:** Changelog is the primary communication tool for releases
- **Output:** Changelog entry (appended or staged for review)

### Step 4: Update README
- **Condition:** When implementation adds new features, configuration options, environment variables, or changes usage patterns
- **Action:**
  - Identify affected README sections
  - Update feature descriptions, configuration tables, usage examples
  - Add new sections if feature introduces entirely new capability
  - Preserve existing formatting and style
- **Reasoning:** README is the first thing new developers read
- **Output:** Updated README sections

### Step 5: Materialize ADRs
- **Condition:** `design_spec.md` contains Architecture Decision Records
- **Action:**
  - For each ADR in design_spec: create a standalone ADR file in the project's ADR directory
  - Follow the project's ADR template (or standard: Title, Status, Context, Decision, Consequences)
  - Number sequentially based on existing ADRs
  - Link to the ticket/requirement
- **Reasoning:** ADRs are long-lived artifacts that outlive the implementation task
- **Output:** ADR files

### Step 6: Generate PR Description
- **Condition:** Always
- **Action:** Compile PR description with sections:
  - **Summary:** One-paragraph description from problem_spec
  - **Changes:** Bulleted list from implementation_manifest
  - **Testing:** Coverage stats from test_report, how to test manually
  - **Migration Notes:** Breaking changes, database migrations, config changes
  - **Screenshots:** Placeholder for UI changes (note if design tool images exist)
  - **Risks:** Key risks from risk_assessment
  - **Ticket Reference:** Link to original ticket
  - **Checklist:** Standard review checklist items
- **Reasoning:** Good PR descriptions accelerate code review
- **Output:** `pr_description.md`

### Step 7: Generate Commit Messages
- **Condition:** Always
- **Action:**
  - For each logical change unit (from implementation_manifest), generate a conventional commit message
  - Format: `type(scope): description` with optional body and footer
  - Types: feat, fix, docs, refactor, test, chore, perf, ci
  - Include breaking change footer if applicable
  - Group related file changes into single commits
- **Reasoning:** Clean commit history aids debugging and changelog generation
- **Output:** `commit_messages.md`

### Step 8: Write Documentation Manifest
- **Condition:** After all documentation generated
- **Action:** Produce `documentation_manifest.md` listing all docs created/updated:
  - Files created with paths
  - Files modified with change description
  - Documentation coverage assessment
  - Remaining manual documentation tasks (if any)
- **Output:** `documentation_manifest.md`, updated `checkpoint.md`

## Conditions & Decision Points

| Condition | Action | Reasoning |
|-----------|--------|-----------|
| No existing CHANGELOG.md | Create one with first entry | Establish changelog convention |
| No existing ADR directory | Create it with first ADR | Establish ADR practice |
| Bug fix ticket | Changelog under "Fixed", simpler PR description | Less documentation needed |
| Breaking change detected | Add migration notes, mark in changelog, add to PR | Critical for consumers |
| UI changes implemented | Add screenshot placeholders, reference design URLs | Visual changes need visual docs |
| No API changes | Skip Step 2 | No API docs to update |
| Config change only | Minimal changelog, focus on README config section | Documentation scope matches change scope |

## Tool Categories

| Category | Purpose | When Used |
|----------|---------|-----------|
| `file_read` | Read all upstream artifacts, existing docs | Steps 1-7 |
| `file_write` | Create/update documentation files | Steps 2-8 |
| `search` | Find existing doc patterns, ADR numbering | Steps 1, 5 |

## Hook Points

| Hook Point | Purpose | Behavior |
|------------|---------|----------|
| `pre_tool_use` | Guard destructive commands | Block irreversible operations |
| `pre_tool_use` | Guard secret files | Block credential access |
| `post_tool_use` | Lint on save | Auto-fix Markdown style issues |

## Access Restrictions

| Resource | Permission | Reason |
|----------|------------|--------|
| `problem_spec.md` | Read | Requirements context |
| `design_spec.md` | Read | ADRs, API contracts |
| `implementation_manifest.md` | Read | Change scope |
| `verification_report.md` | Read | Verification status |
| `risk_assessment.md` | Read | Risk documentation |
| `test_report.md` | Read | Coverage stats |
| Source repository docs | Read/Write | Documentation target |
| Source repository code | Read | API signature analysis |
| Source repository code | No Write (non-doc files) | Documentation agent doesn't modify code |
| `documentation_manifest.md` | Write | Primary output |
| `pr_description.md` | Write | PR body |
| `commit_messages.md` | Write | Commit messages |

## Quality Checklist

- [ ] Documentation stack correctly identified
- [ ] API documentation updated for all new/modified endpoints
- [ ] Changelog entry follows project convention
- [ ] README updated for new features/configuration
- [ ] ADRs materialized from design_spec
- [ ] PR description includes all required sections
- [ ] Commit messages follow conventional format
- [ ] All documentation follows existing project style
- [ ] No code files modified (only doc files)
- [ ] `documentation_manifest.md` accurately lists all changes
- [ ] `checkpoint.md` updated

## Customization Points

| Point | How Customized | Default |
|-------|---------------|---------|
| Changelog format | Auto-detected / `agent7_custom_client_context.md` | Keep a Changelog |
| Commit message convention | Auto-detected / `agent7_custom_client_context.md` | Conventional Commits |
| ADR template | `agent7_custom_client_context.md` | Standard (Title, Status, Context, Decision, Consequences) |
| ADR directory | Auto-detected | `docs/adr/` |
| PR description template | `agent7_custom_client_context.md` | Standard sections |
| API documentation tool | Auto-detected from codebase | OpenAPI for REST, schema docs for GraphQL |
| Documentation generator | Auto-detected | None (raw Markdown) |
| Commit grouping strategy | `agent7_custom_client_context.md` | One commit per logical change unit |
