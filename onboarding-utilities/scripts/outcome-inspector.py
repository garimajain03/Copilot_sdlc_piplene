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
import py_compile
import re
import sys
from pathlib import Path


GENERATED_AGENT_PATTERN = re.compile(r"^agent\d+[a-z]?_.*\.md$")
RUNTIME_STATE_DIR = os.path.join(".github", "sdlc-pipeline-runtime")
PLACEHOLDER_SIGNATURES = [
    "The following workflow logic is applied exactly from the contract:",
    "Pipeline sequence, routing table, and finalization protocol from contract:",
    "Key Outcomes to satisfy:",
]


def _resolve_repo_root(output_dir: str) -> Path:
    out = Path(output_dir).resolve()
    if out.name == "agents-repo" and out.parent.name == "outputs":
        return out.parent.parent
    return Path.cwd().resolve()


def _pipeline_dirs(output_dir: str) -> tuple[Path, Path]:
    repo_root = _resolve_repo_root(output_dir)
    root_pipeline = repo_root / ".github" / "sdlc-pipeline"
    legacy_pipeline = Path(output_dir).resolve() / ".github" / "sdlc-pipeline"
    return root_pipeline, legacy_pipeline


def _is_empty_section(content: str, section_name: str) -> bool:
    """Return True when a section exists but has no substantive body before next heading."""
    marker = f"## {section_name}"
    idx = content.find(marker)
    if idx == -1:
        return False

    tail = content[idx + len(marker):]
    lines = tail.splitlines()
    body_lines = []
    for line in lines:
        if line.strip().startswith("## "):
            break
        body_lines.append(line)

    for line in body_lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped in ("---", "|", "|-", "|--", "|---"):
            continue
        return False
    return True


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

    root_pipeline, legacy_pipeline = _pipeline_dirs(output_dir)
    repo_root = _resolve_repo_root(output_dir)

    # Check required files exist
    required_files = {
        "setup.sh": "Setup script",
        "setup.ps1": "Windows setup script",
        "preflight_report.md": "Preflight report",
        "codebase_scan_results.md": "Codebase scan results",
    }

    # Look in root pipeline state first, then legacy output-side path.
    search_dirs = [output_dir, str(root_pipeline), str(legacy_pipeline)]

    for filename, desc in required_files.items():
        found = False
        for d in search_dirs:
            if os.path.exists(os.path.join(d, filename)):
                found = True
                break
        if not found:
            inspector.error("completeness", f"Missing required file: {filename} ({desc})")

    # Enforce setup scripts are generated only in output_dir (no duplicates elsewhere).
    expected_setup_paths = {
        "setup.sh": Path(output_dir).resolve() / "setup.sh",
        "setup.ps1": Path(output_dir).resolve() / "setup.ps1",
    }
    duplicate_candidates = [
        repo_root / "setup.sh",
        repo_root / "setup.ps1",
        repo_root / ".github" / "setup.sh",
        repo_root / ".github" / "setup.ps1",
    ]
    for candidate in duplicate_candidates:
        name = candidate.name
        expected = expected_setup_paths.get(name)
        if expected and candidate.exists() and candidate.resolve() != expected:
            inspector.error(
                "consistency",
                f"Duplicate setup script found outside outputs/agents-repo: {candidate}",
                str(candidate),
            )

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
        if "install-observability.sh" not in content:
            inspector.error("quality", "setup.sh missing observability installer integration", "setup.sh")
        if ".github/scripts/install-observability.sh" not in content and "scripts/install-observability.sh" not in content:
            inspector.warning("quality", "setup.sh should resolve generated .github/scripts/install-observability.sh path", "setup.sh")

    # Check setup.ps1 basic quality
    setup_ps1_path = os.path.join(output_dir, "setup.ps1")
    if os.path.exists(setup_ps1_path):
        with open(setup_ps1_path, "r", encoding="utf-8") as f:
            content = f.read()
        if not content.strip():
            inspector.error("quality", "setup.ps1 is empty", "setup.ps1")
        if "[CmdletBinding()]" not in content:
            inspector.warning("quality", "setup.ps1 missing CmdletBinding declaration", "setup.ps1")
        if "Copy-Item \".env.template\" \".env\"" in content and "Test-Path \".env.template\"" not in content:
            inspector.warning("quality", "setup.ps1 copies .env.template without existence check", "setup.ps1")
        if "install-observability.ps1" not in content:
            inspector.error("quality", "setup.ps1 missing observability installer integration", "setup.ps1")
        if ".github\\scripts\\install-observability.ps1" not in content and "scripts\\install-observability.ps1" not in content:
            inspector.warning("quality", "setup.ps1 should resolve generated .github/scripts/install-observability.ps1 path", "setup.ps1")

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

    root_pipeline, legacy_pipeline = _pipeline_dirs(output_dir)
    if legacy_pipeline.exists():
        inspector.error(
            "consistency",
            "Legacy pipeline state directory exists at outputs/agents-repo/.github/sdlc-pipeline; pipeline state must be under root .github/sdlc-pipeline",
            str(legacy_pipeline),
        )

    # Check agent files exist for each contract
    agents_dir = os.path.join(output_dir, ".github", "agents")
    if not os.path.isdir(agents_dir):
        inspector.error("completeness", "No .github/agents/ directory found")
        return

    agent_files = [
        f for f in os.listdir(agents_dir)
        if f.endswith(".md") and (GENERATED_AGENT_PATTERN.match(f) or f == "orchestrator.md")
    ]
    if len(agent_files) < 8:
        inspector.warning("completeness", f"Only {len(agent_files)} generated agent files found (expected ~12)")

    if len(agent_files) == 0:
        inspector.error("completeness", "No generated pipeline agents found (agent*.md / orchestrator.md)")
        return

    pr_reviewer = os.path.join(agents_dir, "pr-review-fixer.md")
    if not os.path.exists(pr_reviewer):
        inspector.error("completeness", "Missing PR review utility agent file: pr-review-fixer.md", pr_reviewer)

    pipeline_preflight = os.path.join(output_dir, ".github", "scripts", "pipeline-preflight.py")
    if not os.path.exists(pipeline_preflight):
        inspector.error(
            "completeness",
            "Missing required pipeline preflight script: .github/scripts/pipeline-preflight.py",
            pipeline_preflight,
        )
    else:
        try:
            with open(pipeline_preflight, "r", encoding="utf-8") as pf:
                preflight_content = pf.read()
            if "parents[4]" in preflight_content:
                inspector.error(
                    "consistency",
                    "pipeline-preflight.py uses fragile root resolution (parents[4]); use parents[2] for .github/scripts location",
                    pipeline_preflight,
                )
            required_runtime_tokens = ["feature_id", "outputs", "checkpoint.md", "orchestration_tracker.md"]
            for token in required_runtime_tokens:
                if token not in preflight_content:
                    inspector.error(
                        "consistency",
                        f"pipeline-preflight.py missing runtime initialization token: {token}",
                        pipeline_preflight,
                    )
        except OSError:
            pass

    # Ensure generated observability installers are full reference implementations (not stubs).
    installers = {
        ".github/scripts/install-observability.sh": [
            "opentelemetry-collector-releases/releases/download",
            "prometheus/releases/download",
            "otelcol-contrib",
            "prometheus",
        ],
        ".github/scripts/install-observability.ps1": [
            "opentelemetry-collector-releases/releases/download",
            "prometheus/releases/download",
            "otelcol-contrib.exe",
            "prometheus.exe",
        ],
    }
    placeholder_markers = [
        "placeholder",
        "predownloaded binaries",
        "external installer flows",
        "use onboarding-utilities/scripts/install-observability",
    ]
    for rel_path, required_tokens in installers.items():
        full_path = os.path.join(output_dir, *rel_path.split("/"))
        if not os.path.exists(full_path):
            inspector.error("completeness", f"Missing required installer script: {rel_path}", rel_path)
            continue
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                installer_content = f.read()
        except OSError:
            inspector.error("quality", f"Unable to read installer script: {rel_path}", rel_path)
            continue

        if len(installer_content.strip()) < 800:
            inspector.error(
                "quality",
                f"Installer script appears too short to be a full implementation: {rel_path}",
                rel_path,
            )

        lowered = installer_content.lower()
        for marker in placeholder_markers:
            if marker in lowered:
                inspector.error(
                    "quality",
                    f"Installer script contains placeholder/stub marker '{marker}': {rel_path}",
                    rel_path,
                )

        for token in required_tokens:
            if token not in installer_content:
                inspector.error(
                    "consistency",
                    f"Installer script missing required download/runtime token '{token}': {rel_path}",
                    rel_path,
                )

    # Check orchestrator exists
    orch_files = [f for f in agent_files if "orchestrator" in f.lower()]
    if not orch_files:
        inspector.error("completeness", "No orchestrator agent definition found")

    # Check each agent file has required sections
    required_sections = [
        "Metadata",
        "Role",
        "Prime Directive",
        "Behavioral Guardrails",
        "Client Onboarding Context",
        "Inputs",
        "Input Validation",
        "Outputs",
        "Output Handling",
        "Connector Integration",
        "Instructions",
        "Checkpointing Strategy",
        "Resume Protocol",
        "Re-run Protocol",
        "Custom Client Context",
        "Quality Checklist",
        "Completion Criteria",
        "Access Restrictions",
        "Hooks",
    ]

    for agent_file in agent_files:
        filepath = os.path.join(agents_dir, agent_file)
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        for signature in PLACEHOLDER_SIGNATURES:
            if signature in content:
                inspector.error("quality", f"Generated artifact contains placeholder signature: {signature}", agent_file)

        for section in ["Role", "Inputs", "Outputs", "Instructions", "Quality Checklist", "Access Restrictions"]:
            if _is_empty_section(content, section):
                inspector.error("quality", f"Section is empty: {section}", agent_file)

        for section in required_sections:
            if section not in content:
                inspector.error("consistency", f"Missing section: {section}", agent_file)

        # Check frontmatter
        if not content.startswith("---"):
            inspector.error("structure", "Missing YAML frontmatter", agent_file)
        elif "model:" not in content.split("---")[1] if len(content.split("---")) > 1 else True:
            inspector.error("structure", "Missing model in frontmatter", agent_file)

        if "python3 .github/hooks/" in content:
            inspector.warning("cross_platform", "Hook commands use python3; consider portable python command for Windows", agent_file)

        if "outputs/agents-repo/.github/sdlc-pipeline/" in content:
            inspector.error(
                "consistency",
                "Generated agent contains legacy pipeline-state path outputs/agents-repo/.github/sdlc-pipeline/",
                agent_file,
            )

        # Detect obvious duplicate top-level headings.
        top_headings = re.findall(r"^##\s+(.+?)\s*$", content, flags=re.MULTILINE)
        seen = set()
        dups = set()
        for h in top_headings:
            if h in seen:
                dups.add(h)
            seen.add(h)
        if dups:
            inspector.error("consistency", f"Duplicate top-level sections: {', '.join(sorted(dups))}", agent_file)

        # Frontmatter hook shape checks: worker agents vs orchestrator.
        parts = content.split("---", 2)
        fm = parts[1] if len(parts) >= 3 else ""

        # Guard malformed quote usage for argument hint keys in frontmatter.
        for line in fm.splitlines():
            l = line.strip()
            if l.startswith("argument-hint:") or l.startswith("argumentHint:"):
                if l.count('"') % 2 != 0:
                    inspector.error("frontmatter", "Malformed quoted string in argument hint", agent_file)

        if agent_file == "orchestrator.md":
            if "agents:" not in fm:
                inspector.error("frontmatter", "Orchestrator missing 'agents' list in frontmatter", agent_file)
            required_hook_events = ["SessionStart:", "PreToolUse:", "PostToolUse:", "Stop:"]
            for ev in required_hook_events:
                if ev not in fm:
                    inspector.error("frontmatter", f"Orchestrator missing hook event: {ev.rstrip(':')}", agent_file)
            if fm.count("SessionStart:") > 1 or fm.count("PreToolUse:") > 1 or fm.count("PostToolUse:") > 1 or fm.count("Stop:") > 1:
                inspector.error("frontmatter", "Orchestrator has duplicate hook event blocks", agent_file)
            if "otel-hook.py" not in fm:
                inspector.error("frontmatter", "Orchestrator frontmatter must include otel-hook.py", agent_file)
            if "observability-hook.py" not in fm:
                inspector.error("frontmatter", "Orchestrator frontmatter must include observability-hook.py", agent_file)
            if "session-learnings.py" in fm:
                inspector.error("frontmatter", "Orchestrator must not use session-learnings.py in frontmatter hooks", agent_file)
            command_entries = len(re.findall(r"-\s+type:\s+command", fm))
            timeout_entries = len(re.findall(r"\n\s*timeout:\s*\d+", fm))
            if command_entries > 0 and timeout_entries < command_entries:
                inspector.error("frontmatter", "Orchestrator hook entries must include timeout for every command", agent_file)
            if "PR.md" not in content:
                inspector.error("consistency", "Orchestrator must include PR.md output artifact", agent_file)
            if "pr_creation_report.md" not in content:
                inspector.error("consistency", "Orchestrator must include pr_creation_report.md output artifact", agent_file)
            if "telemetry_report.md" not in content:
                inspector.error("consistency", "Orchestrator must include telemetry_report.md output artifact", agent_file)
            if "cost_report.md" not in content:
                inspector.error("consistency", "Orchestrator must include cost_report.md output artifact", agent_file)
            if "outputs/<FEATURE_ID>/" not in content and "outputs/<feature_id>/" not in content and "outputs/{feature_id}/" not in content:
                inspector.warning("consistency", "Orchestrator should explicitly document outputs/<FEATURE_ID>/ runtime artifact path", agent_file)
        else:
            if "PreToolUse:" not in fm:
                inspector.error("frontmatter", "Worker agent missing PreToolUse hook block", agent_file)
            if "PostToolUse:" in fm or "SessionStart:" in fm or "Stop:" in fm:
                inspector.error("frontmatter", "Worker agent frontmatter must only contain PreToolUse hooks", agent_file)
            if "argument-hint:" not in fm:
                inspector.warning("frontmatter", "Worker agent missing 'argument-hint' key", agent_file)

    # Check custom client context templates
    context_dir = root_pipeline / "client-context"
    if context_dir.is_dir():
        context_files = [f for f in os.listdir(context_dir) if f.endswith("_custom_client_context.md")]
        if len(context_files) < 8:
            inspector.warning("completeness",
                              f"Only {len(context_files)} custom context templates (expected ~12)")

        # Ensure each generated agent has a matching slug-based context template.
        context_set = set(context_files)
        for af in agent_files:
            if af == "orchestrator.md":
                expected = "orchestrator_custom_client_context.md"
            else:
                expected = af.replace(".md", "") + "_custom_client_context.md"
            if expected not in context_set:
                inspector.error("cross_reference", f"Missing matching client context template: {expected}", af)
    else:
        inspector.warning("completeness", "No client-context directory found")

    # Check generation report at root pipeline location; allow runtime fallback for compatibility.
    report_candidates = [
        str(root_pipeline / "generation_report.md"),
        str(_resolve_repo_root(output_dir) / RUNTIME_STATE_DIR / "generation_report.md"),
    ]
    if not any(os.path.exists(path) for path in report_candidates):
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

            # Ensure hooks configuration uses a single script naming family.
            scripts = []
            for _, event_hooks in hooks_config.get("hooks", {}).items():
                if isinstance(event_hooks, list):
                    for hook in event_hooks:
                        script = hook.get("script", hook.get("path", ""))
                        if script:
                            scripts.append(Path(script).name)
            forbidden_aliases = {"hook_observability.py", "hook_otel_telemetry.py"}
            alias_hits = sorted(set(scripts).intersection(forbidden_aliases))
            if alias_hits:
                inspector.error(
                    "consistency",
                    f"hooks.json references legacy alias hook names: {', '.join(alias_hits)}; use observability-hook.py and otel-hook.py",
                    "hooks.json",
                )
            has_prefixed = any(name.startswith("hook_") for name in scripts)
            has_plain = any(not name.startswith("hook_") for name in scripts)
            if has_prefixed and has_plain:
                inspector.error("consistency", "hooks.json mixes prefixed and non-prefixed hook script naming", "hooks.json")

            # Telemetry hook quality checks (dynamic paths + compatibility)
            telemetry_scripts = [
                ".github/hooks/otel-hook.py",
                ".github/hooks/hook_otel_telemetry.py",
            ]
            for rel in telemetry_scripts:
                tpath = os.path.join(output_dir, rel)
                if not os.path.exists(tpath):
                    continue
                try:
                    with open(tpath, "r", encoding="utf-8") as tf:
                        tcontent = tf.read()
                except OSError:
                    continue

                # Block delivery if telemetry hook has Python syntax errors.
                try:
                    py_compile.compile(tpath, doraise=True)
                except py_compile.PyCompileError as exc:
                    msg = str(exc)
                    inspector.error(
                        "quality",
                        f"Telemetry hook contains Python syntax errors: {msg.splitlines()[-1] if msg else 'compile failed'}",
                        rel,
                    )
                    # Skip text-based checks when file is syntactically invalid.
                    continue

                # Guard against hardcoded feature folder names in telemetry output paths.
                if re.search(r"\bEPMINAI-\d+\b", tcontent):
                    inspector.error(
                        "consistency",
                        "Telemetry hook contains hardcoded feature id; output path must be dynamic outputs/<FEATURE_ID>",
                        rel,
                    )

                # Ensure markdown telemetry writes are UTF-8 safe on Windows.
                has_utf8_header_write = bool(
                    re.search(r"telemetry_file\.write_text\(\s*header\s*,\s*encoding=['\"]utf-8['\"]\s*\)", tcontent)
                )
                has_utf8_append = bool(
                    re.search(r"with\s+open\(\s*telemetry_file\s*,\s*['\"]a['\"]\s*,\s*encoding=['\"]utf-8['\"]\s*\)", tcontent)
                )
                if not has_utf8_header_write or not has_utf8_append:
                    inspector.error(
                        "consistency",
                        "Telemetry markdown writes must use explicit UTF-8 encoding for both header and append",
                        rel,
                    )

                # Ensure feature-id parser has explicit guard against infra folder names.
                if "NON_FEATURE_DIR_NAMES" not in tcontent or "agents-repo" not in tcontent:
                    inspector.error(
                        "consistency",
                        "Telemetry hook must reject infra folder names (for example agents-repo) as feature IDs",
                        rel,
                    )
                if "_is_valid_feature_id" not in tcontent:
                    inspector.error(
                        "consistency",
                        "Telemetry hook must validate feature IDs before resolving output paths",
                        rel,
                    )

                # Guard against brittle workspace root resolution in generated telemetry hooks.
                if "parents[3]" in tcontent:
                    inspector.error(
                        "consistency",
                        "Telemetry hook uses fragile WORKSPACE_ROOT resolution (parents[3]); use Path(__file__).resolve().parents[2]",
                        rel,
                    )

                # Ensure event key compatibility parsing exists.
                has_event = "event" in tcontent
                has_hook_event = "hookEventName" in tcontent
                has_event_name = "eventName" in tcontent
                if not (has_event and has_hook_event and has_event_name):
                    inspector.warning(
                        "quality",
                        "Telemetry hook should support event/eventName/hookEventName payload variants",
                        rel,
                    )

                # Ensure tool compatibility for both runSubagent and agent variants.
                if "runSubagent" not in tcontent or "agent" not in tcontent:
                    inspector.warning(
                        "quality",
                        "Telemetry hook should support both toolName variants: runSubagent and agent",
                        rel,
                    )

                if "hookSpecificOutput" not in tcontent or "hookEventName" not in tcontent:
                    inspector.warning(
                        "quality",
                        "Telemetry hook should emit hookSpecificOutput with hookEventName for debug Hook Output visibility",
                        rel,
                    )

                # Generated repo should include pricing file so telemetry cost works standalone.
                pricing_path = os.path.join(output_dir, "observability", "model-pricing.json")
                if not os.path.exists(pricing_path):
                    inspector.error(
                        "completeness",
                        "Missing observability/model-pricing.json in generated repo; telemetry cost report will not work in standalone agents-repo",
                        "observability/model-pricing.json",
                    )

            # Detect duplicate hook files present on disk with both naming families.
            hooks_dir = os.path.join(output_dir, ".github", "hooks")
            if os.path.isdir(hooks_dir):
                disk_files = [f for f in os.listdir(hooks_dir) if f.endswith(".py")]
                # Block delivery if any generated hook script has Python syntax errors.
                for hook_file in disk_files:
                    hook_path = os.path.join(hooks_dir, hook_file)
                    try:
                        py_compile.compile(hook_path, doraise=True)
                    except py_compile.PyCompileError as exc:
                        msg = str(exc)
                        inspector.error(
                            "quality",
                            f"Hook script contains Python syntax errors: {msg.splitlines()[-1] if msg else 'compile failed'}",
                            os.path.join(".github", "hooks", hook_file),
                        )
                disk_set = set(disk_files)
                duplicate_aliases = []
                for f in disk_files:
                    if f.startswith("hook_"):
                        plain = f[len("hook_"):]
                        if plain in disk_set:
                            duplicate_aliases.append((f, plain))
                if duplicate_aliases:
                    pairs = [f"{a} <-> {b}" for a, b in duplicate_aliases]
                    inspector.error("consistency", f"Duplicate hook alias families present: {', '.join(pairs)}", ".github/hooks")
                if "hook_observability.py" in disk_set or "hook_otel_telemetry.py" in disk_set:
                    inspector.error(
                        "consistency",
                        "Legacy alias hooks detected on disk; expected canonical names observability-hook.py and otel-hook.py only",
                        ".github/hooks",
                    )

            # Runtime consistency check when telemetry JSON outputs are present.
            runtime_outputs_root = Path(output_dir) / "outputs"
            if runtime_outputs_root.is_dir():
                session_to_features: dict[str, set[str]] = {}
                for telemetry_json in runtime_outputs_root.glob("*/*_telemetry_report.json"):
                    try:
                        with open(telemetry_json, "r", encoding="utf-8") as tf:
                            report = json.load(tf)
                    except (OSError, json.JSONDecodeError):
                        continue
                    session_id = str(report.get("session_id", "")).strip()
                    feature_id = str(report.get("feature_id", telemetry_json.parent.name)).strip()
                    if session_id and feature_id:
                        session_to_features.setdefault(session_id, set()).add(feature_id)

                mixed = {sid: feats for sid, feats in session_to_features.items() if len(feats) > 1}
                if mixed:
                    examples = "; ".join(
                        f"session={sid} -> {', '.join(sorted(feats))}"
                        for sid, feats in sorted(mixed.items())
                    )
                    inspector.error(
                        "consistency",
                        f"Telemetry outputs mix feature folders for a single session: {examples}",
                        "outputs",
                    )
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

    # Frontmatter schema validation for generated agents
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
