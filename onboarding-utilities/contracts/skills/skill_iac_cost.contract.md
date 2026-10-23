# Contract: Skill - IaC Cost

| Field | Value |
|-------|-------|
| contract_id | SC-IAC-COST |
| skill_name | IaC Cost Skill |
| category | cost |
| version | 1.0.0 |

## Role

Provides cloud infrastructure cost estimation delta analysis on infrastructure plans. Loaded by Agent 8 (IaC Specialist) and consumed by Agent 5 (Critic) and human approval gates to evaluate financial impact before shipping.

## Supported Cost Sources (Pluggable)

| Tool / Provider | Detection | Key Output |
|-----------------|-----------|------------|
| Infracost | `infracost` CLI / `infracost.yml` | Monthly cost delta, breakdown by resource |
| AWS Cost Explorer / Pricing API | AWS provider default | Estimated hourly and monthly spend delta |
| Azure Cost Management | Azure provider | Estimated subscription cost delta |
| GCP Billing API | GCP provider | Estimated project cost delta |

## Capabilities (Abstract)

| Capability | Description |
|------------|-------------|
| `estimate-plan-delta` | Calculate monthly and hourly cost changes from `iac_plan_output.md` |
| `apply-budget-threshold` | Compare estimated cost surge against budget threshold |
| `format-cost-report` | Produce `cost_impact.md` summary for Critic and human review |

## Cost Principles (Universal)

1. **Visibility** - Surface cost deltas before infrastructure changes are applied
2. **Resource Granularity** - Break down costs by individual resource creation/modification
3. **Threshold-Gated** - Flag cost surges exceeding budget thresholds as ship blockers or approval gates

## Customization Points

| Point | How Customized | Default |
|-------|---------------|---------|
| Cost Engine | Auto-detected / Provider default | Infracost / AWS Pricing API |
| Monthly Budget Threshold | Client context | $500 delta threshold |
| Currency | Client context | USD |
