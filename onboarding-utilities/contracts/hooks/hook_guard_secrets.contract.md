# Contract: Hook - Guard Secrets

| Field | Value |
|-------|-------|
| contract_id | HC-GUARD-SEC |
| hook_name | Guard Secrets |
| event | pre_tool_use |
| version | 1.0.0 |

## Purpose

Prevents agents from reading, writing, or executing files that contain or may contain secrets, credentials, API keys, or other sensitive configuration.

## Trigger Conditions

- Fires on every `file_read`, `file_write`, `terminal` tool invocation
- Inspects file paths and command arguments

## Guard Logic

### Protected File Patterns (Configurable)

| Pattern | Reason |
|---------|--------|
| `.env`, `.env.*` | Environment variables with secrets |
| `*.pem`, `*.key`, `*.cert` | Certificates and private keys |
| `credentials.*`, `secrets.*` | Credential files |
| `.aws/credentials`, `.ssh/*` | Cloud/SSH credentials |
| `**/vault/**` | Secret vault directories |

### Protected Content Patterns

| Pattern | Reason |
|---------|--------|
| Lines matching `API_KEY=`, `SECRET=`, `PASSWORD=`, `TOKEN=` | Credential values |
| Base64-encoded blocks > 40 chars | Potential encoded secrets |

### Operations Blocked

| Operation | Example |
|-----------|---------|
| Read secret file | `read_file(.env)` |
| Write secret file | `create_file(.env.local)` |
| Cat/print secret file | `cat .env`, `echo $SECRET` |
| Copy secret file | `cp .env .env.backup` |
| Git add secret file | `git add .env` |

## Exit Codes

| Code | Meaning | Agent Behavior |
|------|---------|----------------|
| `0` | No secret files involved - proceed | Normal execution |
| `2` | Secret file access blocked | Agent receives error, must avoid secrets |

## Customization Points

| Point | How Customized | Default |
|-------|---------------|---------|
| Protected file patterns | Onboarding answers -> Security rules | `.env*`, `*.pem`, `*.key` |
| Additional patterns | `hook_guard_secrets_custom.md` | None |
| Allowed exceptions | `hook_guard_secrets_custom.md` | None (strict by default) |

