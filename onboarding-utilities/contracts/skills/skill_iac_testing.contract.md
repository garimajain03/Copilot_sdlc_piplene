# Contract: Skill - IaC Testing

| Field | Value |
|-------|-------|
| contract_id | SC-IAC-TEST |
| skill_name | IaC Testing Skill |
| category | testing |
| version | 1.0.0 |

## Role

Provides infrastructure testing patterns and execution conventions. Loaded by Agent 8 (IaC Specialist) and Agent 4 (Verifier) to validate IaC module syntaxes, unit tests, and integration assertions.

## Supported IaC Testing Frameworks (Pluggable)

| Framework | Detection | Key Conventions |
|-----------|-----------|-----------------|
| `terraform test` | HCL `*.tftest.hcl` files | Native Terraform module unit and integration tests |
| Terratest | Go tests with `terratest` package | Go-based infrastructure validation tests |
| Kitchen-Terraform | `kitchen.yml` | Ruby/Kitchen test harness for Terraform |
| Bicep test / build | `bicep build` validation | Azure Bicep template validation |

## Capabilities (Abstract)

| Capability | Description |
|------------|-------------|
| `run-iac-tests` | Execute detected IaC test runner (`terraform test`, Terratest) |
| `validate-module-contract` | Verify module input variables, outputs, and requirements |
| `format-iac-test-report` | Produce test execution report for Verifier |

## Customization Points

| Point | How Customized | Default |
|-------|---------------|---------|
| Testing Framework | Auto-detected | `terraform test` |
| Test Directory | Auto-detected | `tests/` or `*.tftest.hcl` |
