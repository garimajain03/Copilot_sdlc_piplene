---
name: mcp-azure-devops-connector
description: "Reusable Azure DevOps MCP connector skill for preflight selection."
user-invocable: false
---

# Azure DevOps MCP Connector Skill

## Overview
Reusable MCP connector skill for Azure DevOps selected during preflight.

## Usage
1. Ensure outputs/agents-repo/.mcp.json contains the configured Azure DevOps MCP server definition.
2. Complete authentication per .github/sdlc-pipeline/mcp_auth_instructions.md.
3. Use MCP client tools for Azure DevOps operations; do not embed credentials in prompts.

## Authentication
- Mode: token
- Integration Type: mcp
