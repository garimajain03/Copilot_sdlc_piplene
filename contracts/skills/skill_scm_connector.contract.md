# Contract: Skill — SCM Connector

| Field | Value |
|-------|-------|
| contract_id | SC-SCM |
| skill_name | SCM Connector |
| category | scm |
| version | 1.0.0 |

## Role

Provides a unified interface for source control operations. Abstracts away SCM-specific APIs behind a common command set.

## Supported SCM Systems (Pluggable)

| SCM | Implementation | Detection |
|-----|---------------|-----------|
| GitHub | GitHub CLI / REST API | Onboarding → SCM = github |
| GitLab | GitLab CLI / REST API | Onboarding → SCM = gitlab |
| Bitbucket | Bitbucket REST API | Onboarding → SCM = bitbucket |
| Azure DevOps | Azure DevOps REST API | Onboarding → SCM = azure-devops |

## Capabilities (Abstract)

| Capability | Description | Agents Using |
|------------|-------------|-------------|
| `status` | Repository/workspace status | Orchestrator |
| `create-branch` | Create feature branch from default | Builder, Orchestrator |
| `checkout-branch` | Switch to branch | Builder |
| `commit-push` | Stage, commit, push changes | Orchestrator |
| `create-pr` | Create pull request with linked ticket | Orchestrator |
| `get-pr` | Fetch PR details | Agent 0, Orchestrator |
| `pr-changes` | Fetch PR diff/changes | Agent 0 |
| `pr-comments` | Fetch PR review comments | Agent 0 |
| `branch-status` | Check CI/build status | Orchestrator |

## Configuration

| Setting | Source | Example |
|---------|--------|---------|
| SCM provider | Onboarding answers → SCM | `github` |
| Organization/workspace | Onboarding answers → SCM org | `myorg` |
| Default branch | Onboarding answers → Default Branch | `main` |
| Auth token | Setup script | `GITHUB_TOKEN` |
| Enterprise URL | Onboarding answers → GitHub Enterprise | `https://github.myorg.com` |

## Customization Points

| Point | How Customized | Default |
|-------|---------------|---------|
| SCM provider | Onboarding answers | GitHub |
| Branch naming convention | `skill_scm_custom.md` | `feature/<ticket-id>` |
| PR template | `skill_scm_custom.md` | Standard template |
| Protected branches | Onboarding answers → Default Branch | `main` |
| CI status check names | `skill_scm_custom.md` | Auto-detected |
