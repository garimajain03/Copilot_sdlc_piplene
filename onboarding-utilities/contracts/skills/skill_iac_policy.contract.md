# Contract: Skill - IaC Policy

| Field | Value |
|-------|-------|
| contract_id | SC-IAC-POLICY |
| skill_name | IaC Policy Skill |
| category | policy |
| version | 1.0.0 |

## Role

Provides policy-as-code evaluation and governance checks for infrastructure plan outputs. Loaded by Agent 8 (IaC Specialist) and Agent 4 (Verifier) to enforce security, compliance, and architectural policy rules against IaC plans before apply recommendations.

## Supported Policy Engines (Pluggable)

| Engine | Detection / Config | Key Rules |
|--------|-------------------|-----------|
| Checkov | `checkov` CLI / `.checkov.yaml` | Security, compliance (CIS, SOC2, HIPAA, PCI-DSS) |
| tfsec / Trivy | `tfsec` or `trivy` CLI | Terraform security scanner rules |
| OPA / Conftest | `conftest` CLI / `policy/` directory | Rego policy evaluations |
| AWS SCP / Config Rules | AWS policy metadata / `aws` default | AWS Service Control Policies and Config posture |

## Capabilities (Abstract)

| Capability | Description |
|------------|-------------|
| `detect-policy-engine` | Identify available policy engine (Checkov, tfsec, OPA/conftest, AWS rules) |
| `load-policy-set` | Load workspace or organization policy rules |
| `scan-plan` | Scan `iac_plan_output.md` or JSON plan representation for policy violations |
| `map-to-compliance-framework` | Map findings to compliance frameworks (SOC2, HIPAA, PCI-DSS, ISO27001) |

## Policy Principles (Universal)

1. **Shift Left** - Evaluate policies at plan time before any live infrastructure changes
2. **Deterministic** - Rule evaluations yield reproducible Pass/Fail results
3. **Traceable** - Every violation links to specific line numbers, resource addresses, and policy IDs
4. **Compliance-Mapped** - Link security findings directly to compliance controls collected in onboarding

## Customization Points

| Point | How Customized | Default |
|-------|---------------|---------|
| Primary Engine | Auto-detected / Onboarding answers | Checkov / AWS Config rules |
| Policy Directory | Auto-detected | `policy/` or `.checkov.yaml` |
| Severity Threshold | Onboarding answers -> Compliance & Risk | High / Critical blockers |
| Compliance Mapping | Onboarding answers -> Compliance | SOC2, HIPAA, PCI-DSS |
