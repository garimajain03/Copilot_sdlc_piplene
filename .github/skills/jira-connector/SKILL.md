---
name: jira-connector
description: "Reusable Jira connector skill for preflight selection."
user-invocable: false
---

# Jira Connector Skill

## Overview
Reusable API connector skill for Jira selected during preflight.

## Usage
1. Run connector commands with node .github/skills/jira-connector/index.js --command=<command>.
2. Provide credentials via environment variables only.
3. Never store plaintext credentials in prompt history.

## Authentication
- Mode: token
- Integration Type: api
