import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
INSTALLER = PROJECT_ROOT / "install.sh"
BASH = shutil.which("bash")
if BASH is None:
    for candidate in (
        Path("C:/Program Files/Git/bin/bash.exe"),
        Path("C:/Program Files/Git/usr/bin/bash.exe"),
    ):
        if candidate.is_file():
            BASH = str(candidate)
            break


@unittest.skipUnless(BASH, "bash is required for installer tests")
class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temporary_directory.name)
        self.fake_bin = self.temp_path / "bin"
        self.fake_bin.mkdir()
        self.os_release = self.temp_path / "os-release"
        self.os_release.write_text('ID="ubuntu"\nVERSION_ID="22.04"\n', encoding="utf-8")
        for command in ("python3", "sqlite3", "systemctl"):
            script = self.fake_bin / command
            script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            script.chmod(0o755)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def run_installer(self, *args, extra_env=None):
        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{self.fake_bin}{os.pathsep}{env.get('PATH', '')}",
                "VAST_GUARDIAN_OS_RELEASE": str(self.os_release),
                "VAST_GUARDIAN_ETC_DIR": str(self.temp_path / "etc"),
                "VAST_GUARDIAN_SYSTEMD_DIR": str(self.temp_path / "systemd"),
                "VAST_GUARDIAN_DATA_DIR": str(self.temp_path / "data"),
            }
        )
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [BASH, str(INSTALLER), *args],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )

    def test_central_dry_run_lists_all_central_units(self):
        result = self.run_installer("--role", "central", "--host-key", "central-a", "--dry-run")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("role: central", result.stdout)
        self.assertIn("vast-guardian.service, vast-guardian-web.service", result.stdout)
        self.assertIn("vast-guardian-watchdog.service/timer", result.stdout)
        self.assertIn("vast-guardian-heartbeat.service/timer", result.stdout)
        self.assertIn("DRY-RUN", result.stdout)

    def test_agent_dry_run_does_not_install_or_start_units(self):
        result = self.run_installer(
            "--role", "agent",
            "--host-key", "agent-a",
            "--central-url", "https://central.example.test/api/v1/ingest",
            "--ingest-token", "test-token",
            "--dry-run",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("agent transport is not implemented; no systemd units will be installed or started", result.stdout)
        self.assertNotIn("vast-guardian-web.service", result.stdout)
        self.assertNotIn("database: initialize", result.stdout)

    def test_agent_requires_central_parameters(self):
        result = self.run_installer("--role", "agent", "--dry-run")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Agent role requires --central-url", result.stderr)

    def test_dry_run_is_idempotent(self):
        first = self.run_installer("--role", "central", "--host-key", "central-a", "--dry-run")
        second = self.run_installer("--role", "central", "--host-key", "central-a", "--dry-run")

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(first.stdout, second.stdout)

    def test_dry_run_does_not_overwrite_existing_environment_file(self):
        environment_path = self.temp_path / "etc" / "guardian.env"
        environment_path.parent.mkdir()
        environment_path.write_text("VAST_GUARDIAN_INGEST_TOKEN=keep-me\n", encoding="utf-8")

        result = self.run_installer("--role", "central", "--dry-run")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(environment_path.read_text(encoding="utf-8"), "VAST_GUARDIAN_INGEST_TOKEN=keep-me\n")

    def test_only_central_plan_includes_database_migration(self):
        central = self.run_installer("--role", "central", "--dry-run")
        agent = self.run_installer(
            "--role", "agent",
            "--central-url", "https://central.example.test/ingest",
            "--ingest-token", "test-token",
            "--dry-run",
        )

        self.assertIn("database: initialize", central.stdout)
        self.assertNotIn("database: initialize", agent.stdout)

    def test_installer_has_no_dangerous_host_operations(self):
        contents = INSTALLER.read_text(encoding="utf-8")

        self.assertIn("set -euo pipefail", contents)
        for forbidden in (
            "apt-get upgrade",
            "do-release-upgrade",
            "restart docker",
            "restart vastai",
            "nvidia-smi -",
            "docker restart",
        ):
            self.assertNotIn(forbidden, contents)

    def test_central_service_templates_are_parameterized(self):
        for template in (
            "vast-guardian.service.in",
            "vast-guardian-web.service.in",
            "vast-guardian-watchdog.service.in",
            "vast-guardian-heartbeat.service.in",
        ):
            contents = (PROJECT_ROOT / "systemd" / template).read_text(encoding="utf-8")
            self.assertIn("@REPO_PATH@", contents)
            self.assertIn("@ENV_FILE@", contents)

    def test_bash_syntax_is_valid(self):
        result = subprocess.run([BASH, "-n", str(INSTALLER)], text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
