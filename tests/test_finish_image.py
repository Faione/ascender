"""Exercise the finishing script in a temporary tree without installing packages."""
import os
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class FinishImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ascender finish ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for path in ("etc/ascend", "etc/profile.d", "usr/local/lib/ascend", "usr/local/bin",
                     "usr/local/share/ascend", "config", "bin"):
            (self.root / path).mkdir(parents=True)
        for name in ("constraints.txt", "pip-packages.txt", "manifest.txt"):
            (self.root / "config" / name).write_text("" if name != "manifest.txt" else "fixture manifest\n")
        (self.root / "etc/ascend/cann-requirements.txt").write_text("psutil>=5.9\n")
        scripts = self.root / "usr/local/lib/ascend"
        for name in ("shell-env.sh", "entrypoint.sh"):
            (scripts / name).write_text("true\n")
        (scripts / "verify-image.sh").write_text('exit "${MOCK_VERIFY_EXIT:-0}"\n')
        python = self.root / "bin/python3"
        python.write_text(f"#!{sys.executable}\n" + '''import json, os, sys
from pathlib import Path
with Path(os.environ["MOCK_PYTHON_LOG"]).open("a") as output:
    output.write(json.dumps(sys.argv[1:]) + "\\n")
if sys.argv[1:4] == ["-m", "pip", "install"]:
    sys.exit(int(os.environ.get("MOCK_PIP_EXIT", "0")))
if len(sys.argv) == 4 and sys.argv[2] == "inventory":
    Path(sys.argv[3]).write_text("fixture inventory\\n")
''')
        python.chmod(0o755)
        self.script = self.root / "finish-image.sh"
        source = (ROOT / "scripts/finish-image.sh").read_text()
        for path in ("/etc", "/usr/local", "/tmp/config"):
            target = self.root / ("config" if path == "/tmp/config" else path.lstrip("/"))
            source = source.replace(path, shlex.quote(str(target)))
        self.script.write_text(source)

    def run_script(self, **options):
        env = dict(os.environ, PATH=str(self.root / "bin") + os.pathsep + os.environ["PATH"],
                   DEV_WORKDIR=str(self.root / "workspace"), STRICT="0", MOCK_PYTHON_LOG=str(self.root / "python.log"))
        env.update(options)
        return subprocess.run(["bash", str(self.script)], env=env, text=True, capture_output=True)

    def test_optional_checksum_report_does_not_break_finishing(self):
        for strict in (False, True):
            with self.subTest(strict=strict):
                if strict:
                    (self.root / "config/materials.sha256").write_text("fixture checksum\n")
                result = self.run_script(STRICT="1" if strict else "0")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                output = self.root / "usr/local/share/ascend"
                self.assertEqual((output / "manifest.txt").read_text(), "fixture manifest\n")
                self.assertEqual((output / "materials.sha256").exists(), strict)
                self.assertEqual((output / "installed-packages.txt").read_text(), "fixture inventory\n")

    def test_installs_only_declared_and_requested_packages(self):
        (self.root / "config/pip-packages.txt").write_text("pytest\n")
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = [json.loads(line) for line in (self.root / "python.log").read_text().splitlines()]
        install = next(call for call in calls if call[:3] == ["-m", "pip", "install"])
        for package in ("build", "pyyaml", "psutil", "numpy<2", "pytest", "dtype"):
            self.assertNotIn(package, install)
        self.assertIn(str(self.root / "etc/ascend/cann-requirements.txt"), install)
        self.assertIn(str(self.root / "config/pip-packages.txt"), install)

    def test_no_pip_install_when_both_requirement_lists_are_empty(self):
        (self.root / "etc/ascend/cann-requirements.txt").write_text("")
        result = self.run_script(MOCK_PIP_EXIT="23", MOCK_VERIFY_EXIT="19")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("Running verify-image.sh", result.stdout)
        calls = [json.loads(line) for line in (self.root / "python.log").read_text().splitlines()]
        self.assertFalse(any(call[:3] == ["-m", "pip", "install"] for call in calls))

    def test_pip_failure_reports_command_line_and_preserves_exit_code(self):
        result = self.run_script(MOCK_PIP_EXIT="23")
        self.assertEqual(result.returncode, 23)
        self.assertIn("Installing declared CANN dependencies", result.stdout)
        self.assertRegex(result.stderr, r"ERROR: .*finish-image.sh:\d+:")
        self.assertIn("python3 -m pip install", result.stderr)
        self.assertIn("(exit 23)", result.stderr)

    def test_verification_failure_reports_stage_and_preserves_exit_code(self):
        result = self.run_script(MOCK_VERIFY_EXIT="19", STRICT="1")
        self.assertEqual(result.returncode, 19)
        self.assertIn("Running verify-image.sh", result.stdout)
        self.assertIn("verify-image.sh", result.stderr)
        self.assertIn("(exit 19)", result.stderr)


if __name__ == "__main__":
    unittest.main()
