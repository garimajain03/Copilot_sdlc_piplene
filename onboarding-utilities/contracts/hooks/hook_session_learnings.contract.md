# Contract: Hook - Session Learnings

| Field | Value |
|-------|-------|
| contract_id | HC-LEARN |
| hook_name | Session Learnings |
| event | session_stop |
| version | 1.0.0 |

## Purpose

At the end of each agent session, extracts learnings, patterns discovered, and mistakes made. Stores them in persistent memory for future sessions.

## Trigger Conditions

- Fires when an agent session ends (Stop event)
- Runs after all other cleanup hooks

## Logic

1. Analyze session conversation for:
   - Codebase patterns discovered
   - Common mistakes corrected
   - User preferences expressed
   - Conventions confirmed
2. Store relevant learnings in memory system
3. Skip if session was trivial (< 3 tool invocations)

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Learnings stored (or nothing worth storing) |
| `1` | Error storing - log but don't block |

## Customization Points

| Point | How Customized | Default |
|-------|---------------|---------|
| Memory storage path | Generated from setup | `/memories/repo/` |
| Learning categories | `hook_learnings_custom.md` | Patterns, mistakes, preferences |
| Minimum session length | `hook_learnings_custom.md` | 3 tool invocations |

