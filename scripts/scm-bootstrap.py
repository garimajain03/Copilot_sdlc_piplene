#!/usr/bin/env python3
"""
scm-bootstrap.py — Clone and prepare customer repositories for SDLC Pipeline

Takes a list of repositories, clones them using the appropriate SCM connector,
and prepares them for scanning by the repo-scanner.

Usage:
  python3 scm-bootstrap.py --repos '["repo1","repo2"]' --scm github --org myorg --target-dir ./repos
  python3 scm-bootstrap.py --repos-file repos.json --scm github --org myorg --target-dir ./repos
  python3 scm-bootstrap.py --repos '["repo1"]' --scm gitlab --org mygroup --target-dir ./repos

Exit codes:
  0 — All repos cloned successfully
  1 — Some repos failed (partial success)
  2 — Fatal error (no repos cloned)
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


# SCM clone URL patterns
SCM_URL_PATTERNS = {
    "github": "https://github.com/{org}/{repo}.git",
    "github_enterprise": "{base_url}/{org}/{repo}.git",
    "gitlab": "https://gitlab.com/{org}/{repo}.git",
    "gitlab_self_hosted": "{base_url}/{org}/{repo}.git",
    "bitbucket": "https://bitbucket.org/{org}/{repo}.git",
    "azure_devops": "https://dev.azure.com/{org}/{project}/_git/{repo}",
}

# Shallow clone depth — enough for analysis without full history
SHALLOW_DEPTH = 1


def clone_repo(repo_name: str, scm: str, org: str, target_dir: str,
               base_url: str = "", project: str = "", branch: str = "main") -> dict:
    """Clone a single repository. Returns status dict."""
    result = {
        "repo": repo_name,
        "status": "pending",
        "path": "",
        "error": "",
    }

    target_path = os.path.join(target_dir, repo_name)

    # Skip if already cloned
    if os.path.isdir(os.path.join(target_path, ".git")):
        result["status"] = "exists"
        result["path"] = target_path
        return result

    # Build clone URL
    url_template = SCM_URL_PATTERNS.get(scm, "")
    if not url_template:
        result["status"] = "error"
        result["error"] = f"Unsupported SCM: {scm}"
        return result

    clone_url = url_template.format(
        org=org, repo=repo_name, base_url=base_url.rstrip("/"), project=project
    )

    # Clone with shallow depth for speed
    cmd = [
        "git", "clone",
        "--depth", str(SHALLOW_DEPTH),
        "--branch", branch,
        "--single-branch",
        clone_url,
        target_path,
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )

        if proc.returncode == 0:
            result["status"] = "cloned"
            result["path"] = target_path
        else:
            # Try without branch (maybe default branch is different)
            cmd_no_branch = [
                "git", "clone",
                "--depth", str(SHALLOW_DEPTH),
                clone_url,
                target_path,
            ]
            proc2 = subprocess.run(
                cmd_no_branch,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if proc2.returncode == 0:
                result["status"] = "cloned"
                result["path"] = target_path
            else:
                result["status"] = "error"
                result["error"] = proc.stderr.strip() or proc2.stderr.strip()

    except subprocess.TimeoutExpired:
        result["status"] = "error"
        result["error"] = "Clone timed out after 120 seconds"
    except FileNotFoundError:
        result["status"] = "error"
        result["error"] = "git not found — install git first"
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)

    return result


def validate_repo_list(repos: list) -> tuple[list, list]:
    """Validate repo names, return (valid, invalid) lists."""
    valid = []
    invalid = []
    for repo in repos:
        if not isinstance(repo, str):
            invalid.append({"repo": str(repo), "reason": "Not a string"})
            continue
        # Basic repo name validation — alphanumeric, hyphens, underscores, dots
        if not all(c.isalnum() or c in "-_." for c in repo):
            invalid.append({"repo": repo, "reason": "Invalid characters in repo name"})
            continue
        if len(repo) > 100:
            invalid.append({"repo": repo, "reason": "Name too long (>100 chars)"})
            continue
        valid.append(repo)
    return valid, invalid


def main():
    parser = argparse.ArgumentParser(description="Clone repositories for SDLC Pipeline")
    parser.add_argument("--repos", help="JSON array of repo names")
    parser.add_argument("--repos-file", help="Path to JSON file with repo list")
    parser.add_argument("--scm", required=True, choices=["github", "github_enterprise",
                        "gitlab", "gitlab_self_hosted", "bitbucket", "azure_devops"],
                        help="SCM provider")
    parser.add_argument("--org", required=True, help="Organization/group/workspace name")
    parser.add_argument("--target-dir", required=True, help="Directory to clone repos into")
    parser.add_argument("--base-url", default="", help="Base URL for self-hosted SCMs")
    parser.add_argument("--project", default="", help="Project name (Azure DevOps)")
    parser.add_argument("--branch", default="main", help="Default branch to clone")
    args = parser.parse_args()

    # Load repo list
    if args.repos:
        try:
            repos = json.loads(args.repos)
        except json.JSONDecodeError as e:
            print(json.dumps({"error": f"Invalid JSON in --repos: {e}"}))
            sys.exit(2)
    elif args.repos_file:
        try:
            with open(args.repos_file, "r") as f:
                repos = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(json.dumps({"error": f"Failed to read repos file: {e}"}))
            sys.exit(2)
    else:
        print(json.dumps({"error": "Provide --repos or --repos-file"}))
        sys.exit(2)

    if not isinstance(repos, list):
        print(json.dumps({"error": "Repos must be a JSON array"}))
        sys.exit(2)

    # Validate
    valid_repos, invalid_repos = validate_repo_list(repos)

    # Create target directory
    os.makedirs(args.target_dir, exist_ok=True)

    # Clone each repo
    results = []
    for repo in valid_repos:
        print(f"Cloning {repo}...", file=sys.stderr)
        result = clone_repo(
            repo_name=repo,
            scm=args.scm,
            org=args.org,
            target_dir=args.target_dir,
            base_url=args.base_url,
            project=args.project,
            branch=args.branch,
        )
        results.append(result)
        status_icon = "✓" if result["status"] in ("cloned", "exists") else "✗"
        print(f"  {status_icon} {repo}: {result['status']}", file=sys.stderr)

    # Summary
    cloned = [r for r in results if r["status"] in ("cloned", "exists")]
    failed = [r for r in results if r["status"] == "error"]

    output = {
        "total": len(repos),
        "valid": len(valid_repos),
        "invalid": invalid_repos,
        "cloned": len(cloned),
        "failed": len(failed),
        "results": results,
    }

    print(json.dumps(output, indent=2))

    if len(failed) == len(valid_repos):
        sys.exit(2)
    elif failed:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
