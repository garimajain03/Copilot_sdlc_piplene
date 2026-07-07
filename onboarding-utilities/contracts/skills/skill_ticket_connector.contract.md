# Contract: Skill — Ticket Connector

| Field | Value |
|-------|-------|
| contract_id | SC-TICKET |
| skill_name | Ticket Connector |
| category | ticket_management |
| version | 1.0.0 |

## Role

Provides a unified interface for retrieving ticket context from any project management system. Abstracts away PM-specific APIs behind a common command set.

## Supported PM Systems (Pluggable)

| PM System | Implementation | Detection |
|-----------|---------------|-----------|
| Jira | Atlassian REST API / CLI | Onboarding → PM System = Jira |
| Linear | Linear GraphQL API | Onboarding → PM System = Linear |
| Azure DevOps | Azure DevOps REST API | Onboarding → PM System = Azure DevOps |
| GitHub Issues | GitHub REST/GraphQL API | Onboarding → PM System = GitHub Issues |
| Shortcut | Shortcut REST API | Onboarding → PM System = Shortcut |

## Capabilities (Abstract)

| Capability | Description | Agents Using |
|------------|-------------|-------------|
| `get-ticket` | Fetch ticket summary, description, status, priority, assignee | Agent 0 |
| `get-details` | Cost-optimized staged retrieval (core → enrichment → artifacts) | Agent 0 |
| `get-linked` | Retrieve linked/related tickets | Agent 0 |
| `get-comments` | Fetch ticket comments/discussion | Agent 0 |
| `get-attachments` | List and download ticket attachments | Agent 0 |
| `get-epic` | Fetch parent epic context | Agent 0 |
| `get-sprint` | Fetch sprint context | Agent 0 |
| `wiki-search` | Search linked wiki/documentation | Agent 0, 1 |
| `wiki-get` | Retrieve specific wiki page | Agent 0, 1 |

## Staged Retrieval Policy

| Stage | Default | Cost | Content |
|-------|---------|------|---------|
| 1 | Always | Low | Core ticket data |
| 2 | On demand (user-approved) | Medium | Comments + linked tickets |
| 3 | On demand (user-approved) | High | Attachments + wiki pages |

## Input/Output

**Input:** Ticket ID, optional flags (stage, output-dir, format)
**Output:** JSON to stdout, or files to output directory

## Configuration

| Setting | Source | Example |
|---------|--------|---------|
| PM base URL | Onboarding answers → PM URL | `https://myorg.atlassian.net` |
| Auth token | Setup script (stored in `.env` or OS keychain) | `JIRA_TOKEN` |
| Ticket prefix regex | Onboarding answers → Ticket Prefix | `[A-Z]+-\d+` |
| Wiki spaces | Onboarding answers → Confluence spaces | `ARCH, ENG` |

## Customization Points

| Point | How Customized | Default |
|-------|---------------|---------|
| PM system type | Onboarding answers | Jira |
| Authentication method | Setup script | Token-based |
| Ticket ID pattern | Onboarding answers → Ticket Prefix | `[A-Z]+-\d+` |
| Wiki integration | Onboarding answers → Sources | Confluence |
| Custom fields to extract | `skill_ticket_custom.md` | Standard fields |
