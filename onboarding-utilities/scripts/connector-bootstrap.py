#!/usr/bin/env python3
"""
connector-bootstrap.py - Preflight connector artifact generation and secure token collection.

Commands:
  generate:
    Parse intake-sources markdown and generate connector artifacts for preflight.

  collect-token:
    Securely collect a connector API token, encrypt it, and store as encrypted
    env-style variables in outputs/agents-repo/.env.encrypted.

    verify-auth:
        Validate that API encrypted tokens exist and MCP auth prerequisites are
        satisfied before pipeline generation.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


KEYRING_SERVICE_DEFAULT = "sdlc-pipeline-connectors"


class ConnectorSpec:
    __slots__ = ("platform", "category", "mode", "auth", "endpoint")

    def __init__(self, platform: str, category: str, mode: str, auth: str, endpoint: str):
        self.platform = platform
        self.category = category
        self.mode = mode
        self.auth = auth
        self.endpoint = endpoint

    def to_dict(self) -> Dict[str, str]:
        return {
            "platform": self.platform,
            "category": self.category,
            "mode": self.mode,
            "auth": self.auth,
            "endpoint": self.endpoint,
        }


MCP_CATALOG: Dict[str, Dict[str, object]] = {
    "jira": {
        "server_name": "atlassian-jira",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-atlassian"],
        "env": {"ATLASSIAN_URL": "{endpoint}", "ATLASSIAN_TOKEN": "${ATLASSIAN_TOKEN}"},
        "auth_modes": ["token", "oauth"],
        "default_auth": "token",
        "auth": "token",
    },
    "confluence": {
        "server_name": "atlassian-confluence",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-atlassian"],
        "env": {"ATLASSIAN_URL": "{endpoint}", "ATLASSIAN_TOKEN": "${ATLASSIAN_TOKEN}"},
        "auth_modes": ["token", "oauth"],
        "default_auth": "token",
        "auth": "token",
    },
    "github": {
        "server_name": "github",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env": {"GITHUB_TOKEN": "${GITHUB_TOKEN}"},
        "auth_modes": ["token", "oauth"],
        "default_auth": "oauth",
        "auth": "oauth",
    },
    "gitlab": {
        "server_name": "gitlab",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-gitlab"],
        "env": {"GITLAB_TOKEN": "${GITLAB_TOKEN}"},
        "auth_modes": ["token", "oauth"],
        "default_auth": "token",
        "auth": "token",
    },
    "azure devops": {
        "server_name": "azure-devops",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-azure-devops"],
        "env": {
            "AZURE_DEVOPS_URL": "{endpoint}",
            "AZURE_DEVOPS_TOKEN": "${AZURE_DEVOPS_TOKEN}",
        },
        "auth_modes": ["token", "oauth"],
        "default_auth": "token",
        "auth": "token",
    },
}


API_CATALOG: Dict[str, Dict[str, str]] = {
    "jira": {"token_env": "JIRA_TOKEN", "default_endpoint": "https://your-org.atlassian.net", "skill": "jira-connector"},
    "other": {"token_env": "OTHER_TOKEN", "default_endpoint": "", "skill": "other-connector"},
    "confluence": {"token_env": "CONFLUENCE_TOKEN", "default_endpoint": "https://your-org.atlassian.net/wiki", "skill": "confluence-connector"},
    "github": {"token_env": "GITHUB_TOKEN", "default_endpoint": "https://api.github.com", "skill": "github-connector"},
    "gitlab": {"token_env": "GITLAB_TOKEN", "default_endpoint": "https://gitlab.com/api/v4", "skill": "gitlab-connector"},
    "azure devops": {"token_env": "AZURE_DEVOPS_TOKEN", "default_endpoint": "https://dev.azure.com", "skill": "azure-devops-connector"},
    "linear": {"token_env": "LINEAR_TOKEN", "default_endpoint": "https://api.linear.app/graphql", "skill": "linear-connector"},
    "bitbucket": {"token_env": "BITBUCKET_TOKEN", "default_endpoint": "https://api.bitbucket.org/2.0", "skill": "bitbucket-connector"},
}


PLATFORM_ALIASES: Dict[str, str] = {
    "ado": "azure devops",
    "azure-devops": "azure devops",
    "azure_devops": "azure devops",
    "azure-repos": "azure devops",
    "azure repos": "azure devops",
    "atlassian jira": "jira",
    "jira software": "jira",
    "jira cloud": "jira",
    "github issues": "github",
}


def parse_arg() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate preflight connector artifacts and collect tokens securely")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="Generate connector artifacts from intake-sources.md")
    gen.add_argument("--intake", required=True, help="Path to intake-sources.md")
    gen.add_argument("--output-root", default="outputs/agents-repo", help="Generated agents repo root")
    gen.add_argument(
        "--mcp-auth-overrides",
        default="",
        help="Optional JSON file with MCP auth selections from preflight (example: {\"pm\":\"oauth\",\"scm\":\"token\",\"confluence\":\"oauth\"})",
    )

    collect = sub.add_parser("collect-token", help="Collect and encrypt a connector token")
    collect.add_argument("--connector", required=True, help="Connector platform (jira, github, gitlab, confluence, etc.)")
    collect.add_argument("--output-root", default="outputs/agents-repo", help="Generated agents repo root")
    collect.add_argument("--token-env", default="", help="Token environment variable base name, defaults from connector catalog")

    verify = sub.add_parser("verify-auth", help="Verify connector authentication readiness")
    verify.add_argument("--output-root", default="outputs/agents-repo", help="Generated agents repo root")
    verify.add_argument("--fail-on-missing", action="store_true", help="Return non-zero exit code when auth is incomplete")
    verify.add_argument(
        "--require-dotenv-tokens",
        action="store_true",
        help="Require API connector token variables to be present in .env before reporting auth as ready",
    )
    verify.add_argument(
        "--allow-dotenv-fallback",
        action="store_true",
        help="Treat matching token values in .env as valid fallback for auth readiness",
    )

    mark_oauth = sub.add_parser("mark-oauth-complete", help="Mark MCP OAuth connector authentication as complete")
    mark_oauth.add_argument("--connector", required=True, help="Connector platform (for example: github)")
    mark_oauth.add_argument("--output-root", default="outputs/agents-repo", help="Generated agents repo root")

    return parser.parse_args()


def _extract_line_value(text: str, label: str) -> str:
    pattern = re.compile(
        rf"^\s*[-*]?\s*(?:\*\*)?{re.escape(label)}(?:\*\*)?\s*:\s*(.+?)\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    match = pattern.search(text)
    if not match:
        return ""

    value = match.group(1).strip()
    if value.startswith("**"):
        value = value[2:].lstrip()
    if value.endswith("**"):
        value = value[:-2].rstrip()
    return value


def parse_intake_markdown(path: Path) -> Dict[str, str]:
    content = path.read_text(encoding="utf-8-sig")
    pm_name = _extract_line_value(content, "PM/Requirements Name")
    if not pm_name:
        pm_name = _extract_line_value(content, "PM/Requirement Name")
    values = {
        "pm_system": _extract_line_value(content, "PM/Requirements System"),
        "pm_name": pm_name,
        "pm_url": _extract_line_value(content, "PM Tool URL"),
        "pm_mode": _extract_line_value(content, "PM Integration Mode"),
        "pm_mcp_auth_mode": _extract_line_value(content, "PM MCP Auth Mode"),
        "scm_system": _extract_line_value(content, "SCM System"),
        "scm_mode": _extract_line_value(content, "SCM Integration Mode"),
        "scm_mcp_auth_mode": _extract_line_value(content, "SCM MCP Auth Mode"),
        "confluence_url": _extract_line_value(content, "Confluence URL"),
        "confluence_mode": _extract_line_value(content, "Confluence Integration Mode"),
        "confluence_mcp_auth_mode": _extract_line_value(content, "Confluence MCP Auth Mode"),
    }
    return values


def _normalize_mode(value: str) -> str:
    cleaned = value.strip().lower()
    if cleaned in {"mcp", "model context protocol"}:
        return "mcp"
    if cleaned in {"api", "api-based connector", "api based connector", "api-based"}:
        return "api"
    return ""


def _normalize_auth_mode(value: str) -> str:
    cleaned = value.strip().lower()
    if cleaned in {"token", "oauth", "auto", "none"}:
        return cleaned
    return ""


def _get_mcp_catalog_entry(platform: str) -> Dict[str, object]:
    return MCP_CATALOG.get(_resolve_catalog_platform(platform), {})


def _get_mcp_supported_auth_modes(platform: str) -> List[str]:
    entry = _get_mcp_catalog_entry(platform)
    configured = entry.get("auth_modes")
    if isinstance(configured, list):
        modes = [str(item).strip().lower() for item in configured if str(item).strip()]
        filtered = [mode for mode in modes if mode in {"token", "oauth"}]
        if filtered:
            return filtered

    auth = str(entry.get("auth", "token")).strip().lower()
    return [auth] if auth in {"token", "oauth"} else ["token"]


def _get_mcp_default_auth_mode(platform: str) -> str:
    entry = _get_mcp_catalog_entry(platform)
    default_auth = str(entry.get("default_auth", "")).strip().lower()
    supported = _get_mcp_supported_auth_modes(platform)
    if default_auth in supported:
        return default_auth
    return supported[0] if supported else "token"


def _resolve_mcp_auth_mode(platform: str, requested: str) -> str:
    requested_mode = _normalize_auth_mode(requested)
    supported = _get_mcp_supported_auth_modes(platform)
    if requested_mode in {"token", "oauth"} and requested_mode in supported:
        return requested_mode
    return _get_mcp_default_auth_mode(platform)


def _load_mcp_auth_overrides(path_text: str) -> Dict[str, str]:
    if not path_text.strip():
        return {}

    path = Path(path_text).expanduser().resolve()
    if not path.exists():
        raise RuntimeError(f"MCP auth overrides file not found: {path}")

    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise RuntimeError("MCP auth overrides must be a JSON object")

    normalized: Dict[str, str] = {}
    for key, value in payload.items():
        norm_key = _normalize_platform(str(key))
        norm_value = _normalize_auth_mode(str(value))
        if not norm_key or norm_value not in {"token", "oauth"}:
            continue
        normalized[norm_key] = norm_value
    return normalized


def _normalize_platform(name: str) -> str:
    return name.strip().lower()


def _resolve_catalog_platform(name: str) -> str:
    """Resolve known platform aliases to canonical catalog keys.

    This keeps token/env names stable even when inventory/input stores
    variants like "gitlab api" or "jira mcp".
    """
    value = _normalize_platform(name)
    if not value:
        return value

    alias = PLATFORM_ALIASES.get(value)
    if alias:
        return alias

    # Common suffix variants used in freeform intake/exported inventory.
    suffixes = (" api", " mcp", " connector")
    for suffix in suffixes:
        if value.endswith(suffix):
            candidate = value[: -len(suffix)].strip()
            if candidate in API_CATALOG or candidate in MCP_CATALOG:
                return candidate

    return value


def _map_pm_platform(pm_system: str) -> str:
    value = _resolve_catalog_platform(pm_system)
    if value in {"", "none", "not using", "n/a", "na"}:
        return ""
    if value.startswith("jira"):
        return "jira"
    if value.startswith("azure devops"):
        return "azure devops"
    if value.startswith("linear"):
        return "linear"
    if value.startswith("github issues"):
        return "github"
    if value.startswith("bitbucket"):
        return "bitbucket"
    if value.startswith("other"):
        return "other"
    return value


def _map_scm_platform(scm_system: str) -> str:
    return _resolve_catalog_platform(scm_system)


def resolve_connectors(values: Dict[str, str], mcp_auth_overrides: Dict[str, str] | None = None) -> List[ConnectorSpec]:
    mcp_auth_overrides = mcp_auth_overrides or {}
    specs: List[ConnectorSpec] = []

    pm_platform = _map_pm_platform(values.get("pm_system", ""))
    pm_name = values.get("pm_name", "").strip()
    if pm_platform == "other" and pm_name:
        pm_platform = _resolve_catalog_platform(pm_name)
    pm_mode = _normalize_mode(values.get("pm_mode", ""))
    pm_mcp_auth_mode = ""
    pm_endpoint = values.get("pm_url", "")
    if pm_platform and pm_mode:
        catalog_platform = _resolve_catalog_platform(pm_platform)
        endpoint = pm_endpoint or API_CATALOG.get(catalog_platform, {}).get("default_endpoint", "")
        pm_mcp_auth_mode = (
            mcp_auth_overrides.get("pm")
            or mcp_auth_overrides.get(catalog_platform)
            or values.get("pm_mcp_auth_mode", "")
        )
        auth = _resolve_mcp_auth_mode(catalog_platform, pm_mcp_auth_mode) if pm_mode == "mcp" else "token"
        specs.append(ConnectorSpec(platform=pm_platform, category="pm", mode=pm_mode, auth=auth, endpoint=endpoint))

    confluence_url = values.get("confluence_url", "").strip()
    if confluence_url:
        resolved_confluence_mode = _normalize_mode(values.get("confluence_mode", ""))
        # Backward-compatible fallback for older intake files without explicit confluence mode.
        confluence_mode = resolved_confluence_mode or (pm_mode if pm_platform == "jira" and pm_mode else "api")
        confluence_mcp_auth_mode = (
            mcp_auth_overrides.get("confluence")
            or mcp_auth_overrides.get("knowledge")
            or values.get("confluence_mcp_auth_mode", "")
        )
        auth = _resolve_mcp_auth_mode("confluence", confluence_mcp_auth_mode) if confluence_mode == "mcp" else "token"
        specs.append(ConnectorSpec(platform="confluence", category="knowledge", mode=confluence_mode, auth=auth, endpoint=confluence_url))

    scm_platform = _map_scm_platform(values.get("scm_system", ""))
    scm_mode = _normalize_mode(values.get("scm_mode", ""))
    scm_mcp_auth_mode = ""
    if scm_platform and scm_mode:
        catalog_platform = _resolve_catalog_platform(scm_platform)
        endpoint = API_CATALOG.get(catalog_platform, {}).get("default_endpoint", "")
        scm_mcp_auth_mode = (
            mcp_auth_overrides.get("scm")
            or mcp_auth_overrides.get(catalog_platform)
            or values.get("scm_mcp_auth_mode", "")
        )
        auth = _resolve_mcp_auth_mode(catalog_platform, scm_mcp_auth_mode) if scm_mode == "mcp" else "token"
        specs.append(ConnectorSpec(platform=scm_platform, category="scm", mode=scm_mode, auth=auth, endpoint=endpoint))

    unique: Dict[tuple, ConnectorSpec] = {}
    for spec in specs:
        unique[(spec.platform, spec.category)] = spec
    return list(unique.values())


def _safe_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9-]", "-", value.lower()).strip("-")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _reset_directory(path: Path) -> None:
    if path.exists() and path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)


def _is_reusable_api_skill(skill_dir: Path) -> bool:
    required_files = ("SKILL.md", "README.md", "package.json", "config.js", "index.js")
    return skill_dir.is_dir() and all((skill_dir / name).exists() for name in required_files)


def _is_reusable_mcp_skill(skill_dir: Path) -> bool:
    required_files = ("SKILL.md", "README.md", "package.json", "config.js", "index.js")
    return skill_dir.is_dir() and all((skill_dir / name).exists() for name in required_files)


def _copy_skill_bundle(source_dir: Path, target_dir: Path) -> None:
    if target_dir.exists():
        shutil.rmtree(target_dir, ignore_errors=True)
    shutil.copytree(source_dir, target_dir)


def _candidate_repo_roots(output_root: Path) -> List[Path]:
    """Return candidate repository roots ordered by preference.

    This supports both execution contexts:
    1) template workspace root (output-root like outputs/agents-repo)
    2) generated agents-repo opened in a separate window (output-root '.')
    """
    out = output_root.resolve()
    cwd = Path.cwd().resolve()
    script_repo_root = Path(__file__).resolve().parents[2]

    candidates: List[Path] = []

    # Canonical template-workspace mapping.
    if out.name == "agents-repo" and out.parent.name == "outputs":
        candidates.append(out.parent.parent)

    # Runtime current working directory and near-parent fallbacks.
    candidates.append(cwd)
    candidates.extend(list(cwd.parents)[:2])

    # Script location fallback (works when invoking ../../onboarding-utilities/... from agents-repo).
    candidates.append(script_repo_root)

    # If output_root itself is an absolute workspace path, include it and nearby parents.
    candidates.append(out)
    candidates.extend(list(out.parents)[:2])

    unique: List[Path] = []
    seen = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def _resolve_inventory_path(output_root: Path) -> Path:
    for root in _candidate_repo_roots(output_root):
        candidate = root / ".github" / "sdlc-pipeline" / "connector_inventory.json"
        if candidate.exists():
            return candidate

    # Backward compatibility for legacy output-side pipeline state.
    legacy = output_root.resolve() / ".github" / "sdlc-pipeline" / "connector_inventory.json"
    if legacy.exists():
        return legacy

    # Fall back to canonical location under best-effort resolved root for clearer error messaging.
    return _candidate_repo_roots(output_root)[0] / ".github" / "sdlc-pipeline" / "connector_inventory.json"


def _resolve_repo_root(output_root: Path) -> Path:
    out = output_root.resolve()
    if out.name == "agents-repo" and out.parent.name == "outputs":
        return out.parent.parent

    inventory_path = _resolve_inventory_path(output_root)
    if inventory_path.exists():
        return inventory_path.parents[2]

    return _candidate_repo_roots(output_root)[0]


def _resolve_pipeline_dir(output_root: Path) -> Path:
    return _resolve_repo_root(output_root) / ".github" / "sdlc-pipeline"


def _has_nonempty_env_file(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            cleaned = line.strip()
            if cleaned and not cleaned.startswith("#") and "=" in cleaned:
                return True
    except OSError:
        return False
    return False


def _resolve_env_root(output_root: Path) -> Path:
    out = output_root.resolve()
    if out.name == "agents-repo" and out.parent.name == "outputs":
        # When running from an opened generated agents-repo window, keep env
        # resolution local so runtime checks validate that repo's credentials.
        if Path.cwd().resolve() == out:
            return out
        # During template-repo preflight runs, preserve canonical root behavior.
        return out.parent.parent

    for root in _candidate_repo_roots(output_root):
        if _has_nonempty_env_file(root / ".env.encrypted"):
            return root

    for root in _candidate_repo_roots(output_root):
        if (root / ".env.encrypted").exists() or (root / ".env").exists():
            return root
    return _resolve_repo_root(output_root)


def _prune_stale_connector_artifacts(
    skills_dir: Path,
    connector_impl_dir: Path,
    expected_skill_names: List[str],
    expected_impl_files: List[str],
) -> None:
    expected_skill_set = set(expected_skill_names)
    expected_impl_set = set(expected_impl_files)

    if skills_dir.exists():
        for entry in skills_dir.iterdir():
            if not entry.is_dir():
                continue
            if entry.name in expected_skill_set:
                continue
            shutil.rmtree(entry, ignore_errors=True)

    if connector_impl_dir.exists():
        for entry in connector_impl_dir.iterdir():
            if not entry.is_file() or not entry.name.endswith("_api_connector.py"):
                continue
            if entry.name in expected_impl_set:
                continue
            entry.unlink(missing_ok=True)


def _render_mcp_json(connectors: List[ConnectorSpec]) -> Dict[str, object]:
    servers: Dict[str, object] = {}
    for spec in connectors:
        if spec.mode != "mcp":
            continue
        if spec.platform not in MCP_CATALOG:
            continue
        entry = MCP_CATALOG[spec.platform]
        env_map = dict(entry.get("env", {}))
        if "ATLASSIAN_URL" in env_map and spec.endpoint:
            env_map["ATLASSIAN_URL"] = spec.endpoint
        if "AZURE_DEVOPS_URL" in env_map and spec.endpoint:
            env_map["AZURE_DEVOPS_URL"] = spec.endpoint
        servers[entry["server_name"]] = {
            "command": entry["command"],
            "args": entry["args"],
            "env": env_map,
        }
    return {"mcpServers": servers}


def _render_mcp_auth_instructions(connectors: List[ConnectorSpec]) -> str:
    lines: List[str] = ["# MCP Authentication Instructions", ""]
    oauth_connectors = [c for c in connectors if c.mode == "mcp" and c.auth == "oauth"]
    token_connectors = [c for c in connectors if c.mode == "mcp" and c.auth == "token"]

    if oauth_connectors:
        lines.append("## OAuth-based MCP Connectors")
        lines.append("")
        lines.append("OAuth login is an interactive flow handled by your MCP client/server (for example browser consent or device-code login).")
        lines.append("The preflight commands below do not perform login; they only checkpoint completion and re-run verification.")
        lines.append("")
        for spec in oauth_connectors:
            template_mark = (
                f"python onboarding-utilities/scripts/connector-bootstrap.py mark-oauth-complete --connector \"{spec.platform}\" --output-root outputs/agents-repo"
            )
            agents_mark = (
                f"python ../../onboarding-utilities/scripts/connector-bootstrap.py mark-oauth-complete --connector \"{spec.platform}\" --output-root ."
            )
            lines.append(f"### {spec.platform}")
            lines.append("1. Start the MCP server configured in .mcp.json.")
            lines.append("2. Trigger a real connector request from your MCP client to start OAuth login.")
            lines.append("3. Complete the OAuth consent flow (browser/device flow) when prompted.")
            lines.append("4. Verify access by listing resources from the connector after sign-in.")
            lines.append("5. Run these copy-paste commands:")
            lines.append("")
            lines.append("   Template workspace root:")
            lines.append("   ```bash")
            lines.append(f"   {template_mark}")
            lines.append("   ```")
            lines.append("   Opened agents-repo workspace:")
            lines.append("   ```bash")
            lines.append(f"   {agents_mark}")
            lines.append("   ```")
            lines.append("6. Re-run verification:")
            lines.append("   ```bash")
            lines.append("   python onboarding-utilities/scripts/connector-bootstrap.py verify-auth --output-root outputs/agents-repo --allow-dotenv-fallback --fail-on-missing")
            lines.append("   ```")
            lines.append("")

    if token_connectors:
        lines.append("## Token-based MCP Connectors")
        lines.append("")
        lines.append("Collect connector tokens through secure terminal prompts before resuming.")
        lines.append("")
        for spec in token_connectors:
            template_collect = (
                f"python onboarding-utilities/scripts/connector-bootstrap.py collect-token --connector \"{spec.platform}\" --output-root outputs/agents-repo"
            )
            agents_collect = (
                f"python ../../onboarding-utilities/scripts/connector-bootstrap.py collect-token --connector \"{spec.platform}\" --output-root ."
            )
            lines.append(f"- {spec.platform}:")
            lines.append("  1. Template workspace root:")
            lines.append("  ```bash")
            lines.append(f"  {template_collect}")
            lines.append("  ```")
            lines.append("  2. Opened agents-repo workspace:")
            lines.append("  ```bash")
            lines.append(f"  {agents_collect}")
            lines.append("  ```")
        lines.append("")

    if oauth_connectors or token_connectors:
        lines.append("## Verify Authentication")
        lines.append("")
        lines.append("Template workspace root:")
        lines.append("```bash")
        lines.append("python onboarding-utilities/scripts/connector-bootstrap.py verify-auth --output-root outputs/agents-repo --allow-dotenv-fallback --fail-on-missing")
        lines.append("```")
        lines.append("Opened agents-repo workspace:")
        lines.append("```bash")
        lines.append("python ../../onboarding-utilities/scripts/connector-bootstrap.py verify-auth --output-root . --allow-dotenv-fallback --fail-on-missing")
        lines.append("```")
        lines.append("")

    lines.append("After finishing authentication, run /resume-pipeline to continue onboarding.")
    return "\n".join(lines)


def _oauth_status_path(output_root: Path) -> Path:
    return _resolve_pipeline_dir(output_root) / "mcp_oauth_status.json"


def _read_oauth_status(output_root: Path) -> Dict[str, Dict[str, str]]:
    path = _oauth_status_path(output_root)
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload.get("completed", {})
    if not isinstance(entries, dict):
        return {}
    cleaned: Dict[str, Dict[str, str]] = {}
    for key, value in entries.items():
        if isinstance(value, dict):
            cleaned[str(key).strip().lower()] = {
                "completed_at": str(value.get("completed_at", "")).strip()
            }
    return cleaned


def _write_oauth_status(output_root: Path, status: Dict[str, Dict[str, str]]) -> None:
    payload = {
        "completed": status,
    }
    path = _oauth_status_path(output_root)
    _write_text(path, json.dumps(payload, indent=2))


def mark_oauth_complete(connector: str, output_root: Path) -> Dict[str, object]:
    connector_key = _normalize_platform(connector)
    connectors = _load_connectors_from_inventory(output_root)
    oauth_platforms = {spec.platform for spec in connectors if spec.mode == "mcp" and spec.auth == "oauth"}
    if connector_key not in oauth_platforms:
        raise RuntimeError(f"Connector is not configured for MCP OAuth: {connector_key}")

    status = _read_oauth_status(output_root)
    status[connector_key] = {
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_oauth_status(output_root, status)
    return {
        "status": "ok",
        "connector": connector_key,
        "message": "OAuth completion marked",
        "status_file": str(_oauth_status_path(output_root)),
    }


def _render_api_auth_instructions(connectors: List[ConnectorSpec]) -> str:
    lines: List[str] = [
        "# API Connector Token Setup",
        "",
        "Use onboarding-utilities/scripts/connector-bootstrap.py collect-token for each API connector before resuming.",
        "After collecting tokens, run verify-auth to confirm all connectors are ready.",
        "",
    ]
    api_specs = [spec for spec in connectors if spec.mode == "api"]
    required_token_envs: List[str] = []

    if not api_specs:
        lines.append("No API connectors are configured for this onboarding run.")
        return "\n".join(lines)

    for spec in api_specs:
        fallback_token_env = f"{_safe_slug(spec.platform).upper().replace('-', '_')}_TOKEN"
        catalog_platform = _resolve_catalog_platform(spec.platform)
        token_env = API_CATALOG.get(catalog_platform, {}).get("token_env", fallback_token_env)
        required_token_envs.append(token_env)

    lines.append("## Required Token Variables")
    lines.append("")
    for token_env in sorted(set(required_token_envs)):
        lines.append(f"- {token_env}_ENC (preferred encrypted value)")
        lines.append(f"- {token_env} (optional plaintext fallback)")
    lines.append("")

    seen_platforms = set()
    for spec in connectors:
        if spec.mode != "api":
            continue
        if spec.platform in seen_platforms:
            continue
        seen_platforms.add(spec.platform)
        fallback_token_env = f"{_safe_slug(spec.platform).upper().replace('-', '_')}_TOKEN"
        catalog_platform = _resolve_catalog_platform(spec.platform)
        token_env = API_CATALOG.get(catalog_platform, {}).get("token_env", fallback_token_env)
        lines.append(f"- {spec.platform}:")
        lines.append(f"  1. Obtain a token with the required scopes for {spec.platform} APIs.")
        lines.append(f"  2. Required token variable base name: {token_env}")
        lines.append(f"  3. Run from the template workspace root:")
        lines.append("  ```bash")
        lines.append(
            f"  python onboarding-utilities/scripts/connector-bootstrap.py collect-token --connector \"{spec.platform}\" --output-root outputs/agents-repo"
        )
        lines.append("  ```")
        lines.append(f"  4. If running from an opened agents-repo workspace, use:")
        lines.append("  ```bash")
        lines.append(
            f"  python ../../onboarding-utilities/scripts/connector-bootstrap.py collect-token --connector \"{spec.platform}\" --output-root ."
        )
        lines.append("  ```")
        lines.append(f"  5. The encrypted value is stored as {token_env}_ENC in .env.encrypted at repository root.")
        lines.append("")
    lines.append("Validation commands:")
    lines.append("Template workspace root:")
    lines.append("```bash")
    lines.append("python onboarding-utilities/scripts/connector-bootstrap.py verify-auth --output-root outputs/agents-repo --fail-on-missing")
    lines.append("```")
    lines.append("Opened agents-repo workspace:")
    lines.append("```bash")
    lines.append("python ../../onboarding-utilities/scripts/connector-bootstrap.py verify-auth --output-root . --require-dotenv-tokens --fail-on-missing")
    lines.append("```")
    lines.append("")
    lines.append("If verify-auth reports missing .env tokens in opened agents-repo:")
    lines.append("- Copy .env.template to .env")
    lines.append("- Add values for listed token variables")
    lines.append("- Re-run start <ISSUE_ID>")
    return "\n".join(lines)


def _render_connector_skill(spec: ConnectorSpec) -> str:
    catalog_platform = _resolve_catalog_platform(spec.platform)
    skill_name = API_CATALOG.get(catalog_platform, {}).get("skill", f"{_safe_slug(spec.platform)}-connector")
    lines = [
        "---",
        f"name: {skill_name}",
        f"description: \"{spec.platform.title()} connector skill generated during preflight.\"",
        "user-invocable: false",
        "---",
        "",
        f"# {spec.platform.title()} Connector Skill",
        "",
        "## Overview",
        f"Generated connector skill using {spec.mode.upper()} integration mode.",
        "",
        "## Usage",
    ]
    if spec.mode == "mcp":
        lines += [
            "1. Ensure .mcp.json is present and authentication is completed.",
            "2. Use MCP tools through your MCP client.",
            "3. Never store plaintext credentials in prompts or code.",
        ]
    else:
        connector_file = f".github/skills/{skill_name}/index.js"
        lines += [
            f"1. Run connector commands with node {connector_file} --command=<command>.",
            "2. Provide credentials via environment variables only.",
            "3. Never store plaintext credentials in prompt history.",
        ]
    lines += ["", "## Authentication", f"- Mode: {spec.auth}", f"- Integration Type: {spec.mode}", ""]
    return "\n".join(lines)


def _render_api_connector_readme(spec: ConnectorSpec, skill_name: str) -> str:
    return "\n".join(
        [
            f"# {spec.platform.title()} Connector",
            "",
            "Template-generated CLI connector for API integrations.",
            "",
            "## Usage",
            "",
            "```bash",
            f"node .github/skills/{skill_name}/index.js --command=help",
            "```",
            "",
            "## Commands",
            "",
            "- `help`: List available commands",
            "- `test-connection`: Validate API token and endpoint",
            "- `request`: Execute an authenticated request against the connector endpoint",
            "",
            "## Security",
            "",
            "- Keep tokens outside source code and prompts.",
            "- Prefer encrypted token handling in preflight artifacts.",
        ]
    )


def _render_api_connector_package_json(spec: ConnectorSpec) -> str:
    catalog_platform = _resolve_catalog_platform(spec.platform)
    package_payload = {
        "name": API_CATALOG.get(catalog_platform, {}).get("skill", f"{_safe_slug(spec.platform)}-connector"),
        "version": "1.0.0",
        "type": "module",
        "main": "index.js",
        "scripts": {
            "help": "node index.js --command=help",
            "test-connection": "node index.js --command=test-connection",
        },
        "dependencies": {
            "axios": "^1.13.2",
            "dotenv": "^17.2.3",
        },
    }
    return json.dumps(package_payload, indent=2)


def _render_api_connector_config_js(spec: ConnectorSpec) -> str:
    catalog_platform = _resolve_catalog_platform(spec.platform)
    token_env = API_CATALOG.get(catalog_platform, {}).get("token_env", "API_TOKEN")
    endpoint = spec.endpoint or API_CATALOG.get(catalog_platform, {}).get("default_endpoint", "")
    endpoint_env = f"{_safe_slug(spec.platform).upper().replace('-', '_')}_URL"

    return f'''import {{ config }} from "dotenv";

config({{ quiet: true }});

const TOKEN_ENV = "{token_env}";
const ENDPOINT_ENV = "{endpoint_env}";
const DEFAULT_ENDPOINT = "{endpoint}";

export function getToken() {{
  const token = process.env[TOKEN_ENV] || "";
  if (!token) {{
    throw new Error(`Missing ${{TOKEN_ENV}} for {spec.platform} connector.`);
  }}
  return token;
}}

export function getBaseUrl() {{
  return process.env[ENDPOINT_ENV] || DEFAULT_ENDPOINT;
}}
'''


def _render_api_connector_index_js(spec: ConnectorSpec) -> str:
    catalog_platform = _resolve_catalog_platform(spec.platform)
    token_env = API_CATALOG.get(catalog_platform, {}).get("token_env", "API_TOKEN")

    return f'''#!/usr/bin/env node
import axios from "axios";
import {{ getBaseUrl, getToken }} from "./config.js";

function parseArgs() {{
  const parsed = {{}};
  for (const arg of process.argv.slice(2)) {{
    if (!arg.startsWith("--")) continue;
    const idx = arg.indexOf("=");
    const key = idx === -1 ? arg.slice(2) : arg.slice(2, idx);
    const value = idx === -1 ? "true" : arg.slice(idx + 1);
    parsed[key] = value;
  }}
  return parsed;
}}

function output(data, success = true, exitCode = 0) {{
  const payload = success ? {{ success: true, data }} : {{ success: false, error: data }};
  process.stdout.write(`${{JSON.stringify(payload, null, 2)}}\n`);
  process.exitCode = exitCode;
}}

async function callApi(path, method = "GET", body = null) {{
  const response = await axios({{
    method,
    url: `${{getBaseUrl().replace(/\\/+$/, "")}}/${{String(path || "").replace(/^\\/+/, "")}}`,
    headers: {{
      Authorization: `Bearer ${{getToken()}}`,
      Accept: "application/json",
      "Content-Type": "application/json",
    }},
    data: body,
  }});
  return response.data;
}}

async function main() {{
  const args = parseArgs();
  const command = args.command || "help";

  try {{
    if (command === "help") {{
      output({{
        connector: "{spec.platform}",
        requiredEnv: ["{token_env}"],
        commands: ["help", "test-connection", "request"],
      }});
      return;
    }}

    if (command === "test-connection") {{
      const data = await callApi(args.path || "");
      output({{ connector: "{spec.platform}", ok: true, data }});
      return;
    }}

    if (command === "request") {{
      const method = String(args.method || "GET").toUpperCase();
      const body = args.body ? JSON.parse(args.body) : null;
      const data = await callApi(args.path || "", method, body);
      output({{ connector: "{spec.platform}", data }});
      return;
    }}

    output(`Unknown command: ${{command}}`, false, 1);
  }} catch (error) {{
    const message = error?.response?.data || error?.message || String(error);
    output(message, false, 1);
  }}
}}

void main();
'''


def _render_connector_config(connectors: List[ConnectorSpec]) -> str:
    lines = ["# Connector Configuration", "", "| Platform | Category | Mode | Auth | Endpoint |", "|----------|----------|------|------|----------|"]
    for spec in connectors:
        lines.append(f"| {spec.platform} | {spec.category} | {spec.mode} | {spec.auth} | {spec.endpoint or '_'} |")
    lines.append("")
    return "\n".join(lines)


def _extract_placeholder_env_name(value: str) -> str:
    text = str(value).strip()
    if text.startswith("${") and text.endswith("}"):
        return text[2:-1].strip()
    return ""


def _render_env_template(connectors: List[ConnectorSpec]) -> str:
    lines: List[str] = [
        "# Generated connector environment template",
        "# Copy this file to .env and fill token values before running start <ISSUE_ID>",
        "",
    ]

    api_token_bases: List[str] = []
    mcp_token_vars: List[str] = []

    for spec in connectors:
        if spec.mode == "api":
            fallback_token_env = f"{_safe_slug(spec.platform).upper().replace('-', '_')}_TOKEN"
            catalog_platform = _resolve_catalog_platform(spec.platform)
            token_env = API_CATALOG.get(catalog_platform, {}).get("token_env", fallback_token_env)
            api_token_bases.append(token_env)
            continue

        if spec.mode == "mcp" and spec.auth == "token":
            catalog_platform = _resolve_catalog_platform(spec.platform)
            entry = MCP_CATALOG.get(catalog_platform, {})
            env_map = dict(entry.get("env", {}))
            for key, raw_value in env_map.items():
                if key.endswith("URL"):
                    continue
                env_name = _extract_placeholder_env_name(str(raw_value)) or key
                mcp_token_vars.append(env_name)

    api_token_bases = sorted(set(api_token_bases))
    mcp_token_vars = sorted(set(mcp_token_vars))

    if api_token_bases:
        lines.append("# API connector tokens (runtime checks require these in .env)")
        for token_env in api_token_bases:
            lines.append(f"{token_env}=")
        lines.append("")

    if mcp_token_vars:
        lines.append("# MCP token-based connector variables")
        for env_name in mcp_token_vars:
            lines.append(f"{env_name}=")
        lines.append("")

    lines.append("# Optional keyring service name for encrypted connector tokens")
    lines.append(f"SDLC_CONNECTOR_KEYRING_SERVICE={KEYRING_SERVICE_DEFAULT}")
    lines.append("")

    return "\n".join(lines)


def _build_verify_auth_remediation(
    output_root: Path,
    connectors: List[ConnectorSpec],
    api_missing_tokens: List[Dict[str, str]],
    mcp_token_pending: List[Dict[str, object]],
    mcp_oauth_pending: List[str],
    api_missing_dotenv_tokens: List[Dict[str, str]],
    blocked: bool,
) -> Dict[str, object]:
    template_path = str(output_root.resolve() / ".env.template")
    if not blocked:
        return {
            "env_template": template_path,
            "steps": [],
        }

    missing_any_of = [row.get("required_any_of", "") for row in api_missing_dotenv_tokens if row.get("required_any_of")]
    token_hints = sorted(set(missing_any_of))

    steps: List[str] = [
        "Connector preflight stopped because authentication is incomplete.",
        "For MCP OAuth connectors, first complete OAuth in your MCP client/server (interactive browser or device-code flow).",
        "Then run the exact per-connector commands shown below in terminal.",
        "Re-run verify-auth after completing the commands.",
        "Resume preflight once verify-auth returns blocked: false.",
    ]
    if token_hints:
        steps.append(f"Missing variables: {', '.join(token_hints)}")

    token_platforms = sorted(
        {
            _resolve_catalog_platform(str(item.get("platform", "")))
            for item in api_missing_tokens
            if item.get("platform")
        }
        | {
            _resolve_catalog_platform(str(item.get("platform", "")))
            for item in mcp_token_pending
            if item.get("platform")
        }
    )

    oauth_platforms = sorted({_resolve_catalog_platform(item) for item in mcp_oauth_pending if item})

    token_commands = [
        {
            "platform": platform,
            "template_workspace": f"python onboarding-utilities/scripts/connector-bootstrap.py collect-token --connector \"{platform}\" --output-root outputs/agents-repo",
            "agents_repo_workspace": f"python ../../onboarding-utilities/scripts/connector-bootstrap.py collect-token --connector \"{platform}\" --output-root .",
        }
        for platform in token_platforms
    ]

    oauth_commands = [
        {
            "platform": platform,
            "mark_complete_template_workspace": f"python onboarding-utilities/scripts/connector-bootstrap.py mark-oauth-complete --connector \"{platform}\" --output-root outputs/agents-repo",
            "mark_complete_agents_repo_workspace": f"python ../../onboarding-utilities/scripts/connector-bootstrap.py mark-oauth-complete --connector \"{platform}\" --output-root .",
        }
        for platform in oauth_platforms
    ]
    return {
        "env_template": template_path,
        "copy_commands": {
            "powershell": "Copy-Item .env.template .env",
            "bash": "cp .env.template .env",
        },
        "steps": steps,
        "terminal_commands": {
            "token_collection": token_commands,
            "oauth_completion": oauth_commands,
            "verify_auth": {
                "template_workspace": "python onboarding-utilities/scripts/connector-bootstrap.py verify-auth --output-root outputs/agents-repo --allow-dotenv-fallback --fail-on-missing",
                "agents_repo_workspace": "python ../../onboarding-utilities/scripts/connector-bootstrap.py verify-auth --output-root . --allow-dotenv-fallback --fail-on-missing",
            },
        },
        "copy_paste_commands": {
            "api_and_mcp_token_template_workspace": [cmd["template_workspace"] for cmd in token_commands],
            "api_and_mcp_token_agents_repo_workspace": [cmd["agents_repo_workspace"] for cmd in token_commands],
            "mcp_oauth_template_workspace": [cmd["mark_complete_template_workspace"] for cmd in oauth_commands],
            "mcp_oauth_agents_repo_workspace": [cmd["mark_complete_agents_repo_workspace"] for cmd in oauth_commands],
            "verify_auth_template_workspace": "python onboarding-utilities/scripts/connector-bootstrap.py verify-auth --output-root outputs/agents-repo --allow-dotenv-fallback --fail-on-missing",
            "verify_auth_agents_repo_workspace": "python ../../onboarding-utilities/scripts/connector-bootstrap.py verify-auth --output-root . --allow-dotenv-fallback --fail-on-missing",
        },
    }


def generate_artifacts(intake: Path, output_root: Path, mcp_auth_overrides_path: str = "") -> Dict[str, object]:
    values = parse_intake_markdown(intake)
    mcp_auth_overrides = _load_mcp_auth_overrides(mcp_auth_overrides_path)
    connectors = resolve_connectors(values, mcp_auth_overrides=mcp_auth_overrides)

    repo_root = _resolve_repo_root(output_root)
    pipeline_dir = repo_root / ".github" / "sdlc-pipeline"
    skills_dir = output_root / ".github" / "skills"
    root_skills_dir = repo_root / ".github" / "skills"
    connector_impl_dir = output_root / ".github" / "connectors"
    legacy_pipeline_dir = output_root / ".github" / "sdlc-pipeline"
    env_root = _resolve_env_root(output_root)

    pipeline_dir.mkdir(parents=True, exist_ok=True)
    skills_dir.mkdir(parents=True, exist_ok=True)
    root_skills_dir.mkdir(parents=True, exist_ok=True)

    # Root env files are created during preflight so auth flow has a stable location.
    (env_root / ".env").touch(exist_ok=True)
    (env_root / ".env.encrypted").touch(exist_ok=True)
    # Keep generated agents-repo self-contained when opened separately.
    (output_root.resolve() / ".env").touch(exist_ok=True)
    (output_root.resolve() / ".env.encrypted").touch(exist_ok=True)

    # Keep a single source of truth in repo-root .github/sdlc-pipeline.
    if legacy_pipeline_dir.exists():
        shutil.rmtree(legacy_pipeline_dir, ignore_errors=True)

    inventory = {
        "generated_by": "connector-bootstrap.py",
        "source": str(intake),
        "connectors": [spec.to_dict() for spec in connectors],
    }
    _write_text(pipeline_dir / "connector_inventory.json", json.dumps(inventory, indent=2))

    mcp_json = _render_mcp_json(connectors)
    mcp_json_path = output_root / ".mcp.json"
    mcp_auth_path = pipeline_dir / "mcp_auth_instructions.md"
    if mcp_json.get("mcpServers"):
        _write_text(mcp_json_path, json.dumps(mcp_json, indent=2))
        _write_text(mcp_auth_path, _render_mcp_auth_instructions(connectors))
    else:
        mcp_json_path.unlink(missing_ok=True)
        mcp_auth_path.unlink(missing_ok=True)

    api_connectors = [c for c in connectors if c.mode == "api"]
    api_auth_path = pipeline_dir / "api_auth_instructions.md"
    if api_connectors:
        _write_text(api_auth_path, _render_api_auth_instructions(connectors))
    else:
        api_auth_path.unlink(missing_ok=True)

    _write_text(output_root / ".env.template", _render_env_template(connectors))

    _write_text(pipeline_dir / "connector_config.md", _render_connector_config(connectors))

    generated_skills: List[str] = []
    generated_impls: List[str] = []
    expected_skill_names: List[str] = []
    expected_impl_files: List[str] = []
    reusable_skill_catalog = _resolve_repo_root(output_root) / ".github" / "skills"

    for spec in connectors:
        catalog_platform = _resolve_catalog_platform(spec.platform)
        skill_name = API_CATALOG.get(catalog_platform, {}).get("skill", f"{_safe_slug(spec.platform)}-connector")
        if spec.mode == "mcp":
            skill_name = f"mcp-{skill_name}"
        expected_skill_names.append(skill_name)

        skill_dir = skills_dir / skill_name
        root_skill_dir = root_skills_dir / skill_name
        _reset_directory(skill_dir)

        reusable_skill_dir = reusable_skill_catalog / skill_name
        reusable_api = spec.mode == "api" and _is_reusable_api_skill(reusable_skill_dir)
        reusable_mcp = spec.mode == "mcp" and _is_reusable_mcp_skill(reusable_skill_dir)
        if reusable_api or reusable_mcp:
            _copy_skill_bundle(reusable_skill_dir, skill_dir)
            generated_skills.append(str(skill_dir / "SKILL.md"))
            generated_skills.append(str(reusable_skill_dir / "SKILL.md"))

            if reusable_api or reusable_mcp:
                if (skill_dir / "index.js").exists():
                    generated_impls.append(str(skill_dir / "index.js"))
                if (reusable_skill_dir / "index.js").exists():
                    generated_impls.append(str(reusable_skill_dir / "index.js"))
            continue

        _reset_directory(root_skill_dir)

        skill_path = skill_dir / "SKILL.md"
        _write_text(skill_path, _render_connector_skill(spec))
        generated_skills.append(str(skill_path))
        _write_text(root_skill_dir / "SKILL.md", _render_connector_skill(spec))
        generated_skills.append(str(root_skill_dir / "SKILL.md"))

        if spec.mode == "api":
            _write_text(skill_dir / "README.md", _render_api_connector_readme(spec, skill_name))
            _write_text(skill_dir / "package.json", _render_api_connector_package_json(spec))
            _write_text(skill_dir / ".gitignore", "node_modules/\n.env\n")
            _write_text(skill_dir / "config.js", _render_api_connector_config_js(spec))
            _write_text(skill_dir / "index.js", _render_api_connector_index_js(spec))
            generated_impls.append(str(skill_dir / "index.js"))

            _write_text(root_skill_dir / "README.md", _render_api_connector_readme(spec, skill_name))
            _write_text(root_skill_dir / "package.json", _render_api_connector_package_json(spec))
            _write_text(root_skill_dir / ".gitignore", "node_modules/\n.env\n")
            _write_text(root_skill_dir / "config.js", _render_api_connector_config_js(spec))
            _write_text(root_skill_dir / "index.js", _render_api_connector_index_js(spec))
            generated_impls.append(str(root_skill_dir / "index.js"))

    _prune_stale_connector_artifacts(
        skills_dir=skills_dir,
        connector_impl_dir=connector_impl_dir,
        expected_skill_names=expected_skill_names,
        expected_impl_files=expected_impl_files,
    )

    return {
        "status": "ok",
        "connectors": [spec.to_dict() for spec in connectors],
        "skills": generated_skills,
        "implementations": generated_impls,
        "mcp_generated": bool(mcp_json.get("mcpServers")),
    }


def _load_encryption_dependencies():
    try:
        from cryptography.fernet import Fernet  # type: ignore
    except Exception as exc:
        raise RuntimeError("cryptography package is required. Install with: pip install cryptography") from exc
    try:
        import keyring  # type: ignore
    except Exception as exc:
        raise RuntimeError("keyring package is required. Install with: pip install keyring") from exc
    return Fernet, keyring


def _upsert_env_file(path: Path, key: str, value: str) -> None:
    existing: Dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.strip().startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            existing[k.strip()] = v.strip()
    existing[key] = value
    ordered = [f"{k}={existing[k]}" for k in sorted(existing.keys())]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(ordered) + "\n", encoding="utf-8")


def _mirror_encrypted_env(output_root: Path, key: str, value: str) -> None:
    """Mirror encrypted connector state into generated agents-repo."""
    target = output_root.resolve() / ".env.encrypted"
    _upsert_env_file(target, key, value)
    _upsert_env_file(target, "SDLC_CONNECTOR_KEYRING_SERVICE", KEYRING_SERVICE_DEFAULT)


def _read_env_file(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        cleaned = line.strip()
        if not cleaned or cleaned.startswith("#") or "=" not in cleaned:
            continue
        key, value = cleaned.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _resolve_api_token_readiness(
    connectors: List[ConnectorSpec],
    encrypted_env: Dict[str, str],
    dotenv_env: Dict[str, str],
    allow_dotenv_fallback: bool,
) -> Dict[str, object]:
    missing: List[Dict[str, str]] = []
    satisfied_via_dotenv: List[Dict[str, str]] = []

    for spec in connectors:
        if spec.mode != "api":
            continue

        catalog_platform = _resolve_catalog_platform(spec.platform)
        token_env = API_CATALOG.get(catalog_platform, {}).get("token_env", f"{_safe_slug(spec.platform).upper()}_TOKEN")
        enc_key = f"{token_env}_ENC"

        if encrypted_env.get(enc_key, "").strip():
            continue

        dotenv_enc = dotenv_env.get(enc_key, "").strip()
        dotenv_plain = dotenv_env.get(token_env, "").strip()

        if allow_dotenv_fallback and (dotenv_enc or dotenv_plain):
            source_key = enc_key if dotenv_enc else token_env
            satisfied_via_dotenv.append({"platform": spec.platform, "source": source_key})
            continue

        missing.append({"platform": spec.platform, "required_env": enc_key})

    return {
        "missing": missing,
        "satisfied_via_dotenv": satisfied_via_dotenv,
    }


def _resolve_api_dotenv_token_presence(
    connectors: List[ConnectorSpec],
    dotenv_env: Dict[str, str],
) -> List[Dict[str, str]]:
    missing: List[Dict[str, str]] = []

    for spec in connectors:
        if spec.mode != "api":
            continue

        catalog_platform = _resolve_catalog_platform(spec.platform)
        token_env = API_CATALOG.get(catalog_platform, {}).get("token_env", f"{_safe_slug(spec.platform).upper()}_TOKEN")
        enc_key = f"{token_env}_ENC"
        if dotenv_env.get(token_env, "").strip() or dotenv_env.get(enc_key, "").strip():
            continue

        missing.append({
            "platform": spec.platform,
            "required_any_of": f"{token_env} or {enc_key}",
            "file": ".env",
        })

    return missing


def _load_connectors_from_inventory(output_root: Path) -> List[ConnectorSpec]:
    inventory_path = _resolve_inventory_path(output_root)
    if not inventory_path.exists():
        raise RuntimeError(f"Missing connector inventory: {inventory_path}")

    payload = json.loads(inventory_path.read_text(encoding="utf-8"))
    connectors: List[ConnectorSpec] = []
    for row in payload.get("connectors", []):
        raw_platform = str(row.get("platform", "")).strip().lower()
        canonical_platform = _resolve_catalog_platform(raw_platform)
        connectors.append(
            ConnectorSpec(
                platform=canonical_platform,
                category=str(row.get("category", "")).strip().lower(),
                mode=str(row.get("mode", "")).strip().lower(),
                auth=str(row.get("auth", "")).strip().lower(),
                endpoint=str(row.get("endpoint", "")).strip(),
            )
        )
    return connectors


def _extract_mcp_missing_env(mcp_json: Dict[str, object], spec: ConnectorSpec) -> List[str]:
    catalog_platform = _resolve_catalog_platform(spec.platform)
    catalog = MCP_CATALOG.get(catalog_platform, {})
    server_name = str(catalog.get("server_name", ""))
    if not server_name:
        return []

    servers = mcp_json.get("mcpServers", {})
    if not isinstance(servers, dict):
        return ["mcpServers"]

    server_entry = servers.get(server_name)
    if not isinstance(server_entry, dict):
        return [server_name]

    env_map = server_entry.get("env", {})
    if not isinstance(env_map, dict):
        return [f"{server_name}.env"]

    missing: List[str] = []
    for key, value in env_map.items():
        if key.endswith("URL"):
            continue
        value_text = str(value).strip()
        if not value_text or (value_text.startswith("${") and value_text.endswith("}")):
            missing.append(key)
    return missing


def _required_mcp_token_env_names(spec: ConnectorSpec) -> List[str]:
    catalog_platform = _resolve_catalog_platform(spec.platform)
    entry = MCP_CATALOG.get(catalog_platform, {})
    env_map = dict(entry.get("env", {}))
    required: List[str] = []
    for key, raw_value in env_map.items():
        if key.endswith("URL"):
            continue
        env_name = _extract_placeholder_env_name(str(raw_value)) or key
        if env_name:
            required.append(env_name)
    return sorted(set(required))


def _resolve_mcp_token_readiness(
    connectors: List[ConnectorSpec],
    encrypted_env: Dict[str, str],
    dotenv_env: Dict[str, str],
    allow_dotenv_fallback: bool,
) -> Dict[str, object]:
    missing: List[Dict[str, object]] = []
    satisfied_via_dotenv: List[Dict[str, str]] = []

    for spec in connectors:
        if spec.mode != "mcp" or spec.auth != "token":
            continue

        required_env = _required_mcp_token_env_names(spec)
        unresolved: List[str] = []
        for env_name in required_env:
            enc_key = f"{env_name}_ENC"
            if encrypted_env.get(enc_key, "").strip():
                continue

            dotenv_enc = dotenv_env.get(enc_key, "").strip()
            dotenv_plain = dotenv_env.get(env_name, "").strip()
            if allow_dotenv_fallback and (dotenv_enc or dotenv_plain):
                source_key = enc_key if dotenv_enc else env_name
                satisfied_via_dotenv.append({"platform": spec.platform, "source": source_key})
                continue

            unresolved.append(enc_key)

        if unresolved:
            missing.append({"platform": spec.platform, "required_env": unresolved})

    return {
        "missing": missing,
        "satisfied_via_dotenv": satisfied_via_dotenv,
    }


def verify_auth(
    output_root: Path,
    allow_dotenv_fallback: bool = False,
    require_dotenv_tokens: bool = False,
) -> Dict[str, object]:
    connectors = _load_connectors_from_inventory(output_root)
    env_root = _resolve_env_root(output_root)
    encrypted_env = _read_env_file(env_root / ".env.encrypted")
    dotenv_env = _read_env_file(env_root / ".env")

    api_readiness = _resolve_api_token_readiness(
        connectors=connectors,
        encrypted_env=encrypted_env,
        dotenv_env=dotenv_env,
        allow_dotenv_fallback=allow_dotenv_fallback,
    )
    api_missing = api_readiness["missing"]
    api_satisfied_via_dotenv = api_readiness["satisfied_via_dotenv"]
    api_missing_dotenv_tokens = (
        _resolve_api_dotenv_token_presence(connectors=connectors, dotenv_env=dotenv_env)
        if require_dotenv_tokens
        else []
    )

    oauth_status = _read_oauth_status(output_root)
    oauth_pending = [
        spec.platform
        for spec in connectors
        if spec.mode == "mcp" and spec.auth == "oauth" and spec.platform not in oauth_status
    ]
    oauth_completed = [
        {"platform": spec.platform, "completed_at": oauth_status[spec.platform].get("completed_at", "")}
        for spec in connectors
        if spec.mode == "mcp" and spec.auth == "oauth" and spec.platform in oauth_status
    ]

    mcp_token_readiness = _resolve_mcp_token_readiness(
        connectors=connectors,
        encrypted_env=encrypted_env,
        dotenv_env=dotenv_env,
        allow_dotenv_fallback=allow_dotenv_fallback,
    )
    mcp_token_pending = mcp_token_readiness["missing"]
    mcp_token_satisfied_via_dotenv = mcp_token_readiness["satisfied_via_dotenv"]

    blocked = bool(api_missing or api_missing_dotenv_tokens or oauth_pending or mcp_token_pending)
    status = "blocked" if blocked else "ok"
    remediation = _build_verify_auth_remediation(
        output_root=output_root,
        connectors=connectors,
        api_missing_tokens=api_missing,
        mcp_token_pending=mcp_token_pending,
        mcp_oauth_pending=oauth_pending,
        api_missing_dotenv_tokens=api_missing_dotenv_tokens,
        blocked=blocked,
    )
    return {
        "status": status,
        "blocked": blocked,
        "allow_dotenv_fallback": allow_dotenv_fallback,
        "require_dotenv_tokens": require_dotenv_tokens,
        "summary": {
            "api_missing_tokens": len(api_missing),
            "api_missing_dotenv_tokens": len(api_missing_dotenv_tokens),
            "api_satisfied_via_dotenv": len(api_satisfied_via_dotenv),
            "mcp_oauth_pending": len(oauth_pending),
            "mcp_oauth_completed": len(oauth_completed),
            "mcp_token_pending": len(mcp_token_pending),
            "mcp_token_satisfied_via_dotenv": len(mcp_token_satisfied_via_dotenv),
        },
        "api_missing_tokens": api_missing,
        "api_missing_dotenv_tokens": api_missing_dotenv_tokens,
        "api_satisfied_via_dotenv": api_satisfied_via_dotenv,
        "mcp_oauth_pending": oauth_pending,
        "mcp_oauth_completed": oauth_completed,
        "mcp_token_pending": mcp_token_pending,
        "mcp_token_satisfied_via_dotenv": mcp_token_satisfied_via_dotenv,
        "remediation": remediation,
    }


def collect_token(connector: str, output_root: Path, token_env_override: str = "") -> Dict[str, str]:
    connector_key = _normalize_platform(connector)
    catalog_platform = _resolve_catalog_platform(connector_key)
    connectors = _load_connectors_from_inventory(output_root)
    matching_connector = next((spec for spec in connectors if _resolve_catalog_platform(spec.platform) == catalog_platform), None)
    if matching_connector is None:
        raise RuntimeError(f"Unsupported connector for token collection: {connector}")

    fallback_token_env = f"{_safe_slug(catalog_platform).upper().replace('-', '_')}_TOKEN"
    if token_env_override.strip():
        token_env = token_env_override.strip()
    elif matching_connector.mode == "api":
        token_env = API_CATALOG.get(catalog_platform, {}).get("token_env", fallback_token_env)
    elif matching_connector.mode == "mcp" and matching_connector.auth == "token":
        token_envs = _required_mcp_token_env_names(matching_connector)
        if not token_envs:
            raise RuntimeError(f"No MCP token variable mapping found for connector: {catalog_platform}")
        token_env = token_envs[0]
    else:
        raise RuntimeError(f"Connector is not configured for token authentication: {catalog_platform}")
    token_value = getpass.getpass(prompt=f"Enter token for {catalog_platform}: ").strip()
    if not token_value:
        raise RuntimeError("Token cannot be empty")

    fernet_cls, keyring = _load_encryption_dependencies()
    key_value = keyring.get_password(KEYRING_SERVICE_DEFAULT, "fernet_key")
    if not key_value:
        key_value = fernet_cls.generate_key().decode("utf-8")
        keyring.set_password(KEYRING_SERVICE_DEFAULT, "fernet_key", key_value)

    fernet = fernet_cls(key_value.encode("utf-8"))
    encrypted = fernet.encrypt(token_value.encode("utf-8")).decode("utf-8")

    env_root = _resolve_env_root(output_root)
    env_file = env_root / ".env.encrypted"
    _upsert_env_file(env_file, f"{token_env}_ENC", encrypted)
    _upsert_env_file(env_file, "SDLC_CONNECTOR_KEYRING_SERVICE", KEYRING_SERVICE_DEFAULT)
    _mirror_encrypted_env(output_root, f"{token_env}_ENC", encrypted)

    return {
        "status": "ok",
        "connector": catalog_platform,
        "encrypted_env": f"{token_env}_ENC",
        "env_file": str(env_file),
    }


def main() -> int:
    args = parse_arg()
    try:
        if args.command == "generate":
            result = generate_artifacts(
                intake=Path(args.intake),
                output_root=Path(args.output_root),
                mcp_auth_overrides_path=getattr(args, "mcp_auth_overrides", ""),
            )
        elif args.command == "collect-token":
            result = collect_token(connector=args.connector, output_root=Path(args.output_root), token_env_override=args.token_env)
        elif args.command == "mark-oauth-complete":
            result = mark_oauth_complete(connector=args.connector, output_root=Path(args.output_root))
        else:
            result = verify_auth(
                output_root=Path(args.output_root),
                allow_dotenv_fallback=args.allow_dotenv_fallback,
                require_dotenv_tokens=args.require_dotenv_tokens,
            )
            print(json.dumps(result, indent=2))
            if args.fail_on_missing and result.get("blocked"):
                return 3
            return 0

        print(json.dumps(result, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "error", "message": str(exc)}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
