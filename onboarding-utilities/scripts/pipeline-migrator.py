#!/usr/bin/env python3
"""
pipeline-migrator.py — Version & Migration Manager for Generated SDLC Pipelines

Detects drift between generated agent definitions and their source contracts,
generates migration plans, and applies upgrades while preserving customer
customizations.

Usage:
  python3 pipeline-migrator.py check --contracts-dir contracts --agents-dir .github/agents
  python3 pipeline-migrator.py plan --contracts-dir contracts --agents-dir .github/agents --output migration_plan.md
  python3 pipeline-migrator.py apply --plan migration_plan.json --agents-dir .github/agents --backup-dir .sdlc-backup
  python3 pipeline-migrator.py diff --contracts-dir contracts --agents-dir .github/agents

Exit codes:
  0 — No drift / migration successful
  1 — Drift detected (check) or warnings during migration
  2 — Error
"""

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def extract_contract_metadata(content: str) -> dict:
    """Extract metadata from a contract file."""
    metadata = {}

    # Extract header table fields
    for field in ["contract_id", "agent_name", "version", "model_tier", "pipeline_position"]:
        match = re.search(rf"\|\s*{field}\s*\|\s*(.+?)\s*\|", content, re.IGNORECASE)
        if match:
            metadata[field] = match.group(1).strip()

    # Extract prime directive
    pd_match = re.search(r'>\s*"(.+?)"', content)
    if pd_match:
        metadata["prime_directive"] = pd_match.group(1)

    # Extract key outcomes
    outcomes = re.findall(r"\*\*\[OUTCOME-([A-Z0-9_-]+)\]\*\*\s*—\s*(.+)", content)
    metadata["outcomes"] = {k: v.strip() for k, v in outcomes}

    # Extract workflow steps
    steps = re.findall(r"### Step \d+:\s*(.+)", content)
    metadata["workflow_steps"] = steps

    # Extract quality checklist items
    checklist = re.findall(r"- \[ \] (.+)", content)
    metadata["quality_checklist"] = checklist

    # Extract customization points
    custom_points = re.findall(r"\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|", content)
    metadata["customization_points"] = len(custom_points)

    return metadata


def extract_agent_metadata(content: str) -> dict:
    """Extract metadata from a generated agent file."""
    metadata = {}

    # Extract YAML frontmatter
    fm_match = re.match(r"^---\s*\n(.+?)\n---", content, re.DOTALL)
    if fm_match:
        fm = fm_match.group(1)
        for field in ["name", "model", "description"]:
            match = re.search(rf'^{field}:\s*["\']?(.+?)["\']?\s*$', fm, re.MULTILINE)
            if match:
                metadata[f"frontmatter_{field}"] = match.group(1)

    # Extract prime directive
    pd_match = re.search(r'>\s*"(.+?)"', content)
    if pd_match:
        metadata["prime_directive"] = pd_match.group(1)

    # Extract version
    ver_match = re.search(r"## Version\s*\n(\S+)", content)
    if ver_match:
        metadata["version"] = ver_match.group(1)

    # Check for key sections
    sections = [
        "Behavioral Guardrails", "Custom Client Context",
        "Quality Checklist", "Access Restrictions", "Instructions"
    ]
    metadata["sections"] = {s: s in content for s in sections}

    # Check for outcome references
    outcomes = re.findall(r"\[OUTCOME-([A-Z0-9_-]+)\]", content)
    metadata["outcome_refs"] = outcomes

    return metadata


def compare_versions(contract_ver: str, agent_ver: str) -> str:
    """Compare semver strings. Returns: 'match', 'ahead', 'behind', 'unknown'."""
    try:
        c_parts = [int(x) for x in contract_ver.split(".")]
        a_parts = [int(x) for x in agent_ver.split(".")]
        if c_parts == a_parts:
            return "match"
        if c_parts > a_parts:
            return "behind"
        return "ahead"
    except (ValueError, AttributeError):
        return "unknown"


def check_drift(contracts_dir: str, agents_dir: str) -> list[dict]:
    """Check for drift between contracts and generated agents."""
    findings = []

    if not os.path.isdir(contracts_dir):
        findings.append({"severity": "error", "message": f"Contracts directory not found: {contracts_dir}"})
        return findings
    if not os.path.isdir(agents_dir):
        findings.append({"severity": "error", "message": f"Agents directory not found: {agents_dir}"})
        return findings

    # Load all contracts
    contracts = {}
    for f in os.listdir(contracts_dir):
        if f.endswith(".contract.md"):
            path = os.path.join(contracts_dir, f)
            with open(path, "r", encoding="utf-8") as fh:
                content = fh.read()
            meta = extract_contract_metadata(content)
            if meta.get("contract_id"):
                contracts[meta["contract_id"]] = {
                    "file": f, "metadata": meta, "content": content
                }

    # Load all generated agents
    agents = {}
    for f in os.listdir(agents_dir):
        if f.endswith(".md") and not f.startswith("agents-workflow"):
            path = os.path.join(agents_dir, f)
            with open(path, "r", encoding="utf-8") as fh:
                content = fh.read()
            meta = extract_agent_metadata(content)
            agents[f] = {"metadata": meta, "content": content}

    # Check each contract has a corresponding agent
    for cid, contract in contracts.items():
        cmeta = contract["metadata"]
        agent_name = cmeta.get("agent_name", "")

        # Find matching agent file
        matched_agent = None
        for af, agent in agents.items():
            ameta = agent["metadata"]
            if ameta.get("frontmatter_name", "").lower() == agent_name.lower():
                matched_agent = (af, agent)
                break
            # Also check if prime directive matches
            if ameta.get("prime_directive") == cmeta.get("prime_directive"):
                matched_agent = (af, agent)
                break

        if not matched_agent:
            findings.append({
                "severity": "warning",
                "type": "missing_agent",
                "contract_id": cid,
                "agent_name": agent_name,
                "message": f"No generated agent found for contract {cid} ({agent_name})"
            })
            continue

        af, agent = matched_agent
        ameta = agent["metadata"]

        # Version check
        c_ver = cmeta.get("version", "0.0.0")
        a_ver = ameta.get("version", "0.0.0")
        ver_status = compare_versions(c_ver, a_ver)
        if ver_status == "behind":
            findings.append({
                "severity": "warning",
                "type": "version_drift",
                "contract_id": cid,
                "agent_file": af,
                "contract_version": c_ver,
                "agent_version": a_ver,
                "message": f"Agent {af} version ({a_ver}) is behind contract ({c_ver})"
            })

        # Prime directive check
        c_pd = cmeta.get("prime_directive", "")
        a_pd = ameta.get("prime_directive", "")
        if c_pd and a_pd and c_pd != a_pd:
            findings.append({
                "severity": "error",
                "type": "prime_directive_mismatch",
                "contract_id": cid,
                "agent_file": af,
                "message": f"Prime directive mismatch in {af}"
            })

        # Outcome coverage check
        contract_outcomes = set(cmeta.get("outcomes", {}).keys())
        agent_outcomes = set(ameta.get("outcome_refs", []))
        missing_outcomes = contract_outcomes - agent_outcomes
        if missing_outcomes:
            findings.append({
                "severity": "warning",
                "type": "missing_outcomes",
                "contract_id": cid,
                "agent_file": af,
                "missing": list(missing_outcomes),
                "message": f"Agent {af} missing outcomes: {', '.join(missing_outcomes)}"
            })

        # Required sections check
        for section, present in ameta.get("sections", {}).items():
            if not present:
                findings.append({
                    "severity": "warning",
                    "type": "missing_section",
                    "contract_id": cid,
                    "agent_file": af,
                    "section": section,
                    "message": f"Agent {af} missing section: {section}"
                })

    return findings


def generate_plan(findings: list[dict], contracts_dir: str, agents_dir: str) -> dict:
    """Generate a migration plan from drift findings."""
    plan = {
        "generated_at": utc_now(),
        "contracts_dir": contracts_dir,
        "agents_dir": agents_dir,
        "total_findings": len(findings),
        "actions": [],
        "summary": {
            "agents_to_regenerate": [],
            "agents_to_update": [],
            "agents_to_create": [],
        }
    }

    for f in findings:
        ftype = f.get("type", "")
        if ftype == "missing_agent":
            plan["actions"].append({
                "action": "create",
                "contract_id": f["contract_id"],
                "agent_name": f["agent_name"],
                "reason": f["message"],
            })
            plan["summary"]["agents_to_create"].append(f["agent_name"])
        elif ftype == "prime_directive_mismatch":
            plan["actions"].append({
                "action": "regenerate",
                "contract_id": f["contract_id"],
                "agent_file": f["agent_file"],
                "reason": f["message"],
                "preserves_custom_context": True,
            })
            plan["summary"]["agents_to_regenerate"].append(f.get("agent_file", ""))
        elif ftype == "version_drift":
            plan["actions"].append({
                "action": "update",
                "contract_id": f["contract_id"],
                "agent_file": f["agent_file"],
                "from_version": f.get("agent_version"),
                "to_version": f.get("contract_version"),
                "reason": f["message"],
            })
            plan["summary"]["agents_to_update"].append(f.get("agent_file", ""))
        elif ftype in ("missing_outcomes", "missing_section"):
            agent_file = f.get("agent_file", "")
            if agent_file not in plan["summary"]["agents_to_update"]:
                plan["actions"].append({
                    "action": "update",
                    "contract_id": f["contract_id"],
                    "agent_file": agent_file,
                    "reason": f["message"],
                })
                plan["summary"]["agents_to_update"].append(agent_file)

    return plan


def format_plan_markdown(plan: dict) -> str:
    """Format migration plan as Markdown."""
    lines = [
        "# SDLC Pipeline Migration Plan",
        f"\nGenerated: {plan['generated_at']}",
        f"\n## Summary\n",
        f"- **Total findings:** {plan['total_findings']}",
        f"- **Agents to create:** {len(plan['summary']['agents_to_create'])}",
        f"- **Agents to regenerate:** {len(plan['summary']['agents_to_regenerate'])}",
        f"- **Agents to update:** {len(plan['summary']['agents_to_update'])}",
        f"\n## Actions\n",
        "| # | Action | Target | Reason |",
        "|---|--------|--------|--------|",
    ]
    for i, action in enumerate(plan["actions"], 1):
        target = action.get("agent_file", action.get("agent_name", ""))
        lines.append(f"| {i} | {action['action']} | {target} | {action['reason']} |")

    if not plan["actions"]:
        lines.append("\nNo migration actions needed — all agents are in sync with contracts.")

    lines.append(f"\n## Instructions\n")
    lines.append("1. Review this plan and approve/reject each action")
    lines.append("2. Run `python3 scripts/pipeline-migrator.py apply --plan migration_plan.json` to apply")
    lines.append("3. Customer customizations in `*_custom_client_context.md` files are preserved")
    lines.append("4. Run outcome inspector to validate: `python3 scripts/outcome-inspector.py --type generator --output-dir .`")

    return "\n".join(lines)


def backup_agents(agents_dir: str, backup_dir: str):
    """Create backup of current agents before migration."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(backup_dir, f"backup_{timestamp}")
    os.makedirs(backup_path, exist_ok=True)

    for f in os.listdir(agents_dir):
        src = os.path.join(agents_dir, f)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(backup_path, f))

    return backup_path


def cmd_check(args):
    """Check for drift between contracts and generated agents."""
    findings = check_drift(args.contracts_dir, args.agents_dir)

    errors = [f for f in findings if f["severity"] == "error"]
    warnings = [f for f in findings if f["severity"] == "warning"]

    output = {
        "status": "drift" if findings else "clean",
        "errors": len(errors),
        "warnings": len(warnings),
        "findings": findings,
    }

    if args.format == "markdown":
        lines = ["# Drift Check Report\n"]
        status = "❌ DRIFT DETECTED" if findings else "✅ NO DRIFT"
        lines.append(f"**Status:** {status}")
        lines.append(f"**Errors:** {len(errors)} | **Warnings:** {len(warnings)}\n")
        if findings:
            lines.append("| Severity | Type | Detail |")
            lines.append("|----------|------|--------|")
            for f in findings:
                lines.append(f"| {f['severity']} | {f.get('type', '')} | {f['message']} |")
        print("\n".join(lines))
    else:
        print(json.dumps(output, indent=2))

    sys.exit(1 if findings else 0)


def cmd_plan(args):
    """Generate migration plan."""
    findings = check_drift(args.contracts_dir, args.agents_dir)
    plan = generate_plan(findings, args.contracts_dir, args.agents_dir)

    if args.output:
        # Write JSON plan for machine consumption
        json_path = args.output.replace(".md", ".json") if args.output.endswith(".md") else args.output + ".json"
        os.makedirs(os.path.dirname(json_path) or ".", exist_ok=True)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(plan, f, indent=2)

        # Write Markdown plan for human review
        md_path = args.output if args.output.endswith(".md") else args.output + ".md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(format_plan_markdown(plan))

        print(json.dumps({
            "action": "plan",
            "json_plan": json_path,
            "markdown_plan": md_path,
            "total_actions": len(plan["actions"]),
        }))
    else:
        if args.format == "markdown":
            print(format_plan_markdown(plan))
        else:
            print(json.dumps(plan, indent=2))

    sys.exit(1 if plan["actions"] else 0)


def cmd_diff(args):
    """Show detailed diff between contracts and generated agents."""
    findings = check_drift(args.contracts_dir, args.agents_dir)

    print("# Contract ↔ Agent Diff Report\n")
    if not findings:
        print("All agents are in sync with their contracts.")
        sys.exit(0)

    for f in findings:
        print(f"## {f.get('type', 'unknown')}: {f.get('contract_id', 'N/A')}")
        print(f"- **Severity:** {f['severity']}")
        print(f"- **Detail:** {f['message']}")
        if "missing" in f:
            print(f"- **Missing items:** {', '.join(f['missing'])}")
        print()

    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="SDLC Pipeline Migration Manager")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # check
    check_p = subparsers.add_parser("check", help="Check for drift")
    check_p.add_argument("--contracts-dir", required=True)
    check_p.add_argument("--agents-dir", required=True)
    check_p.add_argument("--format", choices=["json", "markdown"], default="json")

    # plan
    plan_p = subparsers.add_parser("plan", help="Generate migration plan")
    plan_p.add_argument("--contracts-dir", required=True)
    plan_p.add_argument("--agents-dir", required=True)
    plan_p.add_argument("--output", help="Output file path for plan")
    plan_p.add_argument("--format", choices=["json", "markdown"], default="json")

    # diff
    diff_p = subparsers.add_parser("diff", help="Show detailed diff")
    diff_p.add_argument("--contracts-dir", required=True)
    diff_p.add_argument("--agents-dir", required=True)

    # apply (placeholder — actual apply requires the generator agent)
    apply_p = subparsers.add_parser("apply", help="Apply migration plan")
    apply_p.add_argument("--plan", required=True, help="Path to migration_plan.json")
    apply_p.add_argument("--agents-dir", required=True)
    apply_p.add_argument("--backup-dir", default=".sdlc-backup")

    args = parser.parse_args()

    commands = {
        "check": cmd_check,
        "plan": cmd_plan,
        "diff": cmd_diff,
    }

    if args.command == "apply":
        # Apply requires the SDLC Pipeline Generator agent to regenerate
        # This script only creates backups and outputs instructions
        if not os.path.exists(args.plan):
            print(f"Error: Plan file not found: {args.plan}", file=sys.stderr)
            sys.exit(2)
        with open(args.plan, "r") as f:
            plan = json.load(f)

        backup_path = backup_agents(args.agents_dir, args.backup_dir)
        print(json.dumps({
            "action": "apply",
            "backup_created": backup_path,
            "actions_to_apply": len(plan.get("actions", [])),
            "instruction": "Run the SDLC Pipeline Generator with --migration-plan flag to regenerate affected agents",
        }))
        sys.exit(0)

    try:
        commands[args.command](args)
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
