---
name: azure-devops-connector
description: "Reusable Azure DevOps connector skill for preflight selection."
user-invocable: false
---

# Azure DevOps Connector Skill

## Overview
Reusable API connector skill for Azure DevOps selected during preflight.

## Usage
1. Run connector commands with node .github/skills/azure-devops-connector/index.js --command=<command>.
2. Provide credentials via environment variables only.
3. Never store plaintext credentials in prompt history.

## Authentication
- Mode: token
- Integration Type: api
