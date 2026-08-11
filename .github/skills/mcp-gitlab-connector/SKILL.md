---
name: mcp-gitlab-connector
description: "Reusable GitLab MCP connector skill for preflight selection."
user-invocable: false
---

# GitLab MCP Connector Skill

## Overview
Reusable MCP connector skill for GitLab selected during preflight.

## Usage
1. Ensure outputs/agents-repo/.mcp.json contains the gitlab server definition.
2. Complete authentication per .github/sdlc-pipeline/mcp_auth_instructions.md.
3. Use MCP client tools for GitLab operations; do not embed credentials in prompts.

## Authentication
- Mode: token
- Integration Type: mcp
