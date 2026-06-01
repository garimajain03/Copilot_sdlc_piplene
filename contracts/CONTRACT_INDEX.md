# Contract Index — SDLC Pipeline Bundle

> Master index of all reusable agent, skill, and hook contracts.
> Contracts are tools-agnostic, technology-agnostic, and designed for cross-client reuse.

## Pipeline Flow

```
Ticket/Requirement
    │
    ▼
┌──────────────────┐     ┌──────────────────────┐
│  Agent 0         │     │  Skill: Ticket       │
│  Ticket Analyzer │◄────│  Connector           │
└────────┬─────────┘     └──────────────────────┘
         │ ticket_analysis.md
         ▼
┌──────────────────┐
│  Agent 1         │◄──── Clarification Loop (Human-in-the-Loop)
│  Problem         │
│  Decomposer      │
└────────┬─────────┘
         │ problem_spec.md
         ▼
┌──────────────────┐     ┌──────────────────────┐
│  Agent 2         │     │  Agent 2a            │
│  Design          │────►│  Design Critic       │◄──── Refinement Loop
│  Architect       │◄────│                      │
└────────┬─────────┘     └──────────────────────┘
         │ design_spec.md
         │
    ┌────┴────────────┐
    │ Ticket Type?     │
    └────┬────────┬────┘
    Code │        │ IaC/DevOps
         ▼        ▼
┌──────────────┐  ┌──────────────────┐
│  Agent 3a    │  │  Agent 8         │
│  Scaffolder  │  │  IaC/DevOps      │
└────────┬─────┘  │  Specialist      │
         │        └────────┬─────────┘
         │ scaffold_       │ iac_manifest.md
         │ manifest.md     │
         ▼                 │
┌──────────────────┐       │
│  Agent 3b        │       │
│  Builder         │       │
└────────┬─────────┘       │
         │ impl_manifest   │
         ▼                 │
┌──────────────────┐       │
│  Agent 6         │       │
│  Tester          │       │
└────────┬─────────┘       │
         │ test_report.md  │
         ▼                 │
┌──────────────────┐       │
│  Agent 4         │◄──────┘
│  Verifier        │
└────────┬─────────┘
         │ verification_report.md
         │
    ┌────┴────┐
    │ Issues? │
    └────┬────┘
     Yes │          No
         ▼           ▼
┌──────────────┐  ┌──────────────────┐
│  Agent 3c    │  │  Agent 5         │
│  Fixer       │  │  Critic          │
│  (max 3x)    │  │                  │
└──────┬───────┘  └────────┬─────────┘
       │                   │ risk_assessment.md
       └──► re-run Agent 4 │
                           ▼
                    ┌──────────────────┐
                    │  Agent 7         │
                    │  Documentation   │
                    │  Generator       │
                    └────────┬─────────┘
                             │ pr_description.md
                             │ documentation_manifest.md
                             ▼
                      Ship Recommendation
```

## Agent Contracts

| Contract ID | Agent | File | Purpose |
|-------------|-------|------|---------|
| `AC-000` | Ticket Analyzer | [agent0_ticket_analyzer.contract.md](agent0_ticket_analyzer.contract.md) | Fetch ticket context, classify complexity & type |
| `AC-001` | Problem Decomposer | [agent1_problem_decomposer.contract.md](agent1_problem_decomposer.contract.md) | Transform requirements into structured problem spec |
| `AC-002` | Design Architect | [agent2_design_architect.contract.md](agent2_design_architect.contract.md) | Produce technical design from problem spec |
| `AC-002A` | Design Critic | [agent2a_design_critic.contract.md](agent2a_design_critic.contract.md) | Review design for flaws before implementation |
| `AC-003A` | Scaffolder | [agent3a_scaffolder.contract.md](agent3a_scaffolder.contract.md) | Plan file structure blueprint |
| `AC-003B` | Builder | [agent3b_builder.contract.md](agent3b_builder.contract.md) | Implement code from scaffold + design |
| `AC-003C` | Fixer | [agent3c_fixer.contract.md](agent3c_fixer.contract.md) | Apply targeted fixes from verification |
| `AC-004` | Verifier | [agent4_verifier.contract.md](agent4_verifier.contract.md) | Validate implementation against requirements |
| `AC-005` | Critic | [agent5_critic.contract.md](agent5_critic.contract.md) | Adversarial risk analysis |
| `AC-006` | Tester | [agent6_tester.contract.md](agent6_tester.contract.md) | Write and execute tests |
| `AC-007` | Documentation Generator | [agent7_documentation.contract.md](agent7_documentation.contract.md) | Generate API docs, changelog, PR descriptions, ADRs |
| `AC-008` | IaC/DevOps Specialist | [agent8_iac_devops.contract.md](agent8_iac_devops.contract.md) | Infrastructure changes, CI/CD, database migrations |
| `AC-ORCH` | Orchestrator | [orchestrator.contract.md](orchestrator.contract.md) | Coordinate pipeline, delegate to agents |

## Skill Contracts

| Contract ID | Skill | File | Purpose |
|-------------|-------|------|---------|
| `SC-TICKET` | Ticket Connector | [skills/skill_ticket_connector.contract.md](skills/skill_ticket_connector.contract.md) | PM system integration (Jira, Linear, Azure DevOps, etc.) |
| `SC-SCM` | SCM Connector | [skills/skill_scm_connector.contract.md](skills/skill_scm_connector.contract.md) | Source control operations (GitHub, GitLab, Bitbucket, etc.) |
| `SC-DESIGN` | Design Connector | [skills/skill_design_connector.contract.md](skills/skill_design_connector.contract.md) | Design tool integration (Figma, Sketch, etc.) |
| `SC-TEST` | Testing Skill | [skills/skill_testing.contract.md](skills/skill_testing.contract.md) | Test framework conventions & execution |

## Hook Contracts

| Contract ID | Hook | File | Purpose |
|-------------|------|------|---------|
| `HC-GUARD-CMD` | Guard Destructive | [hooks/hook_guard_destructive.contract.md](hooks/hook_guard_destructive.contract.md) | Block irreversible terminal commands |
| `HC-GUARD-SEC` | Guard Secrets | [hooks/hook_guard_secrets.contract.md](hooks/hook_guard_secrets.contract.md) | Prevent secret/credential exposure |
| `HC-LINT` | Lint on Save | [hooks/hook_lint_on_save.contract.md](hooks/hook_lint_on_save.contract.md) | Auto-fix code style on file writes |
| `HC-OBSERVABILITY` | Observability Lifecycle | [hooks/hook_observability.contract.md](hooks/hook_observability.contract.md) | Manage OTel Collector + Prometheus processes |
| `HC-OTEL-TELEMETRY` | OTel Telemetry | [hooks/hook_otel_telemetry.contract.md](hooks/hook_otel_telemetry.contract.md) | Per-agent metrics, token tracking, cost estimation |
| `HC-LEARN` | Session Learnings | [hooks/hook_session_learnings.contract.md](hooks/hook_session_learnings.contract.md) | Extract and store session learnings |

## Artifact Flow

| Artifact | Produced By | Consumed By | Format |
|----------|-------------|-------------|--------|
| `ticket_analysis.md` | Agent 0 | Orchestrator, Agent 1 | Markdown (classification, repos, context) |
| `problem_spec.md` | Agent 1 | Agent 2, 3b, 4, 5, 6 | Markdown (REQ/AC/EC/ASM inventory) |
| `clarification_questions.md` | Agent 1 | Orchestrator → User | Markdown (Q/A table) |
| `design_spec.md` | Agent 2 | Agent 2a, 3a, 3b, 3c, 4, 5, 6 | Markdown (components, models, APIs, ADRs) |
| `design_review.md` | Agent 2a | Agent 2 (refinement) | Markdown (findings + severity) |
| `scaffold_manifest.md` | Agent 3a | Agent 3b | Markdown (file blueprint) |
| `implementation_manifest.md` | Agent 3b | Agent 3c, 4, 5, 6 | Markdown (files created/modified) |
| `test_report.md` | Agent 6 | Agent 4 | Markdown (coverage, results) |
| `verification_report.md` | Agent 4 | Agent 3c, 5, Orchestrator | Markdown (requirement coverage, findings) |
| `fix_request.md` | Agent 4 | Agent 3c | Markdown (issues to fix) |
| `fix_manifest.md` | Agent 3c | Agent 4 (re-verification) | Markdown (fixes applied) |
| `risk_assessment.md` | Agent 5 | Orchestrator, Human | Markdown (risks, ship recommendation) |
| `documentation_manifest.md` | Agent 7 | Orchestrator | Markdown (docs generated) |
| `pr_description.md` | Agent 7 | Orchestrator, Human | Markdown (PR body) |
| `commit_messages.md` | Agent 7 | Orchestrator, Human | Markdown (conventional commits) |
| `iac_manifest.md` | Agent 8 | Verifier, Orchestrator | Markdown (IaC changes summary) |
| `blast_radius_assessment.md` | Agent 8 | Critic, Human | Markdown (impact analysis) |
| `rollback_plan.md` | Agent 8 | Human, Orchestrator | Markdown (revert steps) |
| `iac_plan_output.md` | Agent 8 | Verifier, Human | Markdown (plan/preview output) |
| `checkpoint.md` | All agents | All agents | Markdown (pipeline state tracking) |
| `telemetry_report.md` | HC-OTEL-TELEMETRY | Orchestrator, Human | Markdown (per-agent time, tokens, cost) |

## Custom Client Context

Each generated agent supports an optional `<agent>_custom_client_context.md` file. Agents MUST load and apply this file if it exists. See [custom_client_context_template.md](../templates/custom_client_context_template.md).

## Contract Schema

All contracts follow the schema defined in [contract_schema.md](../schemas/contract_schema.md).
