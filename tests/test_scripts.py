#!/usr/bin/env python3
"""
Unit tests for SDLC Pipeline Python scripts.

Run with: python3 -m pytest tests/ -v
Or:       python3 tests/test_scripts.py
"""

import json
import os
import subprocess
import sys
import tempfile
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

# Add scripts directory to path
SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "onboarding-utilities", "scripts")
sys.path.insert(0, SCRIPTS_DIR)


# =============================================================================
# checkpoint-manager.py tests
# =============================================================================
class TestCheckpointManager(unittest.TestCase):
    """Tests for checkpoint-manager.py"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.state_file = os.path.join(self.tmpdir, "checkpoint_state.json")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run_cmd(self, args_list):
        """Helper to run checkpoint-manager commands."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "checkpoint_manager",
            os.path.join(SCRIPTS_DIR, "checkpoint-manager.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_save_creates_state_file(self):
        mod = self._run_cmd([])
        state = mod.load_state(self.state_file)
        self.assertIn("agents", state)
        self.assertEqual(state["agents"], {})

    def test_save_and_load_roundtrip(self):
        mod = self._run_cmd([])
        state = mod.load_state(self.state_file)
        state["agents"]["preflight"] = {
            "status": "completed",
            "started_at": mod.utc_now(),
            "phases": {"Phase 1": {"status": "completed", "completed_at": mod.utc_now()}},
            "feedback": [],
            "run_count": 1,
            "errors": [],
        }
        mod.save_state(self.state_file, state)

        loaded = mod.load_state(self.state_file)
        self.assertIn("preflight", loaded["agents"])
        self.assertEqual(loaded["agents"]["preflight"]["status"], "completed")

    def test_load_nonexistent_returns_empty(self):
        mod = self._run_cmd([])
        state = mod.load_state("/nonexistent/path/state.json")
        self.assertEqual(state["agents"], {})
        self.assertEqual(state["version"], "1.0.0")

    def test_save_creates_directories(self):
        mod = self._run_cmd([])
        nested_path = os.path.join(self.tmpdir, "a", "b", "c", "state.json")
        state = mod.load_state(nested_path)
        mod.save_state(nested_path, state)
        self.assertTrue(os.path.exists(nested_path))

    def test_concurrent_saves_dont_corrupt(self):
        """Test that file locking prevents corruption."""
        mod = self._run_cmd([])
        state = mod.load_state(self.state_file)
        state["agents"]["agent1"] = {
            "status": "in_progress",
            "started_at": mod.utc_now(),
            "phases": {},
            "feedback": [],
            "run_count": 1,
            "errors": [],
        }
        mod.save_state(self.state_file, state)

        # Second save should not corrupt
        state2 = mod.load_state(self.state_file)
        state2["agents"]["agent2"] = {
            "status": "completed",
            "started_at": mod.utc_now(),
            "phases": {},
            "feedback": [],
            "run_count": 1,
            "errors": [],
        }
        mod.save_state(self.state_file, state2)

        final = mod.load_state(self.state_file)
        self.assertIn("agent1", final["agents"])
        self.assertIn("agent2", final["agents"])

    def test_corrupted_json_returns_empty(self):
        mod = self._run_cmd([])
        with open(self.state_file, "w") as f:
            f.write("{invalid json!!!")
        state = mod.load_state(self.state_file)
        self.assertEqual(state["agents"], {})

    def test_feedback_preserves_across_reset(self):
        mod = self._run_cmd([])
        state = mod.load_state(self.state_file)
        state["agents"]["preflight"] = {
            "status": "awaiting_rerun",
            "started_at": mod.utc_now(),
            "phases": {"Phase 1": {"status": "completed", "completed_at": mod.utc_now()}},
            "feedback": [{"message": "Fix X", "timestamp": mod.utc_now(), "phase": "Phase 1"}],
            "run_count": 1,
            "errors": [],
        }
        mod.save_state(self.state_file, state)

        # Simulate reset preserving feedback
        loaded = mod.load_state(self.state_file)
        old_feedback = loaded["agents"]["preflight"]["feedback"]
        loaded["agents"]["preflight"] = {
            "status": "not_started",
            "started_at": None,
            "phases": {},
            "feedback": old_feedback,
            "run_count": 2,
            "errors": [],
        }
        mod.save_state(self.state_file, loaded)

        final = mod.load_state(self.state_file)
        self.assertEqual(len(final["agents"]["preflight"]["feedback"]), 1)
        self.assertEqual(final["agents"]["preflight"]["run_count"], 2)


# =============================================================================
# repo-scanner.py tests
# =============================================================================
class TestRepoScanner(unittest.TestCase):
    """Tests for repo-scanner.py"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _load_scanner(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "repo_scanner",
            os.path.join(SCRIPTS_DIR, "repo-scanner.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def _create_repo(self, files: dict):
        """Create a mock repo structure."""
        for path, content in files.items():
            full_path = os.path.join(self.tmpdir, path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w") as f:
                f.write(content)

    def test_tag_source_file(self):
        mod = self._load_scanner()
        tags = mod.tag_file("src/app.ts")
        self.assertIn("source", tags)

    def test_tag_test_file(self):
        mod = self._load_scanner()
        tags = mod.tag_file("src/app.test.ts")
        self.assertIn("test", tags)
        self.assertNotIn("source", tags)  # test takes priority

    def test_tag_config_file(self):
        mod = self._load_scanner()
        tags = mod.tag_file("tsconfig.json")
        self.assertIn("config", tags)

    def test_tag_docs_file(self):
        mod = self._load_scanner()
        tags = mod.tag_file("README.md")
        self.assertIn("docs", tags)

    def test_tag_cicd_file(self):
        mod = self._load_scanner()
        tags = mod.tag_file(".github/workflows/ci.yml")
        self.assertIn("ci_cd", tags)

    def test_tag_infra_file(self):
        mod = self._load_scanner()
        tags = mod.tag_file("infra/main.tf")
        self.assertIn("infra", tags)

    def test_ignore_node_modules(self):
        mod = self._load_scanner()
        self.assertTrue(mod.should_ignore_dir("node_modules"))
        self.assertTrue(mod.should_ignore_dir(".git"))
        self.assertFalse(mod.should_ignore_dir("src"))

    def test_ignore_binary_files(self):
        mod = self._load_scanner()
        self.assertTrue(mod.should_ignore_file("image.png"))
        self.assertTrue(mod.should_ignore_file("font.woff2"))
        self.assertFalse(mod.should_ignore_file("app.ts"))

    def test_detect_lock_files(self):
        mod = self._load_scanner()
        self._create_repo({"package-lock.json": "{}", "yarn.lock": ""})
        locks = mod.detect_lock_file(self.tmpdir)
        self.assertIn("package-lock.json", locks)
        self.assertEqual(locks["package-lock.json"], "npm")

    def test_parse_package_json(self):
        mod = self._load_scanner()
        pkg = {
            "name": "test-app",
            "version": "1.0.0",
            "dependencies": {"react": "^18.0.0", "next": "^14.0.0"},
            "devDependencies": {"jest": "^29.0.0"},
            "scripts": {"test": "jest", "build": "next build"},
        }
        self._create_repo({"package.json": json.dumps(pkg)})
        result = mod.parse_package_json(self.tmpdir)
        self.assertEqual(result["name"], "test-app")
        self.assertIn("React", result["detected_frameworks"])
        self.assertIn("Next.js", result["detected_frameworks"])
        self.assertIn("react", result["dependencies"])

    def test_parse_package_json_missing(self):
        mod = self._load_scanner()
        result = mod.parse_package_json(self.tmpdir)
        self.assertEqual(result, {})

    def test_detect_linter_eslint(self):
        mod = self._load_scanner()
        self._create_repo({".eslintrc.json": "{}"})
        linters = mod.detect_linter(self.tmpdir)
        self.assertIn("eslint", linters)

    def test_detect_linter_biome(self):
        mod = self._load_scanner()
        self._create_repo({"biome.json": "{}"})
        linters = mod.detect_linter(self.tmpdir)
        self.assertIn("biome", linters)

    def test_detect_formatter_prettier(self):
        mod = self._load_scanner()
        self._create_repo({".prettierrc": "{}"})
        formatters = mod.detect_formatter(self.tmpdir)
        self.assertIn("prettier", formatters)

    def test_detect_test_runner_jest(self):
        mod = self._load_scanner()
        self._create_repo({"jest.config.js": "module.exports = {};"})
        runners = mod.detect_test_runner(self.tmpdir)
        self.assertIn("jest", runners)

    def test_detect_ci_cd_github_actions(self):
        mod = self._load_scanner()
        self._create_repo({".github/workflows/ci.yml": "name: CI"})
        ci = mod.detect_ci_cd(self.tmpdir)
        self.assertIn("github_actions", ci)

    def test_detect_precommit_husky(self):
        mod = self._load_scanner()
        os.makedirs(os.path.join(self.tmpdir, ".husky"), exist_ok=True)
        hooks = mod.detect_precommit(self.tmpdir)
        self.assertIn("husky", hooks)

    def test_scan_directory_structure(self):
        mod = self._load_scanner()
        self._create_repo({
            "src/app.ts": "export default {}",
            "src/utils/helper.ts": "export const x = 1",
            "tests/app.test.ts": "test('x', () => {})",
            "README.md": "# Test",
        })
        structure = mod.scan_directory_structure(self.tmpdir)
        self.assertGreater(structure["total_files"], 0)
        self.assertIn("source", structure["by_tag"])

    def test_scan_nonexistent_dir(self):
        mod = self._load_scanner()
        result = mod.scan_repo("/nonexistent/path")
        self.assertEqual(result["scan_status"], "error")

    # --- Multi-language detection tests ---
    def test_detect_java_maven(self):
        mod = self._load_scanner()
        pom = """<project><groupId>com.test</groupId>
        <artifactId>test-app</artifactId><version>1.0.0</version></project>"""
        self._create_repo({"pom.xml": pom})
        result = mod.parse_java_build(self.tmpdir)
        self.assertEqual(result.get("build_tool"), "maven")

    def test_detect_java_gradle(self):
        mod = self._load_scanner()
        self._create_repo({"build.gradle": "plugins { id 'java' }"})
        result = mod.parse_java_build(self.tmpdir)
        self.assertEqual(result.get("build_tool"), "gradle")

    def test_detect_python_project(self):
        mod = self._load_scanner()
        pyproject = '[project]\nname = "test-app"\nversion = "1.0.0"\n[tool.pytest.ini_options]\n'
        self._create_repo({"pyproject.toml": pyproject})
        result = mod.parse_python_project(self.tmpdir)
        self.assertEqual(result.get("name"), "test-app")

    def test_detect_dotnet_project(self):
        mod = self._load_scanner()
        csproj = '<Project Sdk="Microsoft.NET.Sdk.Web"><PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup></Project>'
        self._create_repo({"MyApp.csproj": csproj})
        result = mod.parse_dotnet_project(self.tmpdir)
        self.assertEqual(result.get("target_framework"), "net8.0")

    def test_detect_go_module(self):
        mod = self._load_scanner()
        gomod = "module github.com/test/app\n\ngo 1.22\n"
        self._create_repo({"go.mod": gomod})
        result = mod.parse_go_module(self.tmpdir)
        self.assertEqual(result.get("module"), "github.com/test/app")

    def test_detect_rust_cargo(self):
        mod = self._load_scanner()
        cargo = '[package]\nname = "test-app"\nversion = "0.1.0"\nedition = "2021"\n'
        self._create_repo({"Cargo.toml": cargo})
        result = mod.parse_rust_cargo(self.tmpdir)
        self.assertEqual(result.get("name"), "test-app")


# =============================================================================
# connector-bootstrap.py tests
# =============================================================================
class TestConnectorBootstrap(unittest.TestCase):
    """Tests for connector-bootstrap.py"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.intake_path = os.path.join(self.tmpdir, "intake-sources.md")
        self.output_root = os.path.join(self.tmpdir, "outputs", "agents-repo")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _load_connector_bootstrap(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "connector_bootstrap",
            os.path.join(SCRIPTS_DIR, "connector-bootstrap.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def _write_intake(self, content: str):
        with open(self.intake_path, "w", encoding="utf-8") as f:
            f.write(content)

    def test_generate_creates_mcp_and_api_artifacts(self):
        mod = self._load_connector_bootstrap()
        self._write_intake(
            """# Client Intake
- PM/Requirements System: Jira
- PM Tool URL: https://myorg.atlassian.net
- PM Integration Mode: mcp
- SCM System: github
- SCM Integration Mode: api
- Confluence URL: https://myorg.atlassian.net/wiki
"""
        )

        result = mod.generate_artifacts(Path(self.intake_path), Path(self.output_root))

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["mcp_generated"])
        self.assertGreaterEqual(len(result["skills"]), 2)
        self.assertGreaterEqual(len(result["implementations"]), 1)

        mcp_path = os.path.join(self.output_root, ".mcp.json")
        self.assertTrue(os.path.exists(mcp_path))
        with open(mcp_path, "r", encoding="utf-8") as f:
            mcp_json = json.load(f)
        self.assertIn("mcpServers", mcp_json)
        self.assertGreater(len(mcp_json["mcpServers"].keys()), 0)

        inv_path = os.path.join(self.tmpdir, ".github", "sdlc-pipeline", "connector_inventory.json")
        self.assertTrue(os.path.exists(inv_path))

        cfg_path = os.path.join(self.tmpdir, ".github", "sdlc-pipeline", "connector_config.md")
        self.assertTrue(os.path.exists(cfg_path))

        api_skill_dir = Path(self.output_root) / ".github" / "skills" / "github-connector"
        self.assertTrue((api_skill_dir / "SKILL.md").exists())
        self.assertTrue((api_skill_dir / "README.md").exists())
        self.assertTrue((api_skill_dir / "package.json").exists())
        self.assertTrue((api_skill_dir / "config.js").exists())
        self.assertTrue((api_skill_dir / "index.js").exists())
        self.assertTrue((api_skill_dir / ".gitignore").exists())

        root_api_skill_dir = Path(self.tmpdir) / ".github" / "skills" / "github-connector"
        self.assertTrue((root_api_skill_dir / "SKILL.md").exists())
        self.assertTrue((root_api_skill_dir / "README.md").exists())
        self.assertTrue((root_api_skill_dir / "package.json").exists())
        self.assertTrue((root_api_skill_dir / "config.js").exists())
        self.assertTrue((root_api_skill_dir / "index.js").exists())
        self.assertTrue((root_api_skill_dir / ".gitignore").exists())

        self.assertTrue((Path(self.tmpdir) / ".env").exists())
        self.assertTrue((Path(self.tmpdir) / ".env.encrypted").exists())

    def test_parse_intake_markdown_extracts_modes(self):
        mod = self._load_connector_bootstrap()
        self._write_intake(
            """## SDLC Tools
- PM/Requirements System: Linear
- PM Tool URL: https://linear.app/acme
- PM Integration Mode: api
- SCM System: gitlab
- SCM Integration Mode: mcp
- Confluence URL: https://acme.atlassian.net/wiki
"""
        )

        values = mod.parse_intake_markdown(Path(self.intake_path))
        self.assertEqual(values["pm_system"], "Linear")
        self.assertEqual(values["pm_mode"], "api")
        self.assertEqual(values["scm_system"], "gitlab")
        self.assertEqual(values["scm_mode"], "mcp")

    def test_resolve_connectors_deduplicates(self):
        mod = self._load_connector_bootstrap()
        values = {
            "pm_system": "Jira",
            "pm_url": "https://myorg.atlassian.net",
            "pm_mode": "mcp",
            "scm_system": "github",
            "scm_mode": "mcp",
            "confluence_url": "https://myorg.atlassian.net/wiki",
        }
        specs = mod.resolve_connectors(values)
        pairs = {(s.platform, s.category) for s in specs}
        self.assertIn(("jira", "pm"), pairs)
        self.assertIn(("confluence", "knowledge"), pairs)
        self.assertIn(("github", "scm"), pairs)

    def test_verify_auth_normalizes_api_suffixed_platform_names(self):
        mod = self._load_connector_bootstrap()
        self._write_intake(
            """# Client Intake
- PM/Requirements System: Jira API
- PM Tool URL: https://myorg.atlassian.net
- PM Integration Mode: api
- SCM System: gitlab api
- SCM Integration Mode: api
"""
        )

        mod.generate_artifacts(Path(self.intake_path), Path(self.output_root))
        result = mod.verify_auth(Path(self.output_root))

        self.assertEqual(result["status"], "blocked")
        missing = {item["required_env"] for item in result["api_missing_tokens"]}
        self.assertIn("JIRA_TOKEN_ENC", missing)
        self.assertIn("GITLAB_TOKEN_ENC", missing)
        self.assertNotIn("JIRA_API_TOKEN_ENC", missing)
        self.assertNotIn("GITLAB_API_TOKEN_ENC", missing)

    def test_verify_auth_canonicalizes_legacy_inventory_platform_names(self):
        mod = self._load_connector_bootstrap()
        pipeline_dir = Path(self.tmpdir) / ".github" / "sdlc-pipeline"
        pipeline_dir.mkdir(parents=True, exist_ok=True)
        inventory_path = pipeline_dir / "connector_inventory.json"
        inventory_path.write_text(
            json.dumps(
                {
                    "generated_by": "test",
                    "source": "intake",
                    "connectors": [
                        {
                            "platform": "jira api",
                            "category": "pm",
                            "mode": "api",
                            "auth": "token",
                            "endpoint": "https://myorg.atlassian.net",
                        },
                        {
                            "platform": "gitlab api",
                            "category": "scm",
                            "mode": "api",
                            "auth": "token",
                            "endpoint": "https://gitlab.com/api/v4",
                        },
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        result = mod.verify_auth(Path(self.output_root))
        missing = {item["required_env"] for item in result["api_missing_tokens"]}
        self.assertIn("JIRA_TOKEN_ENC", missing)
        self.assertIn("GITLAB_TOKEN_ENC", missing)
        self.assertNotIn("JIRA_API_TOKEN_ENC", missing)
        self.assertNotIn("GITLAB_API_TOKEN_ENC", missing)

    def test_verify_auth_blocks_when_api_token_missing(self):
        mod = self._load_connector_bootstrap()
        self._write_intake(
            """# Client Intake
- PM/Requirements System: Jira
- PM Tool URL: https://myorg.atlassian.net
- PM Integration Mode: api
- SCM System: gitlab
- SCM Integration Mode: api
"""
        )

        mod.generate_artifacts(Path(self.intake_path), Path(self.output_root))
        result = mod.verify_auth(Path(self.output_root))

        self.assertEqual(result["status"], "blocked")
        missing = {item["required_env"] for item in result["api_missing_tokens"]}
        self.assertIn("JIRA_TOKEN_ENC", missing)
        self.assertIn("GITLAB_TOKEN_ENC", missing)

    def test_verify_auth_passes_when_api_tokens_present(self):
        mod = self._load_connector_bootstrap()
        self._write_intake(
            """# Client Intake
- PM/Requirements System: Jira
- PM Tool URL: https://myorg.atlassian.net
- PM Integration Mode: api
- SCM System: gitlab
- SCM Integration Mode: api
"""
        )

        mod.generate_artifacts(Path(self.intake_path), Path(self.output_root))
        mod._upsert_env_file(Path(self.tmpdir) / ".env.encrypted", "JIRA_TOKEN_ENC", "enc-jira")
        mod._upsert_env_file(Path(self.tmpdir) / ".env.encrypted", "GITLAB_TOKEN_ENC", "enc-gitlab")

        result = mod.verify_auth(Path(self.output_root))

        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["blocked"])

    def test_verify_auth_allows_dotenv_fallback_when_enabled(self):
        mod = self._load_connector_bootstrap()
        self._write_intake(
            """# Client Intake
- PM/Requirements System: Jira
- PM Tool URL: https://myorg.atlassian.net
- PM Integration Mode: api
- SCM System: gitlab
- SCM Integration Mode: api
"""
        )

        mod.generate_artifacts(Path(self.intake_path), Path(self.output_root))
        dotenv_path = Path(self.tmpdir) / ".env"
        dotenv_path.parent.mkdir(parents=True, exist_ok=True)
        dotenv_path.write_text("JIRA_TOKEN=jira-plain\nGITLAB_TOKEN=gitlab-plain\n", encoding="utf-8")

        result = mod.verify_auth(Path(self.output_root), allow_dotenv_fallback=True)

        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["blocked"])
        self.assertEqual(result["summary"]["api_satisfied_via_dotenv"], 2)

    def test_verify_auth_blocks_without_dotenv_fallback(self):
        mod = self._load_connector_bootstrap()
        self._write_intake(
            """# Client Intake
- PM/Requirements System: Jira
- PM Tool URL: https://myorg.atlassian.net
- PM Integration Mode: api
- SCM System: gitlab
- SCM Integration Mode: api
"""
        )

        mod.generate_artifacts(Path(self.intake_path), Path(self.output_root))
        dotenv_path = Path(self.tmpdir) / ".env"
        dotenv_path.parent.mkdir(parents=True, exist_ok=True)
        dotenv_path.write_text("JIRA_TOKEN=jira-plain\nGITLAB_TOKEN=gitlab-plain\n", encoding="utf-8")

        result = mod.verify_auth(Path(self.output_root), allow_dotenv_fallback=False)

        self.assertEqual(result["status"], "blocked")
        self.assertTrue(result["blocked"])

    def test_verify_auth_require_dotenv_tokens_blocks_then_passes(self):
        mod = self._load_connector_bootstrap()
        self._write_intake(
            """# Client Intake
- PM/Requirements System: Jira
- PM Tool URL: https://myorg.atlassian.net
- PM Integration Mode: api
- SCM System: gitlab
- SCM Integration Mode: api
"""
        )

        mod.generate_artifacts(Path(self.intake_path), Path(self.output_root))
        mod._upsert_env_file(Path(self.tmpdir) / ".env.encrypted", "JIRA_TOKEN_ENC", "enc-jira")
        mod._upsert_env_file(Path(self.tmpdir) / ".env.encrypted", "GITLAB_TOKEN_ENC", "enc-gitlab")

        blocked = mod.verify_auth(Path(self.output_root), require_dotenv_tokens=True)
        self.assertEqual(blocked["status"], "blocked")
        self.assertTrue(blocked["blocked"])
        self.assertEqual(blocked["summary"]["api_missing_dotenv_tokens"], 2)

        dotenv_path = Path(self.tmpdir) / ".env"
        dotenv_path.parent.mkdir(parents=True, exist_ok=True)
        dotenv_path.write_text("JIRA_TOKEN=jira-plain\nGITLAB_TOKEN=gitlab-plain\n", encoding="utf-8")

        ok = mod.verify_auth(Path(self.output_root), require_dotenv_tokens=True)
        self.assertEqual(ok["status"], "ok")
        self.assertFalse(ok["blocked"])
        self.assertEqual(ok["summary"]["api_missing_dotenv_tokens"], 0)

    def test_verify_auth_detects_mcp_oauth_and_token_placeholders(self):
        mod = self._load_connector_bootstrap()
        self._write_intake(
            """# Client Intake
- PM/Requirements System: Jira
- PM Tool URL: https://myorg.atlassian.net
- PM Integration Mode: mcp
- SCM System: github
- SCM Integration Mode: mcp
- Confluence URL: https://myorg.atlassian.net/wiki
- Confluence Integration Mode: mcp
"""
        )

        mod.generate_artifacts(Path(self.intake_path), Path(self.output_root))
        result = mod.verify_auth(Path(self.output_root))

        self.assertEqual(result["status"], "blocked")
        self.assertIn("github", result["mcp_oauth_pending"])
        self.assertEqual(result["summary"]["mcp_oauth_completed"], 0)
        platforms = {item["platform"] for item in result["mcp_token_pending"]}
        self.assertIn("jira", platforms)
        self.assertIn("confluence", platforms)

    def test_mark_oauth_complete_removes_oauth_pending(self):
        mod = self._load_connector_bootstrap()
        self._write_intake(
            """# Client Intake
- PM/Requirements System: Jira
- PM Tool URL: https://myorg.atlassian.net
- PM Integration Mode: mcp
- SCM System: github
- SCM Integration Mode: mcp
"""
        )

        mod.generate_artifacts(Path(self.intake_path), Path(self.output_root))
        before = mod.verify_auth(Path(self.output_root))
        self.assertIn("github", before["mcp_oauth_pending"])

        mark_result = mod.mark_oauth_complete("github", Path(self.output_root))
        self.assertEqual(mark_result["status"], "ok")

        after = mod.verify_auth(Path(self.output_root))
        self.assertNotIn("github", after["mcp_oauth_pending"])
        completed = {item["platform"] for item in after["mcp_oauth_completed"]}
        self.assertIn("github", completed)
        self.assertEqual(after["summary"]["mcp_oauth_completed"], 1)

    def test_generate_and_verify_mixed_modes(self):
        mod = self._load_connector_bootstrap()
        self._write_intake(
            """# Client Intake
- PM/Requirements System: Jira
- PM Tool URL: https://myorg.atlassian.net
- PM Integration Mode: api
- SCM System: gitlab
- SCM Integration Mode: mcp
"""
        )

        mod.generate_artifacts(Path(self.intake_path), Path(self.output_root))
        mod._upsert_env_file(Path(self.tmpdir) / ".env.encrypted", "JIRA_TOKEN_ENC", "enc-jira")

        result = mod.verify_auth(Path(self.output_root))

        self.assertTrue(result["blocked"])
        self.assertEqual(len(result["api_missing_tokens"]), 0)
        self.assertGreaterEqual(len(result["mcp_token_pending"]), 1)

    def test_generate_prunes_stale_connector_artifacts(self):
        mod = self._load_connector_bootstrap()
        self._write_intake(
            """# Client Intake
- PM/Requirements System: Jira
- PM Tool URL: https://myorg.atlassian.net
- PM Integration Mode: api
- SCM System: gitlab
- SCM Integration Mode: api
"""
        )

        # Seed stale artifacts from an older run.
        stale_skill = Path(self.output_root) / ".github" / "skills" / "other-connector" / "SKILL.md"
        stale_impl = Path(self.output_root) / ".github" / "connectors" / "other_api_connector.py"
        stale_mcp_json = Path(self.output_root) / ".mcp.json"
        stale_mcp_auth = Path(self.output_root) / ".github" / "sdlc-pipeline" / "mcp_auth_instructions.md"
        stale_skill.parent.mkdir(parents=True, exist_ok=True)
        stale_impl.parent.mkdir(parents=True, exist_ok=True)
        stale_mcp_auth.parent.mkdir(parents=True, exist_ok=True)
        stale_skill.write_text("stale", encoding="utf-8")
        stale_impl.write_text("stale", encoding="utf-8")
        stale_mcp_json.write_text("{}", encoding="utf-8")
        stale_mcp_auth.write_text("stale", encoding="utf-8")

        mod.generate_artifacts(Path(self.intake_path), Path(self.output_root))

        self.assertFalse(stale_skill.exists())
        self.assertFalse(stale_impl.exists())
        self.assertFalse(stale_mcp_json.exists())
        self.assertFalse(stale_mcp_auth.exists())

    def test_generate_artifacts_writes_env_template_with_required_tokens(self):
        mod = self._load_connector_bootstrap()
        self._write_intake(
            """# Client Intake
- PM/Requirements System: Jira
- PM Tool URL: https://myorg.atlassian.net
- PM Integration Mode: api
- SCM System: gitlab
- SCM Integration Mode: api
"""
        )

        mod.generate_artifacts(Path(self.intake_path), Path(self.output_root))
        env_template = Path(self.output_root) / ".env.template"

        self.assertTrue(env_template.exists())
        content = env_template.read_text(encoding="utf-8")
        self.assertIn("JIRA_TOKEN=", content)
        self.assertIn("GITLAB_TOKEN=", content)
        self.assertNotIn("JIRA_TOKEN_ENC=", content)
        self.assertNotIn("GITLAB_TOKEN_ENC=", content)

    def test_generate_artifacts_does_not_create_legacy_connectors_dir(self):
        mod = self._load_connector_bootstrap()
        self._write_intake(
            """# Client Intake
- PM/Requirements System: Jira
- PM Tool URL: https://myorg.atlassian.net
- PM Integration Mode: api
- SCM System: gitlab
- SCM Integration Mode: api
"""
        )

        mod.generate_artifacts(Path(self.intake_path), Path(self.output_root))
        connectors_dir = Path(self.output_root) / ".github" / "connectors"
        self.assertFalse(connectors_dir.exists())

    def test_verify_auth_missing_dotenv_includes_copy_env_template_remediation(self):
        mod = self._load_connector_bootstrap()
        self._write_intake(
            """# Client Intake
- PM/Requirements System: Jira
- PM Tool URL: https://myorg.atlassian.net
- PM Integration Mode: api
- SCM System: gitlab
- SCM Integration Mode: api
"""
        )

        mod.generate_artifacts(Path(self.intake_path), Path(self.output_root))
        mod._upsert_env_file(Path(self.tmpdir) / ".env.encrypted", "JIRA_TOKEN_ENC", "enc-jira")
        mod._upsert_env_file(Path(self.tmpdir) / ".env.encrypted", "GITLAB_TOKEN_ENC", "enc-gitlab")

        result = mod.verify_auth(Path(self.output_root), require_dotenv_tokens=True)
        remediation = result.get("remediation", {})

        self.assertEqual(result["status"], "blocked")
        self.assertIn("copy .env.template", " ".join(remediation.get("steps", [])).lower())
        self.assertIn("re-run start <issue_id>", " ".join(remediation.get("steps", [])).lower())
        self.assertEqual(remediation.get("copy_commands", {}).get("powershell"), "Copy-Item .env.template .env")
        self.assertEqual(remediation.get("copy_commands", {}).get("bash"), "cp .env.template .env")

    def test_generate_with_pm_other_name_uses_custom_platform_name(self):
        mod = self._load_connector_bootstrap()
        self._write_intake(
            """# Client Intake
- PM/Requirements System: Other
- PM/Requirements Name: GitLab
- PM Tool URL: https://custom.pm.example/api
- PM Integration Mode: api
- SCM System: gitlab
- SCM Integration Mode: api
"""
        )

        mod.generate_artifacts(Path(self.intake_path), Path(self.output_root))
        result = mod.verify_auth(Path(self.output_root))

        missing = {item["required_env"] for item in result["api_missing_tokens"]}
        self.assertIn("GITLAB_TOKEN_ENC", missing)

    def test_resolve_connectors_skips_pm_none(self):
        mod = self._load_connector_bootstrap()
        values = {
            "pm_system": "None",
            "pm_url": "https://should-not-be-used.example",
            "pm_mode": "api",
            "scm_system": "gitlab",
            "scm_mode": "api",
            "confluence_url": "",
        }

        specs = mod.resolve_connectors(values)
        platforms = {s.platform for s in specs}
        self.assertNotIn("none", platforms)
        self.assertNotIn("", platforms)
        self.assertIn("gitlab", platforms)

    def test_generate_with_pm_other_uses_other_token_env(self):
        mod = self._load_connector_bootstrap()
        self._write_intake(
            """# Client Intake
- PM/Requirements System: Other
- PM Tool URL: https://custom.pm.example/api
- PM Integration Mode: api
- SCM System: gitlab
- SCM Integration Mode: api
"""
        )

        mod.generate_artifacts(Path(self.intake_path), Path(self.output_root))
        result = mod.verify_auth(Path(self.output_root))

        missing = {item["required_env"] for item in result["api_missing_tokens"]}
        self.assertIn("OTHER_TOKEN_ENC", missing)
        self.assertIn("GITLAB_TOKEN_ENC", missing)

    def test_verify_auth_from_agents_repo_context_uses_local_env(self):
        mod = self._load_connector_bootstrap()
        self._write_intake(
            """# Client Intake
- PM/Requirements System: Jira
- PM Tool URL: https://myorg.atlassian.net
- PM Integration Mode: api
"""
        )

        mod.generate_artifacts(Path(self.intake_path), Path(self.output_root))
        local_env_encrypted = Path(self.output_root) / ".env.encrypted"
        mod._upsert_env_file(local_env_encrypted, "JIRA_TOKEN_ENC", "enc-jira")

        with patch.object(mod.Path, "cwd", return_value=Path(self.output_root)):
            result = mod.verify_auth(Path("."), allow_dotenv_fallback=False)

        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["blocked"])

    def test_api_auth_instructions_dedupe_duplicate_platform_blocks(self):
        mod = self._load_connector_bootstrap()
        connectors = [
            mod.ConnectorSpec("gitlab", "pm", "api", "token", "https://gitlab.example/api/v4"),
            mod.ConnectorSpec("gitlab", "scm", "api", "token", "https://gitlab.example/api/v4"),
        ]

        rendered = mod._render_api_auth_instructions(connectors)
        self.assertEqual(rendered.count("- gitlab:"), 1)


# =============================================================================
# instructions-generator.py tests
# =============================================================================
class TestInstructionsGenerator(unittest.TestCase):
    """Tests for instructions-generator.py"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _load_generator(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "instructions_generator",
            os.path.join(SCRIPTS_DIR, "instructions-generator.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_generate_instructions_basic(self):
        mod = self._load_generator()
        scan = {
            "repo_name": "test-repo",
            "structure": {"total_files": 42, "top_level_dirs": ["src", "tests"], "by_tag": {
                "source": {"count": 30, "sample_files": ["src/app.ts"]},
                "test": {"count": 10, "sample_files": ["tests/app.test.ts"]},
            }},
            "package_info": {
                "name": "test-repo",
                "version": "1.0.0",
                "detected_frameworks": ["React", "Next.js"],
                "dependencies": ["react", "next"],
                "scripts": {"test": "jest", "build": "next build"},
            },
            "typescript": {"strict": True},
            "linters": {"eslint": ".eslintrc.json"},
            "formatters": {"prettier": ".prettierrc"},
            "test_runners": {"jest": "jest.config.js"},
            "lock_files": {"pnpm-lock.yaml": "pnpm"},
            "ci_cd": {},
            "precommit_hooks": {},
            "patterns": [],
        }
        result = mod.generate_instructions(scan)
        self.assertIn("test-repo", result)
        self.assertIn("applyTo:", result)
        self.assertIn("React", result)
        self.assertIn("eslint", result)

    def test_generate_instructions_empty_scan(self):
        mod = self._load_generator()
        scan = {
            "repo_name": "empty-repo",
            "structure": {"total_files": 0, "top_level_dirs": [], "by_tag": {}},
            "package_info": {},
            "typescript": {},
            "linters": {},
            "formatters": {},
            "test_runners": {},
            "lock_files": {},
            "ci_cd": {},
            "precommit_hooks": {},
            "patterns": [],
        }
        result = mod.generate_instructions(scan)
        self.assertIn("empty-repo", result)
        self.assertIn("applyTo:", result)

    def test_generate_instructions_to_file(self):
        mod = self._load_generator()
        scan = {
            "repo_name": "file-test",
            "structure": {"total_files": 1, "top_level_dirs": [], "by_tag": {}},
            "package_info": {},
            "typescript": {},
            "linters": {},
            "formatters": {},
            "test_runners": {},
            "lock_files": {},
            "ci_cd": {},
            "precommit_hooks": {},
            "patterns": [],
        }
        output_dir = os.path.join(self.tmpdir, "instructions")
        os.makedirs(output_dir)
        content = mod.generate_instructions(scan)
        out_path = os.path.join(output_dir, "file-test.instructions.md")
        with open(out_path, "w") as f:
            f.write(content)
        self.assertTrue(os.path.exists(out_path))
        with open(out_path) as f:
            self.assertIn("file-test", f.read())


# =============================================================================
# workspace-bootstrap.py tests
# =============================================================================
class TestWorkspaceBootstrap(unittest.TestCase):
    """Tests for workspace-bootstrap.py"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _load_workspace_bootstrap(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "workspace_bootstrap",
            os.path.join(SCRIPTS_DIR, "workspace-bootstrap.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_add_submodules_recursive_failure_is_warning(self):
        mod = self._load_workspace_bootstrap()
        agents_repo = Path(self.tmpdir) / "agents-repo"
        repos_dir = agents_repo / "repos"
        agents_repo.mkdir(parents=True, exist_ok=True)

        repos = [{"name": "repo-a", "url": "https://example.com/repo-a.git"}]
        calls = []

        def fake_run_git(args, cwd=None):
            calls.append(args)
            if args[:3] == ["submodule", "add", "https://example.com/repo-a.git"]:
                (agents_repo / "repos" / "repo-a").mkdir(parents=True, exist_ok=True)
                return subprocess.CompletedProcess(["git", *args], 0, stdout="", stderr="")
            if args == ["submodule", "update", "--init", "--jobs", "4"]:
                return subprocess.CompletedProcess(["git", *args], 0, stdout="", stderr="")
            if args == ["submodule", "update", "--init", "--recursive", "--jobs", "4"]:
                return subprocess.CompletedProcess(["git", *args], 1, stdout="", stderr="nested submodule auth failed")
            return subprocess.CompletedProcess(["git", *args], 0, stdout="", stderr="")

        with patch.object(mod, "run_git", side_effect=fake_run_git):
            result = mod.add_submodules(agents_repo, repos_dir, repos)

        self.assertIn(["submodule", "update", "--init", "--jobs", "4"], calls)
        self.assertIn(["submodule", "update", "--init", "--recursive", "--jobs", "4"], calls)
        warning_rows = [row for row in result if row.get("name") == "_submodule_recursive"]
        self.assertEqual(len(warning_rows), 1)
        self.assertEqual(warning_rows[0]["status"], "warning")
        init_errors = [row for row in result if row.get("name") == "_submodule_init" and row.get("status") == "error"]
        self.assertEqual(init_errors, [])

    def test_add_submodules_non_recursive_failure_is_error(self):
        mod = self._load_workspace_bootstrap()
        agents_repo = Path(self.tmpdir) / "agents-repo"
        repos_dir = agents_repo / "repos"
        agents_repo.mkdir(parents=True, exist_ok=True)

        repos = []

        def fake_run_git(args, cwd=None):
            if args == ["submodule", "update", "--init", "--jobs", "4"]:
                return subprocess.CompletedProcess(["git", *args], 1, stdout="", stderr="init failed")
            return subprocess.CompletedProcess(["git", *args], 0, stdout="", stderr="")

        with patch.object(mod, "run_git", side_effect=fake_run_git):
            result = mod.add_submodules(agents_repo, repos_dir, repos)

        init_errors = [row for row in result if row.get("name") == "_submodule_init"]
        self.assertEqual(len(init_errors), 1)
        self.assertEqual(init_errors[0]["status"], "error")


# =============================================================================
# outcome-inspector.py tests
# =============================================================================
class TestOutcomeInspector(unittest.TestCase):
    """Tests for outcome-inspector.py"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _load_inspector(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "outcome_inspector",
            os.path.join(SCRIPTS_DIR, "outcome-inspector.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_inspector_creation(self):
        mod = self._load_inspector()
        inspector = mod.Inspector()
        self.assertEqual(len(inspector.findings), 0)
        self.assertFalse(inspector.has_errors())

    def test_inspector_error_tracking(self):
        mod = self._load_inspector()
        inspector = mod.Inspector()
        inspector.error("test", "Something broke", "file.md")
        self.assertTrue(inspector.has_errors())
        report = inspector.report()
        self.assertEqual(report["errors"], 1)
        self.assertEqual(report["status"], "fail")

    def test_inspector_warning_tracking(self):
        mod = self._load_inspector()
        inspector = mod.Inspector()
        inspector.warning("test", "Something suspicious")
        self.assertTrue(inspector.has_warnings())
        self.assertFalse(inspector.has_errors())
        report = inspector.report()
        self.assertEqual(report["warnings"], 1)
        self.assertEqual(report["status"], "warn")

    def test_inspector_markdown_report(self):
        mod = self._load_inspector()
        inspector = mod.Inspector()
        inspector.error("quality", "Empty file", "agent.md")
        inspector.warning("structure", "Missing section", "hook.py")
        report = inspector.report_markdown()
        self.assertIn("FAIL", report)
        self.assertIn("Empty file", report)
        self.assertIn("Missing section", report)

    def test_inspect_preflight_missing_files(self):
        mod = self._load_inspector()
        inspector = mod.Inspector()
        mod.inspect_preflight(self.tmpdir, inspector)
        self.assertTrue(inspector.has_errors())
        messages = [f["message"] for f in inspector.findings]
        self.assertTrue(any("setup.sh" in m for m in messages))

    def test_inspect_generator_no_agents_dir(self):
        mod = self._load_inspector()
        inspector = mod.Inspector()
        mod.inspect_generator(self.tmpdir, "", inspector)
        self.assertTrue(inspector.has_errors())

    def test_inspect_generator_with_agents(self):
        mod = self._load_inspector()
        agents_dir = os.path.join(self.tmpdir, ".github", "agents")
        os.makedirs(agents_dir)
        # Create a minimal agent file
        agent_content = '---\nname: "Test Agent"\nmodel: "test-model"\n---\n# Test Agent\n## Prime Directive\n> "Test"\n## Behavioral Guardrails\nTest\n## Custom Client Context\nTest\n## Quality Checklist\n- [ ] Test'
        with open(os.path.join(agents_dir, "test_agent.md"), "w") as f:
            f.write(agent_content)
        inspector = mod.Inspector()
        mod.inspect_generator(self.tmpdir, "", inspector)
        # Should not have "no agents dir" error
        errors = [f for f in inspector.findings if "No .github/agents" in f.get("message", "")]
        self.assertEqual(len(errors), 0)

    def test_inspect_instructions_missing_dir(self):
        mod = self._load_inspector()
        inspector = mod.Inspector()
        mod.inspect_instructions("/nonexistent", inspector)
        self.assertTrue(inspector.has_errors())

    def test_inspect_instructions_valid(self):
        mod = self._load_inspector()
        idir = os.path.join(self.tmpdir, "instructions")
        os.makedirs(idir)
        content = "---\napplyTo: \"test/**\"\n---\n# Repository Instructions\n## Repository Structure\nstuff\n## Dependencies\nstuff\n## Tools & Technologies\nstuff\n" + ("x" * 200)
        with open(os.path.join(idir, "test.instructions.md"), "w") as f:
            f.write(content)
        inspector = mod.Inspector()
        mod.inspect_instructions(idir, inspector)
        self.assertFalse(inspector.has_errors())


# =============================================================================
# pipeline-migrator.py tests
# =============================================================================
class TestPipelineMigrator(unittest.TestCase):
    """Tests for pipeline-migrator.py"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.contracts_dir = os.path.join(self.tmpdir, "contracts")
        self.agents_dir = os.path.join(self.tmpdir, "agents")
        os.makedirs(self.contracts_dir)
        os.makedirs(self.agents_dir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _load_migrator(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "pipeline_migrator",
            os.path.join(SCRIPTS_DIR, "pipeline-migrator.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_extract_contract_metadata(self):
        mod = self._load_migrator()
        content = '| contract_id | AC-001 |\n| agent_name | Test Agent |\n| version | 1.0.0 |\n| model_tier | reasoning |\n\n> "Do the thing."\n\n1. **[OUTCOME-TEST]** — Test outcome'
        meta = mod.extract_contract_metadata(content)
        self.assertEqual(meta["contract_id"], "AC-001")
        self.assertEqual(meta["agent_name"], "Test Agent")
        self.assertEqual(meta["version"], "1.0.0")
        self.assertEqual(meta["prime_directive"], "Do the thing.")
        self.assertIn("TEST", meta["outcomes"])

    def test_compare_versions(self):
        mod = self._load_migrator()
        self.assertEqual(mod.compare_versions("1.0.0", "1.0.0"), "match")
        self.assertEqual(mod.compare_versions("2.0.0", "1.0.0"), "behind")
        self.assertEqual(mod.compare_versions("1.0.0", "2.0.0"), "ahead")
        self.assertEqual(mod.compare_versions("bad", "1.0.0"), "unknown")

    def test_check_drift_missing_agent(self):
        mod = self._load_migrator()
        contract = '| contract_id | AC-099 |\n| agent_name | Missing Agent |\n| version | 1.0.0 |\n\n> "Do stuff."'
        with open(os.path.join(self.contracts_dir, "test.contract.md"), "w") as f:
            f.write(contract)
        findings = mod.check_drift(self.contracts_dir, self.agents_dir)
        self.assertTrue(any(f["type"] == "missing_agent" for f in findings))

    def test_check_drift_no_drift(self):
        mod = self._load_migrator()
        # Empty dirs = no contracts to compare
        findings = mod.check_drift(self.contracts_dir, self.agents_dir)
        self.assertEqual(len(findings), 0)

    def test_generate_plan(self):
        mod = self._load_migrator()
        findings = [{"severity": "warning", "type": "missing_agent", "contract_id": "AC-099", "agent_name": "Test", "message": "No agent"}]
        plan = mod.generate_plan(findings, self.contracts_dir, self.agents_dir)
        self.assertEqual(len(plan["actions"]), 1)
        self.assertEqual(plan["actions"][0]["action"], "create")

    def test_format_plan_markdown(self):
        mod = self._load_migrator()
        plan = {
            "generated_at": "2026-01-01T00:00:00Z",
            "contracts_dir": "contracts",
            "agents_dir": "agents",
            "total_findings": 1,
            "actions": [{"action": "create", "agent_name": "Test", "reason": "Missing"}],
            "summary": {"agents_to_create": ["Test"], "agents_to_regenerate": [], "agents_to_update": []},
        }
        md = mod.format_plan_markdown(plan)
        self.assertIn("Migration Plan", md)
        self.assertIn("Test", md)


if __name__ == "__main__":
    unittest.main()
