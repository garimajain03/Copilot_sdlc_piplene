# Contract: Hook - Guard Destructive Commands

| Field | Value |
|-------|-------|
| contract_id | HC-GUARD-CMD |
| hook_name | Guard Destructive Commands |
| event | pre_tool_use |
| version | 1.0.0 |

## Purpose

Intercepts terminal/execute tool invocations and blocks commands that could cause irreversible damage to the filesystem, repository, or system.

## Trigger Conditions

- Fires on every `terminal` / `execute` tool invocation
- Inspects the command string before execution

## Guard Logic

### Block Patterns (Configurable)

| Pattern Category | Examples | Severity |
|------------------|----------|----------|
| Recursive deletion of critical paths | `rm -rf /`, `rm -rf ~`, `rm -rf .git` | Critical - always block |
| Force push to protected branches | `git push --force main`, `git push -f origin main` | Critical - always block |
| Hard reset | `git reset --hard` on shared branches | High - block with override |
| Database destruction | `DROP DATABASE`, `DROP TABLE` | Critical - always block |
| Package registry publish | `npm publish`, `pip upload` | High - require confirmation |
| System modification | `chmod -R 777 /`, `chown -R` on system paths | Critical - always block |

### Allow Patterns

| Pattern | Reason |
|---------|--------|
| `rm -rf node_modules` | Common cleanup |
| `rm -rf dist`, `rm -rf build` | Build output cleanup |
| `git reset --hard` on feature branches | Safe for feature work |

## Exit Codes

| Code | Meaning | Agent Behavior |
|------|---------|----------------|
| `0` | Command is safe - proceed | Agent executes normally |
| `2` | Command is blocked - error fed to agent | Agent receives error message, must choose alternative |

## Customization Points

| Point | How Customized | Default |
|-------|---------------|---------|
| Protected paths | Onboarding answers -> Agent Guardrails | `/`, `~`, `.git` |
| Protected branches | Onboarding answers -> Default Branch | `main`, `master` |
| Additional block patterns | `hook_guard_destructive_custom.md` | None |
| Allow-list patterns | `hook_guard_destructive_custom.md` | Standard cleanup |

