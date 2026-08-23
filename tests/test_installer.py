import os
import shutil
import sqlite3
import subprocess
import sys
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
        for command in ("python3", "systemctl"):
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
                "VAST_GUARDIAN_OS_RELEASE": self._bash_path(self.os_release),
                "VAST_GUARDIAN_ETC_DIR": self._bash_path(self.temp_path / "etc"),
                "VAST_GUARDIAN_SYSTEMD_DIR": self._bash_path(self.temp_path / "systemd"),
                "VAST_GUARDIAN_DATA_DIR": self._bash_path(self.temp_path / "data"),
            }
        )
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [BASH, str(INSTALLER), *args],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
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
        self.assertIn("import sqlite3", contents)
        self.assertNotIn("require_command sqlite3", contents)
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

    def test_real_central_install_is_idempotent_and_keeps_database_writable(self):
        if os.name == "nt":
            self.skipTest("Git Bash cannot apply POSIX permissions in the Windows sandbox")
        installation_root = self._create_bash_tempdir()
        self.addCleanup(shutil.rmtree, installation_root, ignore_errors=True)
        repository = installation_root / "repo"
        subprocess.run(
            [
                BASH,
                "-lc",
                'cp -R -- "$1" "$2"',
                "--",
                self._bash_path(PROJECT_ROOT),
                self._bash_path(repository),
            ],
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
        command_log = installation_root / "commands.log"
        self._write_fake_command(
            "id",
            """#!/usr/bin/env bash
if [[ "${1:-}" == "-u" && "${2:-}" == "vast" ]]; then
    exit 0
fi
exit 0
""",
        )
        self._write_fake_command(
            "chown",
            """#!/usr/bin/env bash
printf 'chown %s\\n' "$*" >> "$VAST_GUARDIAN_TEST_COMMAND_LOG"
exit 0
""",
        )
        self._write_fake_command(
            "systemctl",
            """#!/usr/bin/env bash
printf 'systemctl %s\\n' "$*" >> "$VAST_GUARDIAN_TEST_COMMAND_LOG"
exit 0
""",
        )
        self._write_fake_command(
            "python3",
            """#!/usr/bin/env bash
exec "$VAST_GUARDIAN_TEST_PYTHON" "$@"
""",
        )
        bash_python = self._bash_path(Path(sys.executable))
        extra_env = {
            "VAST_GUARDIAN_TEST_MODE": "1",
            "VAST_GUARDIAN_TEST_PYTHON": bash_python,
            "VAST_GUARDIAN_TEST_COMMAND_LOG": self._bash_path(command_log),
            "SUDO_USER": "vast",
        }
        arguments = ("--role", "central", "--host-key", "vastserver2")

        first = self._run_repository_installer(repository, *arguments, extra_env=extra_env)

        self.assertEqual(first.returncode, 0, first.stderr)
        database_path = repository / "database" / "vast_guardian.db"
        self.assertTrue(database_path.is_file())
        with sqlite3.connect(database_path) as connection:
            connection.execute("CREATE TABLE installation_marker(value TEXT)")
            connection.execute("INSERT INTO installation_marker VALUES ('keep')")
        environment_path = installation_root / "etc" / "guardian.env"
        environment_path.write_text(
            environment_path.read_text(encoding="utf-8")
            + "VAST_GUARDIAN_INGEST_TOKEN=keep-this-secret\\n",
            encoding="utf-8",
        )
        expected_environment = environment_path.read_text(encoding="utf-8")

        second = self._run_repository_installer(repository, *arguments, extra_env=extra_env)

        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(environment_path.read_text(encoding="utf-8"), expected_environment)
        with sqlite3.connect(database_path) as connection:
            self.assertEqual(connection.execute("SELECT value FROM installation_marker").fetchone()[0], "keep")
            connection.execute("INSERT INTO installation_marker VALUES ('collector-can-write')")
        command_output = command_log.read_text(encoding="utf-8")
        self.assertIn("chown vast", command_output)
        self.assertIn("vast_guardian.db", command_output)
        self.assertIn("User=vast", (installation_root / "systemd" / "vast-guardian.service").read_text(encoding="utf-8"))

    def _run_repository_installer(self, repository, *args, extra_env=None):
        installation_root = repository.parent
        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{self.fake_bin}{os.pathsep}{env.get('PATH', '')}",
                "VAST_GUARDIAN_OS_RELEASE": self._bash_path(self.os_release),
                "VAST_GUARDIAN_ETC_DIR": self._bash_path(installation_root / "etc"),
                "VAST_GUARDIAN_SYSTEMD_DIR": self._bash_path(installation_root / "systemd"),
                "VAST_GUARDIAN_DATA_DIR": self._bash_path(installation_root / "data"),
            }
        )
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [BASH, self._bash_path(repository / "install.sh"), *args],
            cwd=repository,
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            check=False,
        )

    def _write_fake_command(self, name, contents):
        command = self.fake_bin / name
        command.write_text(contents, encoding="utf-8")
        command.chmod(0o755)

    @staticmethod
    def _create_bash_tempdir():
        if os.name != "nt":
            return Path(tempfile.mkdtemp())
        result = subprocess.run(
            [BASH, "-lc", 'work=$(mktemp -d); cygpath -w "$work"'],
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
        return Path(result.stdout.strip())

    @staticmethod
    def _bash_path(path):
        resolved_path = Path(path).resolve()
        if os.name == "nt":
            try:
                relative_to_temp = resolved_path.relative_to(Path(tempfile.gettempdir()).resolve())
                return f"/tmp/{relative_to_temp.as_posix()}"
            except ValueError:
                pass
        drive, tail = os.path.splitdrive(str(resolved_path))
        if drive:
            return f"/{drive[0].lower()}{tail.replace(os.sep, '/')}"
        return str(path)

    def test_bash_syntax_is_valid(self):
        result = subprocess.run([BASH, "-n", str(INSTALLER)], text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
