---
name: mcp-github-connector
description: "Reusable GitHub MCP connector skill for preflight selection."
user-invocable: false
---

# GitHub MCP Connector Skill

## Overview
Reusable MCP connector skill for GitHub selected during preflight.

## Usage
1. Ensure outputs/agents-repo/.mcp.json contains the github server definition.
2. Complete authentication per .github/sdlc-pipeline/mcp_auth_instructions.md.
3. Use MCP client tools for GitHub operations; do not embed credentials in prompts.

## Authentication
- Mode: oauth
- Integration Type: mcp
