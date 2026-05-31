#!/usr/bin/env python3
"""
repo-scanner.py — Smart Repository Scanner for SDLC Pipeline Preflight

Scans a repository directory and produces a structured analysis of:
- Repository structure with file tagging (source, test, config, docs, etc.)
- Dependency analysis (direct, dev, peer)
- Tools and technologies detected
- Patterns and conventions
- Framework-specific insights

Smart filtering: Ignores node_modules, dist, build outputs, vendor dirs, etc.
Compression: Produces compact summaries, not full file listings.

Usage:
  python3 repo-scanner.py --repo-path /path/to/repo --output-dir /path/to/output
  python3 repo-scanner.py --repo-path /path/to/repo --output-dir /path/to/output --format json
  python3 repo-scanner.py --repo-path /path/to/repo --output-dir /path/to/output --max-depth 5

Exit codes:
  0 — Success
  1 — Error (invalid path, permission denied, etc.)
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# ─── Smart Filter: Directories to ALWAYS skip ─────────────────────────────────
IGNORE_DIRS = {
    "node_modules", ".git", "dist", "build", "out", ".next", ".nuxt",
    ".cache", ".parcel-cache", ".turbo", ".vercel", ".serverless",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".tox", ".nox",
    "venv", ".venv", "env", ".env", "virtualenv",
    "vendor", "Pods", ".gradle", ".idea", ".vscode",
    "coverage", ".nyc_output", "storybook-static",
    ".terraform", ".pulumi", "cdk.out",
    ".angular", ".svelte-kit", ".output",
    "target",  # Java/Rust build output
    "bin", "obj",  # .NET build output
    "tmp", "temp", ".tmp",
}

# File extensions to ALWAYS skip (binary, generated, media)
IGNORE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".bmp",
    ".mp3", ".mp4", ".wav", ".avi", ".mov", ".webm",
    ".zip", ".tar", ".gz", ".bz2", ".rar", ".7z",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".pyc", ".pyo", ".class", ".o", ".so", ".dll", ".dylib",
    ".lock",  # lock files (captured separately)
    ".map",  # source maps
    ".min.js", ".min.css",  # minified files
}

# Files to ALWAYS skip
IGNORE_FILES = {
    ".DS_Store", "Thumbs.db", "desktop.ini",
    ".gitattributes",
}

# ─── File Tagging Categories ──────────────────────────────────────────────────
FILE_TAGS = {
    "source": {
        "extensions": {".ts", ".tsx", ".js", ".jsx", ".py", ".go", ".rs", ".java",
                       ".cs", ".rb", ".php", ".swift", ".kt", ".scala", ".vue",
                       ".svelte"},
        "patterns": [],
    },
    "test": {
        "extensions": set(),
        "patterns": [
            r"\.test\.", r"\.spec\.", r"_test\.", r"test_",
            r"__tests__/", r"tests?/", r"e2e/", r"integration/",
            r"\.stories\.", r"\.storybook",
        ],
    },
    "config": {
        "extensions": {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf"},
        "patterns": [
            r"\.config\.", r"rc$", r"config\.", r"\.env",
            r"tsconfig", r"jest\.config", r"vitest\.config",
            r"webpack\.config", r"vite\.config", r"next\.config",
            r"eslint", r"prettier", r"biome",
        ],
    },
    "docs": {
        "extensions": {".md", ".mdx", ".rst", ".txt"},
        "patterns": [r"README", r"CHANGELOG", r"CONTRIBUTING", r"LICENSE", r"docs/"],
    },
    "ci_cd": {
        "extensions": set(),
        "patterns": [
            r"\.github/workflows/", r"\.gitlab-ci", r"Jenkinsfile",
            r"azure-pipelines", r"\.circleci", r"bitbucket-pipelines",
            r"Dockerfile", r"docker-compose", r"\.dockerignore",
        ],
    },
    "schema": {
        "extensions": {".graphql", ".gql", ".proto", ".avsc"},
        "patterns": [r"openapi", r"swagger", r"schema\.", r"\.prisma"],
    },
    "style": {
        "extensions": {".css", ".scss", ".sass", ".less", ".styl"},
        "patterns": [r"styled", r"theme"],
    },
    "infra": {
        "extensions": {".tf", ".bicep", ".cfn"},
        "patterns": [
            r"serverless\.", r"sam\.template", r"cdk\.",
            r"terraform", r"pulumi",
        ],
    },
}


def tag_file(filepath: str) -> list[str]:
    """Assign tags to a file based on extension and path patterns."""
    tags = []
    lower = filepath.lower()
    ext = Path(filepath).suffix.lower()

    for tag, rules in FILE_TAGS.items():
        if ext in rules["extensions"]:
            tags.append(tag)
        for pattern in rules["patterns"]:
            if re.search(pattern, lower):
                if tag not in tags:
                    tags.append(tag)
                break

    # Test tag takes priority — a .test.ts file is "test" not "source"
    if "test" in tags and "source" in tags:
        tags.remove("source")

    if not tags:
        tags.append("other")

    return tags


def should_ignore_dir(dirname: str) -> bool:
    """Check if directory should be skipped."""
    return dirname in IGNORE_DIRS or dirname.startswith(".")


def should_ignore_file(filename: str) -> bool:
    """Check if file should be skipped."""
    if filename in IGNORE_FILES:
        return True
    ext = Path(filename).suffix.lower()
    if ext in IGNORE_EXTENSIONS:
        return True
    # Skip minified files
    if filename.endswith(".min.js") or filename.endswith(".min.css"):
        return True
    return False


def detect_lock_file(repo_path: str) -> dict[str, Any]:
    """Detect package manager from lock files."""
    lock_files = {
        "pnpm-lock.yaml": "pnpm",
        "yarn.lock": "yarn",
        "package-lock.json": "npm",
        "bun.lockb": "bun",
        "poetry.lock": "poetry",
        "Pipfile.lock": "pipenv",
        "Gemfile.lock": "bundler",
        "go.sum": "go modules",
        "Cargo.lock": "cargo",
        "composer.lock": "composer",
        "mix.lock": "mix",
    }
    found = {}
    for lock_file, manager in lock_files.items():
        path = os.path.join(repo_path, lock_file)
        if os.path.exists(path):
            found[lock_file] = manager
    return found


def parse_package_json(repo_path: str) -> dict[str, Any]:
    """Extract dependency and script info from package.json."""
    pkg_path = os.path.join(repo_path, "package.json")
    if not os.path.exists(pkg_path):
        return {}

    try:
        with open(pkg_path, "r", encoding="utf-8") as f:
            pkg = json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"error": "Failed to parse package.json"}

    result = {
        "name": pkg.get("name", "unknown"),
        "version": pkg.get("version", "unknown"),
        "private": pkg.get("private", False),
        "workspaces": pkg.get("workspaces"),
        "scripts": {k: v for k, v in pkg.get("scripts", {}).items()
                     if k in ("start", "dev", "build", "test", "lint",
                              "format", "typecheck", "e2e", "storybook",
                              "deploy", "migrate", "seed", "generate",
                              "pre-commit", "prepare")},
        "dependencies": list(pkg.get("dependencies", {}).keys()),
        "devDependencies": list(pkg.get("devDependencies", {}).keys()),
        "peerDependencies": list(pkg.get("peerDependencies", {}).keys()),
    }

    # Detect frameworks from dependencies
    all_deps = set(result["dependencies"] + result["devDependencies"])
    frameworks = []
    if "react" in all_deps:
        frameworks.append("React")
    if "next" in all_deps:
        frameworks.append("Next.js")
    if "vue" in all_deps:
        frameworks.append("Vue")
    if "nuxt" in all_deps:
        frameworks.append("Nuxt")
    if "@angular/core" in all_deps:
        frameworks.append("Angular")
    if "svelte" in all_deps:
        frameworks.append("Svelte")
    if "@nestjs/core" in all_deps:
        frameworks.append("NestJS")
    if "express" in all_deps:
        frameworks.append("Express")
    if "fastify" in all_deps:
        frameworks.append("Fastify")
    if "hono" in all_deps:
        frameworks.append("Hono")
    if "serverless" in all_deps:
        frameworks.append("Serverless Framework")
    if "aws-cdk-lib" in all_deps:
        frameworks.append("AWS CDK")
    if "@capacitor/core" in all_deps:
        frameworks.append("Capacitor")
    if "react-native" in all_deps:
        frameworks.append("React Native")
    if "graphql" in all_deps:
        frameworks.append("GraphQL")

    result["detected_frameworks"] = frameworks
    return result


def parse_tsconfig(repo_path: str) -> dict[str, Any]:
    """Extract TypeScript configuration details."""
    ts_path = os.path.join(repo_path, "tsconfig.json")
    if not os.path.exists(ts_path):
        return {}

    try:
        # Handle JSON with comments (strip // comments)
        with open(ts_path, "r", encoding="utf-8") as f:
            content = f.read()
        # Remove single-line comments
        content = re.sub(r"//.*$", "", content, flags=re.MULTILINE)
        # Remove trailing commas before } or ]
        content = re.sub(r",\s*([}\]])", r"\1", content)
        ts = json.loads(content)
    except (json.JSONDecodeError, IOError):
        return {"error": "Failed to parse tsconfig.json"}

    compiler = ts.get("compilerOptions", {})
    return {
        "strict": compiler.get("strict", False),
        "strictNullChecks": compiler.get("strictNullChecks"),
        "target": compiler.get("target"),
        "module": compiler.get("module"),
        "jsx": compiler.get("jsx"),
        "paths": bool(compiler.get("paths")),
        "baseUrl": compiler.get("baseUrl"),
        "outDir": compiler.get("outDir"),
        "rootDir": compiler.get("rootDir"),
        "extends": ts.get("extends"),
    }


def detect_linter(repo_path: str) -> dict[str, Any]:
    """Detect linter configuration."""
    linters = {}
    eslint_files = [
        ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.json", ".eslintrc.yml",
        ".eslintrc.yaml", ".eslintrc", "eslint.config.js", "eslint.config.mjs",
        "eslint.config.ts",
    ]
    for f in eslint_files:
        if os.path.exists(os.path.join(repo_path, f)):
            linters["eslint"] = f
            break

    if os.path.exists(os.path.join(repo_path, "biome.json")):
        linters["biome"] = "biome.json"
    if os.path.exists(os.path.join(repo_path, ".pylintrc")):
        linters["pylint"] = ".pylintrc"
    if os.path.exists(os.path.join(repo_path, ".flake8")):
        linters["flake8"] = ".flake8"
    if os.path.exists(os.path.join(repo_path, "setup.cfg")):
        linters["flake8_or_mypy"] = "setup.cfg"
    if os.path.exists(os.path.join(repo_path, ".golangci.yml")):
        linters["golangci-lint"] = ".golangci.yml"
    if os.path.exists(os.path.join(repo_path, "sonar-project.properties")):
        linters["sonarqube"] = "sonar-project.properties"

    return linters


def detect_formatter(repo_path: str) -> dict[str, Any]:
    """Detect formatter configuration."""
    formatters = {}
    prettier_files = [
        ".prettierrc", ".prettierrc.js", ".prettierrc.json",
        ".prettierrc.yml", ".prettierrc.yaml", ".prettierrc.cjs",
        "prettier.config.js", "prettier.config.cjs",
    ]
    for f in prettier_files:
        if os.path.exists(os.path.join(repo_path, f)):
            formatters["prettier"] = f
            break

    if os.path.exists(os.path.join(repo_path, ".editorconfig")):
        formatters["editorconfig"] = ".editorconfig"
    if os.path.exists(os.path.join(repo_path, "dprint.json")):
        formatters["dprint"] = "dprint.json"

    return formatters


def detect_test_runner(repo_path: str) -> dict[str, Any]:
    """Detect test runner configuration."""
    runners = {}
    jest_files = [
        "jest.config.js", "jest.config.ts", "jest.config.cjs",
        "jest.config.mjs", "jest.config.json",
    ]
    for f in jest_files:
        if os.path.exists(os.path.join(repo_path, f)):
            runners["jest"] = f
            break

    vitest_files = ["vitest.config.ts", "vitest.config.js", "vitest.config.mts"]
    for f in vitest_files:
        if os.path.exists(os.path.join(repo_path, f)):
            runners["vitest"] = f
            break

    if os.path.exists(os.path.join(repo_path, "playwright.config.ts")):
        runners["playwright"] = "playwright.config.ts"
    if os.path.exists(os.path.join(repo_path, "cypress.config.ts")):
        runners["cypress"] = "cypress.config.ts"
    if os.path.exists(os.path.join(repo_path, "pytest.ini")):
        runners["pytest"] = "pytest.ini"
    if os.path.exists(os.path.join(repo_path, "pyproject.toml")):
        try:
            with open(os.path.join(repo_path, "pyproject.toml"), "r") as f:
                content = f.read()
                if "[tool.pytest" in content:
                    runners["pytest"] = "pyproject.toml"
        except IOError:
            pass

    return runners


def detect_ci_cd(repo_path: str) -> dict[str, Any]:
    """Detect CI/CD configuration."""
    ci = {}
    if os.path.isdir(os.path.join(repo_path, ".github", "workflows")):
        workflows = os.listdir(os.path.join(repo_path, ".github", "workflows"))
        ci["github_actions"] = [w for w in workflows if w.endswith((".yml", ".yaml"))]
    if os.path.exists(os.path.join(repo_path, ".gitlab-ci.yml")):
        ci["gitlab_ci"] = ".gitlab-ci.yml"
    if os.path.exists(os.path.join(repo_path, "Jenkinsfile")):
        ci["jenkins"] = "Jenkinsfile"
    if os.path.exists(os.path.join(repo_path, "azure-pipelines.yml")):
        ci["azure_devops"] = "azure-pipelines.yml"
    if os.path.exists(os.path.join(repo_path, ".circleci")):
        ci["circleci"] = ".circleci/"
    if os.path.exists(os.path.join(repo_path, "bitbucket-pipelines.yml")):
        ci["bitbucket"] = "bitbucket-pipelines.yml"

    return ci


def detect_precommit(repo_path: str) -> dict[str, Any]:
    """Detect pre-commit hook configuration."""
    hooks = {}
    if os.path.isdir(os.path.join(repo_path, ".husky")):
        hooks["husky"] = ".husky/"
    if os.path.exists(os.path.join(repo_path, ".lefthook.yml")):
        hooks["lefthook"] = ".lefthook.yml"
    if os.path.exists(os.path.join(repo_path, ".pre-commit-config.yaml")):
        hooks["pre-commit"] = ".pre-commit-config.yaml"

    # Check for lint-staged in package.json
    pkg_path = os.path.join(repo_path, "package.json")
    if os.path.exists(pkg_path):
        try:
            with open(pkg_path, "r", encoding="utf-8") as f:
                pkg = json.load(f)
            if "lint-staged" in pkg:
                hooks["lint-staged"] = "package.json (inline)"
        except (json.JSONDecodeError, IOError):
            pass

    # Check for lint-staged config file
    ls_files = [".lintstagedrc", ".lintstagedrc.json", ".lintstagedrc.js",
                "lint-staged.config.js", "lint-staged.config.mjs"]
    for f in ls_files:
        if os.path.exists(os.path.join(repo_path, f)):
            hooks["lint-staged"] = f
            break

    return hooks


def scan_directory_structure(repo_path: str, max_depth: int = 6) -> dict[str, Any]:
    """Scan repo directory structure with smart filtering and file tagging."""
    structure = {
        "total_files": 0,
        "total_dirs": 0,
        "by_tag": {},
        "by_extension": {},
        "top_level_dirs": [],
        "tree": [],
        "ambiguous_items": [],
    }

    for root, dirs, files in os.walk(repo_path):
        # Smart filter: remove ignored directories in-place
        dirs[:] = [d for d in dirs if not should_ignore_dir(d)]

        rel_root = os.path.relpath(root, repo_path)
        depth = rel_root.count(os.sep) if rel_root != "." else 0

        if depth > max_depth:
            dirs.clear()
            continue

        if depth == 0:
            structure["top_level_dirs"] = sorted(dirs)

        structure["total_dirs"] += len(dirs)

        for filename in files:
            if should_ignore_file(filename):
                continue

            rel_path = os.path.join(rel_root, filename) if rel_root != "." else filename
            ext = Path(filename).suffix.lower()

            structure["total_files"] += 1

            # Count by extension
            if ext:
                structure["by_extension"][ext] = structure["by_extension"].get(ext, 0) + 1

            # Tag the file
            tags = tag_file(rel_path)
            for tag in tags:
                if tag not in structure["by_tag"]:
                    structure["by_tag"][tag] = {"count": 0, "sample_files": []}
                structure["by_tag"][tag]["count"] += 1
                if len(structure["by_tag"][tag]["sample_files"]) < 5:
                    structure["by_tag"][tag]["sample_files"].append(rel_path)

            # Detect ambiguous items (files that could be source or config)
            if len(tags) > 1 and "other" not in tags:
                if len(structure["ambiguous_items"]) < 20:
                    structure["ambiguous_items"].append({
                        "file": rel_path,
                        "tags": tags,
                        "reason": f"File matches multiple categories: {', '.join(tags)}"
                    })

        # Build compact tree (only top 3 levels)
        if depth <= 2:
            prefix = "  " * depth
            dir_name = os.path.basename(root) if depth > 0 else "."
            file_count = len([f for f in files if not should_ignore_file(f)])
            if file_count > 0 or dirs:
                structure["tree"].append(
                    f"{prefix}{dir_name}/ ({file_count} files, {len(dirs)} dirs)"
                )

    return structure


def detect_patterns(repo_path: str, pkg_info: dict) -> list[dict[str, str]]:
    """Detect architectural and coding patterns from the codebase."""
    patterns = []

    # Check for monorepo patterns
    if pkg_info.get("workspaces"):
        patterns.append({
            "pattern": "Monorepo (Workspaces)",
            "evidence": f"workspaces in package.json: {pkg_info['workspaces']}",
            "confidence": "high",
        })

    monorepo_files = ["lerna.json", "nx.json", "turbo.json", "pnpm-workspace.yaml"]
    for f in monorepo_files:
        if os.path.exists(os.path.join(repo_path, f)):
            patterns.append({
                "pattern": f"Monorepo ({f.split('.')[0].title()})",
                "evidence": f"{f} found",
                "confidence": "high",
            })

    # Check for common architecture patterns
    src_path = os.path.join(repo_path, "src")
    if os.path.isdir(src_path):
        src_dirs = set(os.listdir(src_path)) if os.path.isdir(src_path) else set()
        if {"domain", "application", "infrastructure", "presentation"} & src_dirs:
            patterns.append({
                "pattern": "Clean Architecture / Hexagonal",
                "evidence": "Domain-driven directory structure in src/",
                "confidence": "medium",
            })
        if {"controllers", "services", "modules", "entities"} & src_dirs:
            patterns.append({
                "pattern": "NestJS Module Pattern",
                "evidence": "NestJS-style directory structure",
                "confidence": "high",
            })
        if {"components", "pages", "hooks", "utils"} & src_dirs:
            patterns.append({
                "pattern": "React Feature-Based Structure",
                "evidence": "React-style directory structure",
                "confidence": "medium",
            })
        if {"routes", "middleware", "models"} & src_dirs:
            patterns.append({
                "pattern": "MVC / Express Pattern",
                "evidence": "MVC-style directory structure",
                "confidence": "medium",
            })

    # Check for state management
    all_deps = set(pkg_info.get("dependencies", []) + pkg_info.get("devDependencies", []))
    if "redux" in all_deps or "@reduxjs/toolkit" in all_deps:
        patterns.append({"pattern": "Redux State Management", "evidence": "redux in deps", "confidence": "high"})
    if "zustand" in all_deps:
        patterns.append({"pattern": "Zustand State Management", "evidence": "zustand in deps", "confidence": "high"})
    if "mobx" in all_deps:
        patterns.append({"pattern": "MobX State Management", "evidence": "mobx in deps", "confidence": "high"})
    if "@tanstack/react-query" in all_deps or "react-query" in all_deps:
        patterns.append({"pattern": "React Query / TanStack Query", "evidence": "react-query in deps", "confidence": "high"})
    if "graphql" in all_deps:
        patterns.append({"pattern": "GraphQL API", "evidence": "graphql in deps", "confidence": "high"})
    if "@apollo/client" in all_deps:
        patterns.append({"pattern": "Apollo Client", "evidence": "@apollo/client in deps", "confidence": "high"})

    return patterns


def scan_repo(repo_path: str, max_depth: int = 6) -> dict[str, Any]:
    """Full repository scan producing structured analysis."""
    repo_name = os.path.basename(os.path.abspath(repo_path))

    result = {
        "repo_name": repo_name,
        "repo_path": os.path.abspath(repo_path),
        "scan_status": "success",
        "structure": {},
        "package_info": {},
        "typescript": {},
        "linters": {},
        "formatters": {},
        "test_runners": {},
        "ci_cd": {},
        "precommit_hooks": {},
        "lock_files": {},
        "patterns": [],
        "ambiguous_items": [],
    }

    if not os.path.isdir(repo_path):
        result["scan_status"] = "error"
        result["error"] = f"Path does not exist or is not a directory: {repo_path}"
        return result

    try:
        result["lock_files"] = detect_lock_file(repo_path)
        result["package_info"] = parse_package_json(repo_path)
        result["typescript"] = parse_tsconfig(repo_path)
        result["linters"] = detect_linter(repo_path)
        result["formatters"] = detect_formatter(repo_path)
        result["test_runners"] = detect_test_runner(repo_path)
        result["ci_cd"] = detect_ci_cd(repo_path)
        result["precommit_hooks"] = detect_precommit(repo_path)
        result["structure"] = scan_directory_structure(repo_path, max_depth)
        result["patterns"] = detect_patterns(repo_path, result["package_info"])
        result["ambiguous_items"] = result["structure"].pop("ambiguous_items", [])
    except Exception as e:
        result["scan_status"] = "partial"
        result["error"] = str(e)

    return result


def format_markdown(scan_result: dict) -> str:
    """Format scan results as Markdown."""
    r = scan_result
    lines = []
    lines.append(f"# Repository Scan: {r['repo_name']}\n")
    lines.append(f"**Path:** `{r['repo_path']}`  ")
    lines.append(f"**Status:** {r['scan_status']}\n")

    if r.get("error"):
        lines.append(f"> ⚠️ {r['error']}\n")

    # Structure summary
    s = r.get("structure", {})
    lines.append("## Structure Summary\n")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total files (scanned) | {s.get('total_files', 0)} |")
    lines.append(f"| Total directories | {s.get('total_dirs', 0)} |")
    lines.append(f"| Top-level dirs | {', '.join(s.get('top_level_dirs', [])[:15])} |")
    lines.append("")

    # File tags
    if s.get("by_tag"):
        lines.append("### File Tags\n")
        lines.append("| Tag | Count | Sample Files |")
        lines.append("|-----|-------|-------------|")
        for tag, info in sorted(s["by_tag"].items(), key=lambda x: -x[1]["count"]):
            samples = ", ".join(f"`{f}`" for f in info["sample_files"][:3])
            lines.append(f"| {tag} | {info['count']} | {samples} |")
        lines.append("")

    # Extensions
    if s.get("by_extension"):
        lines.append("### File Extensions\n")
        lines.append("| Extension | Count |")
        lines.append("|-----------|-------|")
        sorted_exts = sorted(s["by_extension"].items(), key=lambda x: -x[1])[:20]
        for ext, count in sorted_exts:
            lines.append(f"| `{ext}` | {count} |")
        lines.append("")

    # Package info
    pkg = r.get("package_info", {})
    if pkg and not pkg.get("error"):
        lines.append("## Dependencies\n")
        lines.append(f"**Name:** {pkg.get('name', 'N/A')}  ")
        lines.append(f"**Version:** {pkg.get('version', 'N/A')}  ")
        if pkg.get("detected_frameworks"):
            lines.append(f"**Frameworks:** {', '.join(pkg['detected_frameworks'])}  ")
        lines.append("")

        if pkg.get("scripts"):
            lines.append("### Scripts\n")
            lines.append("| Script | Command |")
            lines.append("|--------|---------|")
            for name, cmd in pkg["scripts"].items():
                lines.append(f"| `{name}` | `{cmd}` |")
            lines.append("")

        if pkg.get("dependencies"):
            lines.append(f"### Production Dependencies ({len(pkg['dependencies'])})\n")
            lines.append(", ".join(f"`{d}`" for d in sorted(pkg["dependencies"])[:30]))
            if len(pkg["dependencies"]) > 30:
                lines.append(f"  ... and {len(pkg['dependencies']) - 30} more")
            lines.append("")

        if pkg.get("devDependencies"):
            lines.append(f"### Dev Dependencies ({len(pkg['devDependencies'])})\n")
            lines.append(", ".join(f"`{d}`" for d in sorted(pkg["devDependencies"])[:30]))
            if len(pkg["devDependencies"]) > 30:
                lines.append(f"  ... and {len(pkg['devDependencies']) - 30} more")
            lines.append("")

    # TypeScript
    ts = r.get("typescript", {})
    if ts and not ts.get("error"):
        lines.append("## TypeScript Configuration\n")
        lines.append("| Setting | Value |")
        lines.append("|---------|-------|")
        for k, v in ts.items():
            if v is not None:
                lines.append(f"| {k} | {v} |")
        lines.append("")

    # Tools
    lines.append("## Tools Detected\n")
    lines.append("| Category | Tool | Config File |")
    lines.append("|----------|------|-------------|")
    for tool, config in r.get("linters", {}).items():
        lines.append(f"| Linter | {tool} | `{config}` |")
    for tool, config in r.get("formatters", {}).items():
        lines.append(f"| Formatter | {tool} | `{config}` |")
    for tool, config in r.get("test_runners", {}).items():
        lines.append(f"| Test Runner | {tool} | `{config}` |")
    for lock, manager in r.get("lock_files", {}).items():
        lines.append(f"| Package Manager | {manager} | `{lock}` |")
    for hook_tool, config in r.get("precommit_hooks", {}).items():
        lines.append(f"| Pre-commit | {hook_tool} | `{config}` |")
    lines.append("")

    # CI/CD
    ci = r.get("ci_cd", {})
    if ci:
        lines.append("## CI/CD\n")
        for provider, config in ci.items():
            if isinstance(config, list):
                lines.append(f"- **{provider}:** {', '.join(config)}")
            else:
                lines.append(f"- **{provider}:** {config}")
        lines.append("")

    # Patterns
    patterns = r.get("patterns", [])
    if patterns:
        lines.append("## Detected Patterns\n")
        lines.append("| Pattern | Evidence | Confidence |")
        lines.append("|---------|----------|------------|")
        for p in patterns:
            lines.append(f"| {p['pattern']} | {p['evidence']} | {p['confidence']} |")
        lines.append("")

    # Ambiguous items
    ambiguous = r.get("ambiguous_items", [])
    if ambiguous:
        lines.append("## ⚠️ Ambiguous Items (Need Clarification)\n")
        lines.append("| File | Tags | Reason |")
        lines.append("|------|------|--------|")
        for item in ambiguous:
            lines.append(f"| `{item['file']}` | {', '.join(item['tags'])} | {item['reason']} |")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Smart Repository Scanner for SDLC Pipeline")
    parser.add_argument("--repo-path", required=True, help="Path to the repository to scan")
    parser.add_argument("--output-dir", help="Directory to write output files")
    parser.add_argument("--format", choices=["json", "markdown", "both"], default="both",
                        help="Output format (default: both)")
    parser.add_argument("--max-depth", type=int, default=6,
                        help="Max directory depth to scan (default: 6)")
    args = parser.parse_args()

    result = scan_repo(args.repo_path, args.max_depth)

    if args.output_dir:
        os.makedirs(args.output_dir, exist_ok=True)
        repo_name = result["repo_name"]

        if args.format in ("json", "both"):
            json_path = os.path.join(args.output_dir, f"{repo_name}_scan.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2)
            print(f"JSON: {json_path}", file=sys.stderr)

        if args.format in ("markdown", "both"):
            md_path = os.path.join(args.output_dir, f"{repo_name}_scan.md")
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(format_markdown(result))
            print(f"Markdown: {md_path}", file=sys.stderr)
    else:
        if args.format == "json":
            print(json.dumps(result, indent=2))
        else:
            print(format_markdown(result))

    sys.exit(0 if result["scan_status"] == "success" else 1)


if __name__ == "__main__":
    main()
