# SDLC Pipeline Bundle — Copilot Instructions

## Overview

This repository is a **standalone SDLC Pipeline Bundle** (`github-copilot-sdlc-template`) containing reusable Agent Contracts, generation templates, and automation scripts. It enables any project to adopt a structured, multi-agent software development lifecycle.

## Repository Layout

| What | Where |
|------|-------|
| Agent definitions (full instructions) | `.github/agents/` |
| Reusable agent contracts | `contracts/` |
| Hook contracts | `contracts/hooks/` |
| Skill contracts | `contracts/skills/` |
| Generation templates | `templates/` |
| Validation schemas | `schemas/` |
| Automation scripts | `scripts/` |
| Observability configs & binaries | `observability/` |
| Onboarding wizard | `client-onboarding-wizard.html` |
| Prompt commands | `.github/prompts/` |
| Pipeline state (generated) | `.github/sdlc-pipeline/` |
| Instruction files (generated) | `.github/instructions/` |

## Key Concepts

### Connector Integration Modes

Each external platform (Jira, Confluence, GitHub/GitLab) can be integrated via:
- **MCP (Model Context Protocol)** — generates `.mcp.json` with server definitions
- **API-based Connector Skills** — generates SKILL.md files with CLI commands

The Preflight Agent asks which mode to use per platform. The Pipeline Generator only generates Connector Skills for platforms where API-based integration was selected.

### Workspace Structure

Two modes supported:
- **Default** — Single Agents repository with Git submodules for development repos
- **Custom** — Customer-defined repository layout

### Cross-Platform Support

All generated artifacts support both macOS and Windows:
- `setup.sh` (macOS/Linux) + `setup.ps1` (Windows)
- `install-observability.sh` + `install-observability.ps1`
- Hook scripts in Python (cross-platform by nature)

## Available Prompts (Slash Commands)

| Command | File | Purpose |
|---------|------|---------|
| `/preflight` | `.github/prompts/preflight.prompt.md` | Run the Preflight Agent (Step 1) |
| `/generate-pipeline` | `.github/prompts/generate-pipeline.prompt.md` | Run the Pipeline Generator (Step 2) |
| `/resume-pipeline` | `.github/prompts/resume-pipeline.prompt.md` | Resume a paused run |
| `/pipeline-status` | `.github/prompts/pipeline-status.prompt.md` | Check pipeline progress |
| `/rerun-phase` | `.github/prompts/rerun-phase.prompt.md` | Re-run a phase with feedback |

## Path Conventions

- All paths in agent instructions and scripts are **relative to this repo root** (workspace root)
- When running from VS Code or CLI, CWD = this repo root
- Scripts: `python3 scripts/<script>.py` (e.g., `python3 scripts/repo-scanner.py`)
- PowerShell scripts: `.\scripts\<script>.ps1` (e.g., `.\scripts\install-observability.ps1`)
- Contracts: `contracts/` (e.g., `contracts/agent0_ticket_analyzer.contract.md`)
- Schemas: `schemas/` (e.g., `schemas/onboarding_answers_schema.md`)
- Generated outputs: `.github/sdlc-pipeline/`, `.github/instructions/`, `.github/hooks/`, `.github/skills/`

## Available Agents

| Agent | File | Purpose |
|-------|------|---------|
| SDLC Preflight Agent | `.github/agents/sdlc-preflight.agent.md` | Validates onboarding, configures connectors (MCP/API), sets up workspace, scans repos, generates cross-platform setup |
| SDLC Pipeline Generator | `.github/agents/sdlc-pipeline-generator.agent.md` | Generates customer-specific agents from contracts, reuses existing agents, generates cross-platform hooks |
