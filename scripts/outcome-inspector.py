#!/usr/bin/env python3
"""
outcome-inspector.py — Self-validation of agent outputs before delivery

Inspects generated artifacts for completeness, consistency, and quality.
Used by both Preflight Agent and Pipeline Generator to validate their own
outputs before presenting to the customer.

Usage:
  python3 outcome-inspector.py --type preflight --output-dir /path/to/outputs
  python3 outcome-inspector.py --type generator --output-dir /path/to/outputs --contracts-dir /path/to/contracts
  python3 outcome-inspector.py --type instructions --instructions-dir /path/to/.github/instructions

Exit codes:
  0 — All checks passed
  1 — Warnings found (non-blocking)
  2 — Errors found (blocking — must fix before delivery)
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path


class Inspector:
    def __init__(self):
        self.findings = []

    def error(self, category: str, message: str, file: str = ""):
        self.findings.append({"severity": "error", "category": category, "message": message, "file": file})

    def warning(self, category: str, message: str, file: str = ""):
        self.findings.append({"severity": "warning", "category": category, "message": message, "file": file})

    def info(self, category: str, message: str, file: str = ""):
        self.findings.append({"severity": "info", "category": category, "message": message, "file": file})

    def has_errors(self) -> bool:
        return any(f["severity"] == "error" for f in self.findings)

    def has_warnings(self) -> bool:
        return any(f["severity"] == "warning" for f in self.findings)

    def report(self) -> dict:
        errors = [f for f in self.findings if f["severity"] == "error"]
        warnings = [f for f in self.findings if f["severity"] == "warning"]
        infos = [f for f in self.findings if f["severity"] == "info"]
        return {
            "status": "fail" if errors else ("warn" if warnings else "pass"),
            "errors": len(errors),
            "warnings": len(warnings),
            "info": len(infos),
            "findings": self.findings,
        }

    def report_markdown(self) -> str:
        r = self.report()
        lines = []
        lines.append(f"# Outcome Inspection Report\n")
        status_emoji = {"pass": "✅", "warn": "⚠️", "fail": "❌"}
        lines.append(f"**Status:** {status_emoji.get(r['status'], '?')} {r['status'].upper()}")
        lines.append(f"**Errors:** {r['errors']} | **Warnings:** {r['warnings']} | **Info:** {r['info']}\n")

        if r["findings"]:
            lines.append("| Severity | Category | Message | File |")
            lines.append("|----------|----------|---------|------|")
            for f in r["findings"]:
                sev = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}.get(f["severity"], "?")
                lines.append(f"| {sev} {f['severity']} | {f['category']} | {f['message']} | `{f.get('file', '')}` |")

        return "\n".join(lines)


def inspect_preflight(output_dir: str, inspector: Inspector):
    """Inspect Preflight Agent outputs."""

    # Check required files exist
    required_files = {
        "setup.sh": "Setup script",
        "preflight_report.md": "Preflight report",
        "codebase_scan_results.md": "Codebase scan results",
    }

    # Look in sdlc-pipeline subdir too
    search_dirs = [output_dir, os.path.join(output_dir, ".github", "sdlc-pipeline")]

    for filename, desc in required_files.items():
        found = False
        for d in search_dirs:
            if os.path.exists(os.path.join(d, filename)):
                found = True
                break
        if not found:
            inspector.error("completeness", f"Missing required file: {filename} ({desc})")

    # Check setup.sh is not empty and has shebang
    setup_path = os.path.join(output_dir, "setup.sh")
    if os.path.exists(setup_path):
        with open(setup_path, "r", encoding="utf-8") as f:
            content = f.read()
        if not content.strip():
            inspector.error("quality", "setup.sh is empty", "setup.sh")
        elif not content.startswith("#!/"):
            inspector.error("quality", "setup.sh missing shebang line", "setup.sh")
        if "read -rs" not in content and "read -s" not in content:
            inspector.warning("security", "setup.sh may not protect secret input (no read -rs found)", "setup.sh")
        if ".env" in content and ".gitignore" not in content:
            inspector.warning("security", "setup.sh creates .env but may not add to .gitignore", "setup.sh")

    # Check hooks.json
    hooks_path = os.path.join(output_dir, ".github", "hooks", "hooks.json")
    if os.path.exists(hooks_path):
        try:
            with open(hooks_path, "r") as f:
                hooks = json.load(f)
            if "hooks" not in hooks:
                inspector.error("structure", "hooks.json missing 'hooks' key", "hooks.json")
            else:
                if "PreToolUse" not in hooks["hooks"]:
                    inspector.warning("security", "No PreToolUse hooks registered — guards disabled", "hooks.json")
        except json.JSONDecodeError:
            inspector.error("quality", "hooks.json is not valid JSON", "hooks.json")
    else:
        inspector.warning("completeness", "hooks.json not found")

    # Check instructions files
    instructions_dir = os.path.join(output_dir, ".github", "instructions")
    if os.path.isdir(instructions_dir):
        instruction_files = [f for f in os.listdir(instructions_dir) if f.endswith(".instructions.md")]
        if not instruction_files:
            inspector.warning("completeness", "No .instructions.md files generated", instructions_dir)
        else:
            inspector.info("completeness", f"{len(instruction_files)} instruction files generated")
            for ifile in instruction_files:
                ipath = os.path.join(instructions_dir, ifile)
                with open(ipath, "r", encoding="utf-8") as f:
                    content = f.read()
                if len(content) < 100:
                    inspector.warning("quality", f"Instructions file is very short ({len(content)} chars)", ifile)
                if "applyTo:" not in content:
                    inspector.warning("structure", f"Missing applyTo frontmatter", ifile)
    else:
        inspector.warning("completeness", "No .github/instructions/ directory found")

    # Check connector skills
    skills_dir = os.path.join(output_dir, ".github", "skills")
    if os.path.isdir(skills_dir):
        skills = [d for d in os.listdir(skills_dir) if os.path.isdir(os.path.join(skills_dir, d))]
        if not skills:
            inspector.warning("completeness", "No connector skills generated")
        else:
            for skill in skills:
                skill_md = os.path.join(skills_dir, skill, "SKILL.md")
                if not os.path.exists(skill_md):
                    inspector.error("completeness", f"Skill {skill} missing SKILL.md", skill)


def inspect_generator(output_dir: str, contracts_dir: str, inspector: Inspector):
    """Inspect Pipeline Generator outputs against contracts."""

    # Check agent files exist for each contract
    agents_dir = os.path.join(output_dir, ".github", "agents")
    if not os.path.isdir(agents_dir):
        inspector.error("completeness", "No .github/agents/ directory found")
        return

    agent_files = [f for f in os.listdir(agents_dir) if f.endswith(".md")]
    if len(agent_files) < 8:
        inspector.warning("completeness", f"Only {len(agent_files)} agent files found (expected ~12)")

    # Check orchestrator exists
    orch_files = [f for f in agent_files if "orchestrator" in f.lower()]
    if not orch_files:
        inspector.error("completeness", "No orchestrator agent definition found")

    # Check each agent file has required sections
    required_sections = [
        "Prime Directive",
        "Behavioral Guardrails",
        "Custom Client Context",
        "Quality Checklist",
    ]

    for agent_file in agent_files:
        filepath = os.path.join(agents_dir, agent_file)
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        for section in required_sections:
            if section not in content:
                inspector.warning("consistency", f"Missing section: {section}", agent_file)

        # Check frontmatter
        if not content.startswith("---"):
            inspector.warning("structure", "Missing YAML frontmatter", agent_file)
        elif "model:" not in content.split("---")[1] if len(content.split("---")) > 1 else True:
            inspector.warning("structure", "Missing model in frontmatter", agent_file)

    # Check custom client context templates
    context_dir = os.path.join(output_dir, ".github", "sdlc-pipeline", "client-context")
    if os.path.isdir(context_dir):
        context_files = [f for f in os.listdir(context_dir) if f.endswith("_custom_client_context.md")]
        if len(context_files) < 8:
            inspector.warning("completeness",
                              f"Only {len(context_files)} custom context templates (expected ~12)")
    else:
        inspector.warning("completeness", "No client-context directory found")

    # Check generation report
    report_path = os.path.join(output_dir, ".github", "sdlc-pipeline", "generation_report.md")
    if not os.path.exists(report_path):
        inspector.error("completeness", "Missing generation_report.md")

    # Validate against contracts if available
    if contracts_dir and os.path.isdir(contracts_dir):
        contract_files = [f for f in os.listdir(contracts_dir) if f.endswith(".contract.md")]
        for cf in contract_files:
            cpath = os.path.join(contracts_dir, cf)
            with open(cpath, "r", encoding="utf-8") as f:
                contract_content = f.read()

            # Extract contract_id
            cid_match = re.search(r"\|\s*contract_id\s*\|\s*(\S+)\s*\|", contract_content)
            cid = cid_match.group(1) if cid_match else cf

            # Extract prime directive from contract
            pd_match = re.search(r'> "(.+?)"', contract_content)
            if pd_match:
                pd = pd_match.group(1)
                # Check if any generated agent contains this directive
                found_in_agent = False
                for af in agent_files:
                    with open(os.path.join(agents_dir, af), "r", encoding="utf-8") as f:
                        if pd in f.read():
                            found_in_agent = True
                            break
                if not found_in_agent:
                    inspector.warning("consistency",
                                      f"Contract {cf} prime directive not found in any generated agent", cf)

            # Contract compliance: Key Outcomes coverage
            outcomes = re.findall(r"\*\*\[OUTCOME-([A-Z0-9_-]+)\]\*\*", contract_content)
            if outcomes:
                for af in agent_files:
                    with open(os.path.join(agents_dir, af), "r", encoding="utf-8") as f:
                        agent_content = f.read()
                    # Check if this agent corresponds to this contract (by prime directive)
                    if pd_match and pd_match.group(1) in agent_content:
                        missing = [o for o in outcomes if f"OUTCOME-{o}" not in agent_content]
                        if missing:
                            inspector.warning("compliance",
                                              f"Agent {af} missing Key Outcomes from {cid}: {', '.join(missing)}", af)

    # Cross-reference integrity: verify hook/skill file references
    hooks_path = os.path.join(output_dir, ".github", "hooks", "hooks.json")
    if os.path.exists(hooks_path):
        try:
            with open(hooks_path, "r") as f:
                hooks_config = json.load(f)
            # Verify referenced hook scripts exist
            for event_type, event_hooks in hooks_config.get("hooks", {}).items():
                if isinstance(event_hooks, list):
                    for hook in event_hooks:
                        script = hook.get("script", hook.get("path", ""))
                        if script:
                            script_path = os.path.join(output_dir, script)
                            if not os.path.exists(script_path):
                                inspector.error("cross_reference",
                                                f"hooks.json references non-existent script: {script}", "hooks.json")
        except (json.JSONDecodeError, IOError):
            pass

    # Verify skill directories have SKILL.md
    skills_dir = os.path.join(output_dir, ".github", "skills")
    if os.path.isdir(skills_dir):
        for skill_name in os.listdir(skills_dir):
            skill_path = os.path.join(skills_dir, skill_name)
            if os.path.isdir(skill_path):
                skill_md = os.path.join(skill_path, "SKILL.md")
                if not os.path.exists(skill_md):
                    inspector.error("cross_reference",
                                    f"Skill directory {skill_name}/ missing SKILL.md", skill_name)

    # Frontmatter schema validation for agents
    for agent_file in agent_files:
        filepath = os.path.join(agents_dir, agent_file)
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                fm = parts[1]
                if "name:" not in fm:
                    inspector.error("frontmatter", "Missing 'name' in frontmatter", agent_file)
                if "model:" not in fm:
                    inspector.error("frontmatter", "Missing 'model' in frontmatter", agent_file)
                if "tools:" not in fm:
                    inspector.warning("frontmatter", "Missing 'tools' in frontmatter", agent_file)


def inspect_instructions(instructions_dir: str, inspector: Inspector):
    """Inspect generated instruction files."""
    if not os.path.isdir(instructions_dir):
        inspector.error("completeness", f"Instructions directory not found: {instructions_dir}")
        return

    files = [f for f in os.listdir(instructions_dir) if f.endswith(".instructions.md")]
    if not files:
        inspector.error("completeness", "No instruction files found")
        return

    for ifile in files:
        filepath = os.path.join(instructions_dir, ifile)
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        # Check required sections
        required = ["Repository Structure", "Dependencies", "Tools & Technologies"]
        for section in required:
            if section not in content:
                inspector.warning("completeness", f"Missing section: {section}", ifile)

        # Check applyTo frontmatter
        if "applyTo:" not in content:
            inspector.error("structure", "Missing applyTo frontmatter — file won't be applied", ifile)

        # Check not too short
        if len(content) < 200:
            inspector.warning("quality", f"File is very short ({len(content)} chars) — may lack detail", ifile)

        # Check for placeholder content
        if "<!-- " in content and content.count("<!-- ") > 5:
            inspector.warning("quality", "Many placeholder comments — consider filling in details", ifile)


def main():
    parser = argparse.ArgumentParser(description="SDLC Pipeline Outcome Inspector")
    parser.add_argument("--type", required=True, choices=["preflight", "generator", "instructions"],
                        help="Type of output to inspect")
    parser.add_argument("--output-dir", help="Directory containing outputs to inspect")
    parser.add_argument("--contracts-dir", help="Directory containing contracts (for generator validation)")
    parser.add_argument("--instructions-dir", help="Directory containing instruction files")
    parser.add_argument("--format", choices=["json", "markdown"], default="json",
                        help="Output format")
    args = parser.parse_args()

    inspector = Inspector()

    if args.type == "preflight":
        if not args.output_dir:
            print("Error: --output-dir required for preflight inspection", file=sys.stderr)
            sys.exit(1)
        inspect_preflight(args.output_dir, inspector)

    elif args.type == "generator":
        if not args.output_dir:
            print("Error: --output-dir required for generator inspection", file=sys.stderr)
            sys.exit(1)
        inspect_generator(args.output_dir, args.contracts_dir or "", inspector)

    elif args.type == "instructions":
        if not args.instructions_dir:
            print("Error: --instructions-dir required for instructions inspection", file=sys.stderr)
            sys.exit(1)
        inspect_instructions(args.instructions_dir, inspector)

    if args.format == "markdown":
        print(inspector.report_markdown())
    else:
        print(json.dumps(inspector.report(), indent=2))

    if inspector.has_errors():
        sys.exit(2)
    elif inspector.has_warnings():
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
