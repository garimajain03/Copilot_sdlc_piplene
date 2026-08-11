---
name: mcp-jira-connector
description: "Reusable Jira MCP connector skill for preflight selection."
user-invocable: false
---

# Jira MCP Connector Skill

## Overview
Reusable MCP connector skill for Jira selected during preflight.

## Usage
1. Ensure outputs/agents-repo/.mcp.json contains the atlassian-jira server definition.
2. Complete authentication per .github/sdlc-pipeline/mcp_auth_instructions.md.
3. Use MCP client tools for Jira operations; do not embed credentials in prompts.

## Authentication
- Mode: token
- Integration Type: mcp
