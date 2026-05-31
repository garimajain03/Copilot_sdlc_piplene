# Custom Client Context — {{AGENT_NAME}}

> This file is loaded by **{{AGENT_NAME}}** (Agent {{AGENT_NUMBER}}) at the start of every run.
> Add any client-specific context that should influence this agent's behavior.
> This file is optional — the agent works without it but may produce more
> accurate results with domain-specific guidance.

---

## Domain-Specific Rules

<!-- 
Add domain terminology, business rules, and conventions specific to your organization.
Examples:
- "Our domain model uses 'Encounter' instead of 'Visit'"
- "All monetary values must use BigDecimal, never floating point"
- "Patient data requires HIPAA-compliant encryption at rest"
-->

## Additional Constraints

<!--
Add constraints beyond the standard behavioral guardrails.
Examples:
- "Never modify files in the `legacy/` directory without explicit approval"
- "All new components must be Server Components by default (Next.js App Router)"
- "Database queries must use parameterized queries only — no string concatenation"
-->

## Patterns & Preferences

<!--
Add preferred patterns, libraries, and approaches.
Examples:
- "Prefer Zustand over Redux for state management"
- "Use zod for runtime validation of API responses"
- "Follow the Repository pattern for data access"
- "Error handling must use Result<T, E> pattern, not try/catch"
-->

## Examples

<!--
Add examples of expected behavior or output.
Examples:
- "When creating a new API endpoint, follow this structure: ..."
- "When writing tests, use this factory pattern: ..."
- "Error messages should follow this format: ..."
-->

---

> **Priority Rules:**
> - Custom context takes precedence over default behavior
> - Custom context NEVER overrides the Prime Directive
> - Custom context NEVER overrides Access Restrictions
> - Custom context NEVER overrides security guardrails
