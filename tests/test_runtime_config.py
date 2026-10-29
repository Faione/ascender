"""Runtime generation tests use Docker/device-metadata doubles; no container starts."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RuntimeConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ascend runtime ")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.code = self.path / "operator code"
        self.code.mkdir()
        self.output = self.path / "runtime"
        self.image_file = self.path / "image-ref.txt"
        self.image_file.write_text("ascend-dev:generated\n")
        binary = self.path / "bin"
        binary.mkdir()
        mock = binary / "docker"
        mock.write_text(f"#!{sys.executable}\n" + (ROOT / "tests/docker_mock.py").read_text())
        mock.chmod(0o755)
        mock_id = binary / "id"
        mock_id.write_text('#!/bin/sh\ncase "$1" in -u) echo 1234 ;; -g) echo 2345 ;; *) exit 1 ;; esac\n')
        mock_id.chmod(0o755)
        self.env = dict(os.environ, PATH=str(binary) + os.pathsep + os.environ["PATH"],
                        MOCK_LOG=str(self.path / "docker.log"), MOCK_TARGET="simulation",
                        LOCAL_UID="9999", LOCAL_GID="9999", LOCAL_USER="ambient",
                        ASCEND_IMAGE="wrong:image", IDENTITY_DIR="wrong-path", CODE_DIR="wrong-path")
        for key in ("MOCK_CP_FAIL", "MOCK_PASSWD", "MOCK_GROUP"):
            self.env.pop(key, None)

    def run_prepare(self, *args, expected=0):
        result = subprocess.run(["/bin/bash", str(ROOT / "examples/prepare-runtime.sh"),
                                 "--image-ref-file", str(self.image_file), "--code-dir", str(self.code),
                                 "--output-dir", str(self.output), *args],
                                env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def config(self):
        return (self.output / "compose.yaml").read_text()

    def test_default_simulation_has_complete_settings_without_environment(self):
        self.run_prepare()
        config = self.config()
        self.assertIn("image: 'ascend-dev:generated'", config)
        self.assertIn("user: '1234:2345'", config)
        self.assertIn("pull_policy: never", config)
        self.assertIn("target: '/etc/passwd'\n        read_only: true", config)
        self.assertIn("target: '/etc/group'\n        read_only: true", config)
        self.assertIn("source: '" + str(self.code.resolve()) + "'", config)
        self.assertNotIn("devices:", config)
        self.assertNotIn("group_add:", config)
        self.assertIsNone(re.search(r"(?<!\$)\$(?:\{|[A-Za-z_])", config))
        self.assertIn("developer:*:1234:2345:", (self.output / "identity/passwd").read_text())
        self.assertTrue((self.output / "home").is_dir())
        self.assertFalse((self.output / "identity/compose.env").exists())
        self.assertFalse(list(self.output.glob(".prepare-runtime.*")))
        calls = [json.loads(line) for line in Path(self.env["MOCK_LOG"]).read_text().splitlines()]
        self.assertFalse(any(call[0] in ("run", "start", "exec", "pull") for call in calls))

    def test_cli_identity_overrides_are_normalized(self):
        self.run_prepare("--uid", "001234", "--gid", "002345", "--user", "customuser")
        self.assertIn("user: '1234:2345'", self.config())
        self.assertIn("customuser:*:1234:2345:", (self.output / "identity/passwd").read_text())

    def test_quotes_and_literal_dollars_are_preserved_in_paths(self):
        self.code = self.path / "operator's $cash ${CODE_DIR}"
        self.code.mkdir()
        self.output = self.path / "user's $runtime"
        self.run_prepare()
        config = self.config()
        self.assertIn("operator''s $$cash $${CODE_DIR}", config)
        self.assertIn("user''s $$runtime", config)
        self.assertIsNone(re.search(r"(?<!\$)\$(?:\{|[A-Za-z_])", config))
        self.assertTrue((self.output / "identity/passwd").exists())

    def test_npu_discovers_and_deduplicates_device_groups(self):
        self.env["MOCK_TARGET"] = "npu"
        driver = self.path / "driver"
        (driver / "lib64").mkdir(parents=True)
        (driver / "version.info").write_text("fixture driver")
        dcmi = self.path / "dcmi"
        dcmi.mkdir()
        info = self.path / "ascend_install.info"
        info.write_text("fixture info")
        mock_stat = self.path / "bin/stat"
        mock_stat.write_text("#!/bin/sh\necho 77\n")
        mock_stat.chmod(0o755)
        # Generic character devices exercise path/type checks without NPU hardware.
        self.run_prepare("--device", "/dev/null", "--device", "/dev/zero",
                         "--driver-root", str(driver), "--dcmi-dir", str(dcmi), "--install-info", str(info),
                         "--group-add", "0077", "--group-add", "88")
        config = self.config()
        self.assertIn("'/dev/null:/dev/null'", config)
        self.assertEqual(config.count("      - '77'\n"), 1)
        self.assertEqual(config.count("      - '88'\n"), 1)
        self.assertIn("source: '" + str(driver.resolve()) + "/lib64'", config)
        self.assertIn("target: '/usr/local/Ascend/driver/lib64'\n        read_only: true", config)

    def test_simulation_rejects_npu_options_and_target_mismatch(self):
        self.run_prepare("--device", "/dev/null", expected=1)
        self.run_prepare("--target", "npu", expected=1)
        self.assertFalse((self.output / "compose.yaml").exists())

    def test_missing_label_requires_explicit_target(self):
        self.env["MOCK_TARGET"] = "<no value>"
        self.run_prepare(expected=1)
        self.run_prepare("--target", "simulation")

    def test_bad_reference_or_source_does_not_generate_configuration(self):
        self.image_file.write_text("one:image\ntwo:images\n")
        self.run_prepare(expected=1)
        self.image_file.write_text("ascend-dev:generated\n")
        self.run_prepare("--code-dir", str(self.path / "missing"), expected=1)
        self.assertFalse((self.output / "compose.yaml").exists())

    def test_failed_identity_refresh_preserves_existing_runtime(self):
        self.run_prepare()
        original_config = self.config()
        original_passwd = (self.output / "identity/passwd").read_bytes()
        marker = self.output / "home/preserved.txt"
        marker.write_text("keep cache/home files")
        self.env["MOCK_CP_FAIL"] = "1"
        self.run_prepare(expected=24)
        self.assertEqual(self.config(), original_config)
        self.assertEqual((self.output / "identity/passwd").read_bytes(), original_passwd)
        self.assertTrue(marker.exists())
        self.assertFalse(list(self.output.glob(".prepare-runtime.*")))


if __name__ == "__main__":
    unittest.main()
