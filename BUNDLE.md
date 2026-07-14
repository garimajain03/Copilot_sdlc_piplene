---
name: Github Copilot SDLC Factory - Agentic SDLC Enablement
description: A standalone, reusable SDLC Pipeline Bundle containing tools-agnostic Agent Contracts, generation templates, and automation scripts. Combined with the SDLC Pipeline Generator, it enables any project to adopt a structured, multi-agent software development lifecycle — driving onboarding → preflight → code scan → agent generation → orchestration with cross-platform support, connector flexibility (MCP/API), and built-in observability.
authors:
  - Vamsi krishna Hari <vamsikrishna_hari@epam.com>
  - Dudde Yaswa Anirwin <dudde_yaswaanirwin@epam.com>
owner: AI Run India
sdlc_phase: SDLC
support_level: Dedicated Capacity
project_deployments:
    - EPAM-INAI
use_cases:
    - Accelerated Feature Development
    - Technical Task Breakdown
    - Requirements Analysis
    - Code Review
    - Test Case Generation
    - Test Coverage Analysis
    - Design Architecture
    - Infrastructure as Code
    - CI/CD Pipeline Setup
    - Team Members Onboarding and Training
    - Multi-Agent SDLC Orchestration
    - Cross-Platform Project Scaffolding
---


## Summary

**Adopt a full multi-agent SDLC pipeline — without building one from scratch.**

The SDLC Pipeline Bundle is a **standalone, reusable repository** of tools-agnostic Agent Contracts, generation templates, automation scripts, and observability configs. Point it at any project's onboarding answers and it generates a complete, customer-specific set of agents, skills, hooks, and an orchestrator — ready to run on VS Code GitHub Copilot Chat or GitHub Copilot CLI.

Modern AI-assisted development lacks a repeatable structure. Teams prompt ad-hoc, skip design, and produce inconsistent output. This bundle closes that gap with a **templatized, contract-driven pipeline** — reusable contracts define what each agent does, the generator stamps out project-specific agents, and the orchestrator coordinates the full lifecycle from ticket to ship recommendation.

---

## What it does

- **End-to-end SDLC pipeline from onboarding to orchestration.** Customer fills an HTML wizard → Preflight Agent validates, clones, scans → Pipeline Generator produces agents, skills, hooks → Orchestrator runs the full lifecycle.
- **Two-phase onboarding.**
  - **Preflight** — validates onboarding answers, configures connector modes (MCP vs API), sets up workspace with submodules, clones and scans repositories, generates cross-platform setup scripts (`setup.sh` + `setup.ps1`), produces instruction files and codebase scan results.
  - **Pipeline Generation** — reads contracts + onboarding context, checks for existing agents (reuses/enhances), generates customer-specific agents with full metadata, validation, checkpointing, and completion criteria.
- **Connector flexibility.** Each external platform (Jira, Confluence, GitHub/GitLab) can integrate via MCP (`.mcp.json`) or API-based Connector Skills (`SKILL.md`). The Preflight Agent asks which mode per platform.
- **Cross-platform.** All generated artifacts support macOS, Linux, and Windows — `setup.sh` + `setup.ps1`, `install-observability.sh` + `install-observability.ps1`, Python hook scripts.
- **Resumable runs.** Both agents support pause/resume/re-run at any phase via checkpoint state. Crash, close laptop — pick up where you left off.
- **Built-in observability.** OTel Collector + Prometheus configs ship with the bundle. Per-agent telemetry hooks track time, tokens, and cost.
- **Contract-driven generation.** Agents are generated from reusable, tools-agnostic contracts — not hardcoded specs. Swap tools, models, or repos without rewriting agents.

---

## Why teams use it

- **Zero-to-pipeline in minutes.** Fill the wizard, run two commands, get a fully operational multi-agent SDLC pipeline tailored to your stack.
- **Predictable agent output.** Every generated agent has defined inputs, outputs, validation rules, checkpointing, and completion criteria. Reviewers know exactly what to expect.
- **Reusable across projects.** Contracts are tools-agnostic and technology-agnostic. The same bundle generates pipelines for React frontends, Java backends, or Terraform infrastructure.
- **No vendor lock-in.** Works with any PM tool (Jira, Linear, Azure DevOps), any SCM (GitHub, GitLab, Bitbucket), and any design tool (Figma, Sketch). Connector skills abstract the integration.
- **Guardrails built in.** Destructive command guards, secret exposure prevention, lint-on-save hooks, and session learnings are generated as part of the pipeline — not bolted on after.
- **Observability from day one.** Token usage, cost estimation, and per-agent metrics are tracked automatically via OTel telemetry hooks.

---

## Getting started

### Prerequisites

- [VS Code](https://code.visualstudio.com/) with [GitHub Copilot](https://marketplace.visualstudio.com/items?itemName=GitHub.copilot) extension **OR** [GitHub Copilot CLI](https://docs.github.com/en/copilot/github-copilot-in-the-cli)
- Python 3.9+
- Git

### Quick start

```text
# 1. Open client-onboarding-wizard.html in a browser → fill → download intake-sources.md

# 2. Run Preflight (VS Code Copilot Chat)
/preflight intake-sources.md

# 3. Run setup script
chmod +x setup.sh && ./setup.sh        # macOS/Linux
.\setup.ps1                             # Windows

# 4. Generate pipeline
/generate-pipeline

# 5. Customize per-agent context (optional)
# Edit <agent>_custom_client_context.md files

# 6. Run orchestrator
# Your SDLC pipeline is ready in .github/agents/
```

### Available slash commands

| Command | Purpose |
|---------|---------|
| `/preflight` | Run the Preflight Agent (Step 1) |
| `/generate-pipeline` | Run the Pipeline Generator (Step 2) |
| `/resume-pipeline` | Resume a paused run |
| `/pipeline-status` | Check pipeline progress |
| `/rerun-phase` | Re-run a phase with feedback |

---

## Components

### Agents

| Agent | Contract ID | Purpose |
|-------|-------------|---------|
| Preflight Agent | — | Validates onboarding, configures connectors, sets up workspace, scans repos |
| Pipeline Generator | — | Generates customer-specific agents from contracts |
| Ticket Analyzer | AC-000 | Fetch ticket context, classify complexity & type |
| Problem Decomposer | AC-001 | Transform requirements into structured problem spec |
| Design Architect | AC-002 | Produce technical design from problem spec |
| Design Critic | AC-002A | Review design for flaws before implementation |
| Scaffolder | AC-003A | Plan file structure blueprint |
| Builder | AC-003B | Implement code from scaffold + design |
| Fixer | AC-003C | Apply targeted fixes from verification |
| Verifier | AC-004 | Validate implementation against requirements |
| Critic | AC-005 | Adversarial risk analysis |
| Tester | AC-006 | Write and execute tests |
| Documentation Generator | AC-007 | Generate API docs, changelog, PR descriptions, ADRs |
| IaC/DevOps Specialist | AC-008 | Infrastructure changes, CI/CD, database migrations |
| Orchestrator | AC-ORCH | Coordinate pipeline, delegate to agents |

### Connector skills

| Skill | Contract ID | Purpose |
|-------|-------------|---------|
| Ticket Connector | SC-TICKET | PM system integration (Jira, Linear, Azure DevOps, etc.) |
| SCM Connector | SC-SCM | Source control operations (GitHub, GitLab, Bitbucket, etc.) |
| Design Connector | SC-DESIGN | Design tool integration (Figma, Sketch, etc.) |
| Testing Skill | SC-TEST | Test framework conventions & execution |

### Hooks

| Hook | Contract ID | Purpose |
|------|-------------|---------|
| Guard Destructive | HC-GUARD-CMD | Block irreversible terminal commands |
| Guard Secrets | HC-GUARD-SEC | Prevent secret/credential exposure |
| Lint on Save | HC-LINT | Auto-fix code style on file writes |
| Observability Lifecycle | HC-OBSERVABILITY | Manage OTel Collector + Prometheus processes |
| OTel Telemetry | HC-OTEL-TELEMETRY | Per-agent metrics, token tracking, cost estimation |
| Session Learnings | HC-LEARN | Extract and store session learnings |

### Automation scripts

| Script | Purpose |
|--------|---------|
| `repo-scanner.py` | Scans repositories for structure, dependencies, patterns, conventions |
| `scm-bootstrap.py` | Clones customer repositories with retry logic and branch targeting |
| `instructions-generator.py` | Generates per-repo instruction files from scan results |
| `checkpoint-manager.py` | Manages pipeline state — save, load, reset, pause/resume |
| `outcome-inspector.py` | Self-validates outputs for completeness, quality, security |
| `pipeline-migrator.py` | Version & migration manager |
| `install-observability.sh` | macOS/Linux observability binary installer |
| `install-observability.ps1` | Windows observability binary installer |

---

## Artifact flow

```
Ticket/Requirement
    │
    ▼
 Agent 0: Ticket Analyzer ──► ticket_analysis.md
    │
    ▼
 Agent 1: Problem Decomposer ──► problem_spec.md
    │
    ▼
 Agent 2: Design Architect ◄──► Agent 2a: Design Critic ──► design_spec.md
    │
    ├── Code Path ──► Agent 3a: Scaffolder ──► Agent 3b: Builder ──► Agent 6: Tester
    │
    └── IaC Path ──► Agent 8: IaC/DevOps Specialist
    │
    ▼
 Agent 4: Verifier ──► verification_report.md
    │
    ├── Issues? ──► Agent 3c: Fixer (max 3x) ──► re-verify
    │
    └── Clean ──► Agent 5: Critic ──► Agent 7: Documentation ──► Ship Recommendation
```

---

## Versioning

| Field | Value |
|-------|-------|
| Bundle Version | 1.0.0 |
| Source Pipeline Version | 2.4.0 |
| Created | 2026-05-31 |
