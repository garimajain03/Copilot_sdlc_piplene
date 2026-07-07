# SDLC Pipeline Bundle - Templatized Agentic Workflow

## Overview

This repository is a **standalone, reusable SDLC Pipeline Bundle** containing **tools-agnostic Agent Contracts** extracted from a production SDLC Orchestrator pipeline. Combined with the **SDLC Pipeline Generator**, it enables any project to adopt a structured, multi-agent software development lifecycle.

**Runs on:** VS Code GitHub Copilot Chat or GitHub Copilot CLI.

## How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│                    SDLC ONBOARDING FLOW                        │
│                                                                 │
│  1. Customer fills HTML Wizard (client-onboarding-wizard.html)  │
│     -> Downloads intake-sources.md                               │
│                                                                 │
│  2. Preflight Agent reads answers                               │
│     -> Asks connector mode per platform (MCP vs API-based)       │
│     -> Configures workspace (submodules or custom layout)        │
│     -> Generates .mcp.json (for MCP platforms)                   │
│     -> Generates setup.sh + setup.ps1 (cross-platform)           │
│     -> Clones & scans repos, generates instructions + index.md   │
│     -> Asks clarification questions if unclear                   │
│                                                                 │
│  3. SDLC Pipeline Generator reads Contracts + answers           │
│     -> Checks for existing agents - reuses and enhances them     │
│     -> Generates Connector Skills only for API-based platforms   │
│     -> Generates agents with full metadata, validation,          │
│       checkpointing, and completion criteria                    │
│     -> Generates cross-platform Python hook scripts              │
│     -> Includes telemetry hooks & observability setup            │
│                                                                 │
│  4. Customer adds custom context per agent (optional)           │
│     -> <agent>_custom_client_context.md files                    │
│                                                                 │
│  5. Run Orchestrator -> Full SDLC pipeline operational           │
└─────────────────────────────────────────────────────────────────┘
```

## Repository Structure

```
sdlc-pipeline-bundle/                  ← This standalone repository
├── README.md                          ← This file
├── client-onboarding-wizard.html      ← Onboarding HTML wizard
├── .github/                           ← VS Code Copilot agent discovery
│   ├── agents/
│   │   ├── sdlc-preflight.agent.md          ← Preflight Agent (full instructions)
│   │   └── sdlc-pipeline-generator.agent.md ← Pipeline Generator (full instructions)
│   ├── prompts/
│   │   ├── preflight.prompt.md              ← /preflight slash command
│   │   ├── generate-pipeline.prompt.md      ← /generate-pipeline slash command
│   │   ├── resume-pipeline.prompt.md        ← /resume-pipeline slash command
│   │   ├── pipeline-status.prompt.md        ← /pipeline-status slash command
│   │   └── rerun-phase.prompt.md            ← /rerun-phase slash command
│   └── copilot-instructions.md               ← Repo-level Copilot instructions
├── onboarding-utilities/
│   ├── contracts/                     ← Reusable Agent Contracts
│   │   ├── CONTRACT_INDEX.md          ← Master index of all contracts
│   │   ├── agent0_ticket_analyzer.contract.md
│   │   ├── agent1_problem_decomposer.contract.md
│   │   ├── agent2_design_architect.contract.md
│   │   ├── agent2a_design_critic.contract.md
│   │   ├── agent3a_scaffolder.contract.md
│   │   ├── agent3b_builder.contract.md
│   │   ├── agent3c_fixer.contract.md
│   │   ├── agent4_verifier.contract.md
│   │   ├── agent5_critic.contract.md
│   │   ├── agent6_tester.contract.md
│   │   ├── agent7_documentation.contract.md   ← Documentation Generator
│   │   ├── agent8_iac_devops.contract.md      ← IaC/DevOps Specialist
│   │   ├── orchestrator.contract.md
│   │   ├── hooks/
│   │   │   ├── hook_guard_destructive.contract.md
│   │   │   ├── hook_guard_secrets.contract.md
│   │   │   ├── hook_lint_on_save.contract.md
│   │   │   ├── hook_session_learnings.contract.md
│   │   │   ├── hook_observability.contract.md
│   │   │   └── hook_otel_telemetry.contract.md
│   │   └── skills/
│   │       ├── skill_ticket_connector.contract.md
│   │       ├── skill_scm_connector.contract.md
│   │       ├── skill_design_connector.contract.md
│   │       └── skill_testing.contract.md
│   ├── templates/                     ← Generation Templates
│   │   ├── agent_template.md.hbs
│   │   ├── hook_template.py.hbs
│   │   ├── skill_template.md.hbs
│   │   ├── setup_template.sh.hbs
│   │   ├── setup_template.ps1.hbs     ← Windows PowerShell setup template
│   │   └── custom_client_context_template.md
│   ├── schemas/                       ← Validation Schemas
│   │   ├── contract_schema.md
│   │   └── onboarding_answers_schema.md
│   ├── scripts/                       ← Automation scripts
│   │   ├── repo-scanner.py
│   │   ├── instructions-generator.py
│   │   ├── scm-bootstrap.py
│   │   ├── checkpoint-manager.py
│   │   ├── outcome-inspector.py
│   │   ├── pipeline-migrator.py           ← Version & migration manager
│   │   ├── install-observability.sh       ← macOS/Linux binary installer
│   │   └── install-observability.ps1      ← Windows binary installer
│   ├── observability/                 ← Telemetry stack templates
│   │   ├── otel-collector-config.yml
│   │   ├── prometheus/
│   │   │   └── prometheus.yml
│   │   └── .gitignore
│   └── docs/                          ← Documentation
│       ├── getting-started.md         ← How to run guide
│       └── workflow.html              ← Interactive workflow visualization
├── tests/                             ← Test suite
│   └── test_scripts.py                ← Unit tests for automation scripts
```

## Contracts vs Specs

| Aspect | Spec (Internal) | Contract (Reusable) |
|--------|-----------------|---------------------|
| **Scope** | Specific to one project | Any project |
| **Tools** | Named tools (eslint, Jest, etc.) | Tool categories (linter, test runner) |
| **Models** | Specific models (GPT-5.3-Codex) | Model tier (reasoning, coding, fast) |
| **Repos** | Hardcoded submodules | Customer-defined repositories |
| **Connectors** | Atlassian, GitHub | Pluggable (any PM, SCM, design tool) |
| **Focus** | Metadata + I/O | Outcomes + Reasoning + Conditions |

## Quick Start

> **Detailed guide:** See [onboarding-utilities/docs/getting-started.md](onboarding-utilities/docs/getting-started.md) for full setup instructions, phase-by-phase walkthroughs, scripts reference, and troubleshooting.
>
> **Interactive workflow:** Open [onboarding-utilities/docs/workflow.html](onboarding-utilities/docs/workflow.html) in a browser to explore the pipeline visually.

### VS Code GitHub Copilot

1. Clone this repo into your project or as a standalone workspace
2. Open in VS Code with GitHub Copilot extension
3. Open `client-onboarding-wizard.html` -> fill -> download `intake-sources.md`
4. In Copilot Chat: `@workspace /preflight intake-sources.md`
5. In Copilot Chat: `@workspace /generate-pipeline intake-sources.md`
6. Customize per-agent context in `<agent>_custom_client_context.md` files
7. Run the generated Orchestrator

### GitHub Copilot CLI

1. Clone this repo alongside your project repositories
2. Fill `intake-sources.md` via the wizard or manually
3. `gh copilot chat "Run the SDLC Preflight Agent on intake-sources.md"`
4. `gh copilot chat "Run the SDLC Pipeline Generator"`
5. Review and customize generated agents

## Versioning

| Field | Value |
|-------|-------|
| Bundle Version | 1.0.0 |
| Source Pipeline Version | 2.4.0 |
| Created | 2026-05-31 |

