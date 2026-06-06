# Onboarding Answers Schema — SDLC Pipeline Bundle

> Defines the expected structure of `intake-sources.md` that the Preflight Agent and Pipeline Generator consume.

## Required Sections

### 1. Organisation (Required)

| Field | Required | Used By | Purpose |
|-------|----------|---------|---------|
| Company | Yes | Generator | Naming, branding |
| Industry | Yes | Generator | Compliance defaults, domain patterns |
| Approved AI tools | Yes | Preflight | Tool compatibility check |
| LLM providers | Yes | Generator | Model selection |
| Personas engaged | No | Generator | Which agent types to generate |
| Compliance | No | Generator | Security hook strictness, guardrails |
| Domain model | No | Generator | Domain-specific terminology |

### 2. Approved LLM Models (Required)

| Field | Required | Purpose |
|-------|----------|---------|
| Provider | Yes | Maps to model_tier in contracts |
| Models | Yes | Specific models for agent frontmatter |

**Model Tier Mapping:**
- `reasoning` → Best available model (e.g., claude-sonnet-4, GPT-5.3-Codex, etc.)
- `coding` → Code-optimized model (e.g., claude-sonnet-4, GPT-5.3-Codex, etc.)
- `fast` → Low-latency model (e.g., claude-haiku, GPT-4o-mini, etc.)

### 3. Workflow — Developer (Required)

| Field | Required | Purpose |
|-------|----------|---------|
| PM System | Yes | Determines ticket connector skill |
| PM URL | Yes (if PM ≠ None) | Connector configuration |
| Ticket Prefix | No | Ticket detection regex |
| Default Branch | Yes | SCM connector configuration |
| Project Keys | No | Ticket filtering |

### 4. Workflow — QA (Optional)

| Field | Required | Purpose |
|-------|----------|---------|
| Test Mgmt | No | Test report integration |
| Automation | No | Test framework selection |
| Coverage | No | Coverage threshold for Verifier/Tester |
| Frameworks | No | Testing skill selection |

### 5. Codebase Scan (Auto-detected)

> NOT captured in the wizard — detected by Preflight Agent's codebase scan.

| Detail | Detection Source | Used By |
|--------|-----------------|---------|
| Languages & frameworks | package.json, file extensions | Builder, Tester |
| Linter | .eslintrc, biome.json, etc. | Lint-on-save hook |
| Formatter | .prettierrc, biome.json | Post-save hook |
| Naming conventions | ESLint rules | Builder |
| Test runner & commands | jest.config, vitest.config | Tester |
| Package manager | Lock files | Builder, setup scripts |
| TypeScript strictness | tsconfig.json | Builder, Scaffolder |
| Pre-commit hooks | .husky, lint-staged | Guard hooks |
| Build tool | vite.config, webpack.config | Builder |

### 6. Sources (Required)

| Field | Required | Purpose |
|-------|----------|---------|
| Confluence/Wiki URL | No | Ticket connector enrichment |
| SCM provider | Yes | SCM connector skill |
| SCM org/workspace | No | Connector configuration |
| Docs strategy | No | Knowledge retrieval approach |

### 7. Constraints (Required)

| Field | Required | Purpose |
|-------|----------|---------|
| PII handled | No | Security hook strictness |
| Agent Behavioral Guardrails | Yes | Injected into all agents |
| Security/Privacy rules | Yes | Hook configuration |
| Code Quality rules | Yes | Verifier/Builder configuration |
| Quality Gates | Yes | Verifier thresholds |
| Risk Management rules | Yes | Critic configuration |

### 8. AI Stack (Optional)

| Field | Required | Purpose |
|-------|----------|---------|
| MCPs | No | Connector configuration |
| Existing agents | No | Conflict avoidance |
| CMS | No | Content management skill |

### 9. Pipeline Configuration (Optional)

| Field | Required | Default | Purpose |
|-------|----------|---------|---------|
| `setup_mode` | No | `standard` | Controls clarification question depth: `express` (1-2 questions), `standard` (essential questions), `detailed` (full questionnaire) |
| `approval_mode` | No | `batch` | Approval gate strategy: `strict` (approve every phase), `batch` (approve at design + ship), `auto` (all gates auto-approved) |
| `dry_run` | No | `false` | If `true`, generate preview report without writing files |
| `include_documentation_agent` | No | `true` | Whether to generate Agent 7 (Documentation Generator) |
| `include_iac_agent` | No | `false` | Whether to generate Agent 8 (IaC/DevOps Specialist) |

**Approval Mode Details:**

| Mode | Gates Requiring Approval | Best For |
|------|--------------------------|----------|
| `strict` | Design review, pre-implementation, post-test, pre-ship | Regulated industries (finance, healthcare) |
| `batch` | Design review, ship recommendation | Most teams |
| `auto` | None (all auto-approved) | Prototyping, hackathons, trusted pipelines |

## Validation Rules

1. **Organisation.Company** — Must be non-empty
2. **Approved LLM Models** — At least one provider + model pair
3. **Workflow.Developer.PM System** — Must be one of: `Jira`, `Linear`, `Azure DevOps`, `GitHub Issues`, `Shortcut`, `None`
4. **Workflow.Developer.Default Branch** — Must be a valid branch name
5. **Sources.SCM** — Must be one of: `github`, `gitlab`, `bitbucket`, `azure-devops`
6. **Constraints.Agent Behavioral Guardrails** — Must be non-empty (at minimum: scope control, security)
7. **Pipeline.setup_mode** — If present, must be one of: `express`, `standard`, `detailed`
8. **Pipeline.approval_mode** — If present, must be one of: `strict`, `batch`, `auto`
9. **Pipeline.dry_run** — If present, must be boolean
10. **Pipeline.include_documentation_agent** — If present, must be boolean
11. **Pipeline.include_iac_agent** — If present, must be boolean
