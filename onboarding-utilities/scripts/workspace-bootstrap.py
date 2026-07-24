#!/usr/bin/env python3
"""
workspace-bootstrap.py — Create workspace layout and materialize application repositories.

Supports two mutually exclusive layouts:
- default: outputs/agents-repo with app repos as git submodules in agents-repo/repos
- custom: outputs/agents-repo and outputs/app-repos with app repos cloned normally

Usage examples:
  python3 onboarding-utilities/scripts/workspace-bootstrap.py \
    --workspace-mode default \
        --output-root outputs \
    --app-repos '["https://github.com/acme/api.git", "https://github.com/acme/web.git"]'

  python3 onboarding-utilities/scripts/workspace-bootstrap.py \
    --workspace-mode custom \
        --output-root outputs \
    --app-repos '["api", "web"]' --scm github --org acme
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

SCM_URL_PATTERNS = {
    "github": "https://github.com/{org}/{repo}.git",
    "github_enterprise": "{base_url}/{org}/{repo}.git",
    "gitlab": "https://gitlab.com/{org}/{repo}.git",
    "gitlab_self_hosted": "{base_url}/{org}/{repo}.git",
    "bitbucket": "https://bitbucket.org/{org}/{repo}.git",
    "azure_devops": "https://dev.azure.com/{org}/{project}/_git/{repo}",
}


def run_git(args: List[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
    )


def ensure_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    git_dir = path / ".git"
    if not git_dir.exists():
        proc = run_git(["init"], cwd=path)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or "Failed to initialize git repository")


def normalize_repo_name(entry: str) -> str:
    candidate = entry.rstrip("/")
    if candidate.endswith(".git"):
        candidate = candidate[:-4]
    candidate = candidate.split("/")[-1]
    candidate = re.sub(r"[^A-Za-z0-9._-]", "-", candidate)
    return candidate or "repo"


def build_clone_url(repo: str, scm: str, org: str, base_url: str, project: str) -> str:
    template = SCM_URL_PATTERNS.get(scm)
    if not template:
        raise ValueError(f"Unsupported SCM provider: {scm}")
    return template.format(
        org=org,
        repo=repo,
        base_url=base_url.rstrip("/"),
        project=project,
    )


def parse_repo_entries(raw_entries: List[str], scm: str, org: str, base_url: str, project: str) -> List[Dict[str, str]]:
    repos: List[Dict[str, str]] = []
    for raw in raw_entries:
        value = raw.strip()
        if not value:
            continue

        is_url = value.startswith("http://") or value.startswith("https://") or value.startswith("git@")
        if is_url:
            repos.append({"name": normalize_repo_name(value), "url": value})
            continue

        if not scm or not org:
            raise ValueError("Repo names require --scm and --org so clone URLs can be resolved")

        repos.append(
            {
                "name": normalize_repo_name(value),
                "url": build_clone_url(value, scm=scm, org=org, base_url=base_url, project=project),
            }
        )

    if not repos:
        raise ValueError("No repositories provided")

    # Keep deterministic order but remove duplicates by name.
    unique: Dict[str, Dict[str, str]] = {}
    for repo in repos:
        unique[repo["name"]] = repo
    return list(unique.values())


def clone_agents_repo_if_requested(agents_repo_dir: Path, agents_repo_url: str, branch: str) -> str:
    if not agents_repo_url:
        ensure_git_repo(agents_repo_dir)
        return "initialized"

    if (agents_repo_dir / ".git").exists():
        return "exists"

    agents_repo_dir.parent.mkdir(parents=True, exist_ok=True)
    proc = run_git(["clone", "--branch", branch, agents_repo_url, str(agents_repo_dir)])
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "Failed to clone agents repository")
    return "cloned"


def ensure_observability_pricing(agents_repo_dir: Path) -> bool:
    """Ensure generated agents-repo contains model pricing for standalone telemetry reports."""
    repo_root = Path(__file__).resolve().parents[2]
    source_candidates = [
        repo_root / "onboarding-utilities" / "observability" / "model-pricing.json",
        repo_root / "observability" / "model-pricing.json",
    ]

    source_file = None
    for candidate in source_candidates:
        if candidate.exists():
            source_file = candidate
            break

    if source_file is None:
        return False

    target_dir = agents_repo_dir / "observability"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / "model-pricing.json"
    if not target_file.exists():
        shutil.copy2(source_file, target_file)
        return True
    return False


def add_submodules(agents_repo_dir: Path, repos_dir: Path, repos: List[Dict[str, str]]) -> List[Dict[str, str]]:
    results: List[Dict[str, str]] = []
    repos_dir.mkdir(parents=True, exist_ok=True)

    for repo in repos:
        submodule_path = Path("repos") / repo["name"]
        full_path = agents_repo_dir / submodule_path
        if (full_path / ".git").exists() or full_path.exists():
            results.append({"name": repo["name"], "url": repo["url"], "status": "exists", "path": str(full_path)})
            continue

        proc = run_git(["submodule", "add", repo["url"], str(submodule_path).replace("\\", "/")], cwd=agents_repo_dir)
        if proc.returncode != 0:
            results.append({"name": repo["name"], "url": repo["url"], "status": "error", "error": proc.stderr.strip()})
            continue

        results.append({"name": repo["name"], "url": repo["url"], "status": "added", "path": str(full_path)})

    # Initialize top-level submodules first; nested/foreign submodules can fail
    # for unrelated access reasons and should not block workspace bootstrap.
    init_proc = run_git(["submodule", "update", "--init", "--jobs", "4"], cwd=agents_repo_dir)
    if init_proc.returncode != 0:
        results.append({"name": "_submodule_init", "status": "error", "error": init_proc.stderr.strip()})
        return results

    recursive_proc = run_git(["submodule", "update", "--init", "--recursive", "--jobs", "4"], cwd=agents_repo_dir)
    if recursive_proc.returncode != 0:
        results.append(
            {
                "name": "_submodule_recursive",
                "status": "warning",
                "error": recursive_proc.stderr.strip(),
                "message": "Nested submodule initialization failed; top-level submodules are initialized.",
            }
        )

    return results


def clone_normal_repos(app_repos_dir: Path, repos: List[Dict[str, str]], branch: str) -> List[Dict[str, str]]:
    app_repos_dir.mkdir(parents=True, exist_ok=True)
    results: List[Dict[str, str]] = []

    for repo in repos:
        target = app_repos_dir / repo["name"]
        if (target / ".git").exists() or target.exists():
            results.append({"name": repo["name"], "url": repo["url"], "status": "exists", "path": str(target)})
            continue

        proc = run_git(
            ["clone", "--depth", "1", "--branch", branch, "--single-branch", repo["url"], str(target)]
        )
        if proc.returncode != 0:
            retry_proc = run_git(["clone", "--depth", "1", repo["url"], str(target)])
            if retry_proc.returncode != 0:
                results.append({"name": repo["name"], "url": repo["url"], "status": "error", "error": retry_proc.stderr.strip()})
                continue

        results.append({"name": repo["name"], "url": repo["url"], "status": "cloned", "path": str(target)})

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap SDLC workspace layouts")
    parser.add_argument("--workspace-mode", required=True, choices=["default", "custom"])
    parser.add_argument("--output-root", default="outputs")
    parser.add_argument("--agents-repo-url", default="")
    parser.add_argument("--agents-repo-branch", default="main")
    parser.add_argument("--app-repos", required=True, help="JSON list of repo URLs or repo names")
    parser.add_argument("--scm", default="", choices=["", "github", "github_enterprise", "gitlab", "gitlab_self_hosted", "bitbucket", "azure_devops"])
    parser.add_argument("--org", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--project", default="")
    parser.add_argument("--default-branch", default="main")
    args = parser.parse_args()

    try:
        try:
            raw_repos = json.loads(args.app_repos)
            if not isinstance(raw_repos, list):
                raise ValueError("--app-repos must be a JSON array")
        except json.JSONDecodeError:
            # PowerShell quoting can mangle JSON literals; support a simple fallback.
            raw_repos = [part.strip() for part in re.split(r"[,\n]", args.app_repos) if part.strip()]

        repos = parse_repo_entries(
            [str(x) for x in raw_repos],
            scm=args.scm,
            org=args.org,
            base_url=args.base_url,
            project=args.project,
        )

        output_root = Path(args.output_root)
        agents_repo_dir = output_root / "agents-repo"
        app_repos_dir = output_root / "app-repos"
        default_submodule_dir = agents_repo_dir / "repos"

        output_root.mkdir(parents=True, exist_ok=True)
        agents_repo_status = clone_agents_repo_if_requested(
            agents_repo_dir=agents_repo_dir,
            agents_repo_url=args.agents_repo_url,
            branch=args.agents_repo_branch,
        )
        pricing_copied = ensure_observability_pricing(agents_repo_dir)

        if args.workspace_mode == "default":
            clone_results = add_submodules(
                agents_repo_dir=agents_repo_dir,
                repos_dir=default_submodule_dir,
                repos=repos,
            )
            layout = {
                "workspace_mode": "default",
                "output_root": str(output_root),
                "agents_repo": str(agents_repo_dir),
                "app_repos": str(default_submodule_dir),
                "generated_github": str(agents_repo_dir / ".github"),
            }
        else:
            clone_results = clone_normal_repos(
                app_repos_dir=app_repos_dir,
                repos=repos,
                branch=args.default_branch,
            )
            layout = {
                "workspace_mode": "custom",
                "output_root": str(output_root),
                "agents_repo": str(agents_repo_dir),
                "app_repos": str(app_repos_dir),
                "generated_github": str(agents_repo_dir / ".github"),
            }

        payload = {
            "status": "ok",
            "agents_repo_status": agents_repo_status,
            "observability_pricing": "copied" if pricing_copied else "existing_or_unavailable",
            "layout": layout,
            "repositories": clone_results,
        }

        print(json.dumps(payload, indent=2))

        failed = [r for r in clone_results if r.get("status") == "error"]
        return 1 if failed else 0

    except Exception as exc:
        print(json.dumps({"status": "error", "message": str(exc)}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
