# Contract: Skill - Testing

| Field | Value |
|-------|-------|
| contract_id | SC-TEST |
| skill_name | Testing Skill |
| category | testing |
| version | 1.0.0 |

## Role

Provides stack-specific testing conventions, patterns, and best practices. Loaded by Agent 6 (Tester) based on the detected tech stack.

## Supported Stacks (Pluggable)

| Stack | Detection | Key Libraries |
|-------|-----------|---------------|
| React + Jest + RTL | `@testing-library/react` in deps | Jest, RTL, MSW |
| NestJS + Jest | `@nestjs/testing` in deps | Jest, supertest |
| Express + Jest | `express` in deps (no NestJS) | Jest, supertest |
| Vue + Vitest | `vue`, `vitest` in deps | Vitest, vue-test-utils |
| Python + pytest | `pytest` in deps | pytest, pytest-mock |
| Go + testing | `go.mod` exists | Go testing package |

## Capabilities (Abstract)

| Capability | Description |
|------------|-------------|
| `detect-stack` | Identify test runner, libraries, conventions |
| `load-conventions` | Load stack-specific testing conventions |
| `discover-patterns` | Find existing test helpers, mocks, fixtures |
| `validate-test` | Check test against anti-patterns |

## Testing Principles (Universal)

1. **Deterministic** - No real network, time, or external services
2. **Behavior-driven** - Test what it does, not how it does it
3. **Isolated** - Each test independent of others
4. **Readable** - Test names describe expected behavior
5. **Maintainable** - No over-mocking, no brittle selectors

## Customization Points

| Point | How Customized | Default |
|-------|---------------|---------|
| Test runner | Auto-detected | Jest |
| Coverage threshold | Onboarding answers -> QA Coverage | 80% |
| Test file location | Auto-detected | Co-located or `__tests__/` |
| Mock patterns | Auto-detected | Project-specific |
| Custom testing skills | `skill_testing_custom.md` | None |

