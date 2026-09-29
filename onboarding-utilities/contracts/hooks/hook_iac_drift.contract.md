# Contract: Hook - Infrastructure Drift Detection

| Field | Value |
|-------|-------|
| contract_id | HC-DRIFT |
| hook_name | Infrastructure Drift Detection |
| event | post_tool_use |
| version | 1.0.0 |

## Purpose

Performs plan-against-live-state comparison to detect infrastructure drift between cloud environment live state and target IaC definitions. Emits `drift_report.md` for awareness. Note: This hook monitors *infrastructure drift* (live cloud vs IaC state), distinct from contract migration drift.

## Trigger Conditions

- Fires post-tool-use when IaC plan or preview commands are executed
- Runs non-blocking (exit code 0/1 for informational reports)

## Guard Logic

### Detection Commands

| Tool | Command | Description |
|------|---------|-------------|
| Terraform | `terraform plan -detailed-exitcode` | Checks for drift against state |
| OpenTofu | `tofu plan -detailed-exitcode` | Checks for drift against state |
| Bicep | `az deployment group what-if` | Checks for live resource drift |
| AWS CDK | `cdk diff` | Compares deployed stack against template |

### Exit Codes

| Code | Meaning | Agent Behavior |
|------|---------|----------------|
| `0` | No infrastructure drift detected | Proceed normally |
| `1` | Infrastructure drift detected; `drift_report.md` written | Agent receives drift alert, includes in risk assessment |

## Customization Points

| Point | How Customized | Default |
|-------|---------------|---------|
| Drift Check Command | Auto-detected | `terraform plan -detailed-exitcode` |
| Output Artifact | Configured in hook | `drift_report.md` |
