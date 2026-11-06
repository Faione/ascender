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
        self.env = dict(os.environ, PATH=str(binary) + os.pathsep + os.environ["PATH"],
                        MOCK_LOG=str(self.path / "docker.log"), MOCK_TARGET="simulation",
                        LOCAL_UID="9999", LOCAL_GID="9999", LOCAL_USER="ambient",
                        ASCEND_IMAGE="wrong:image", IDENTITY_DIR="wrong-path", CODE_DIR="wrong-path")
        for key in ("MOCK_CP_FAIL", "MOCK_PASSWD", "MOCK_GROUP", "DOCKER_HOST"):
            self.env.pop(key, None)

    def run_prepare(self, *args, expected=0):
        result = subprocess.run([sys.executable, str(ROOT / "prepare_runtime.py"),
                                 "--image-ref-file", str(self.image_file), "--code-dir", str(self.code),
                                 "--output-dir", str(self.output), "--uid", "1234", "--gid", "2345", *args],
                                env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def config(self):
        return (self.output / "compose.yaml").read_text()

    def test_simulation_has_complete_settings_independent_of_environment(self):
        self.run_prepare()
        config = self.config()
        self.assertIn("image: 'ascend-dev:generated'", config)
        self.assertIn("user: '0:0'", config)
        self.assertIn("pull_policy: never", config)
        self.assertTrue(config.endswith("networks:\n  default:\n    driver: bridge\n    ipam:\n      config:\n        - subnet: '192.168.240.0/24'\n"))
        self.assertIn("target: '/etc/passwd'\n        read_only: true", config)
        self.assertIn("target: '/etc/group'\n        read_only: true", config)
        self.assertIn("source: '" + str(self.code.resolve()) + "'", config)
        self.assertNotIn("devices:", config)
        self.assertNotIn("group_add:", config)
        self.assertIsNone(re.search(r"(?<!\$)\$(?:\{|[A-Za-z_])", config))
        self.assertIn("developer:*:1234:2345:", (self.output / "identity/passwd").read_text())
        self.assertIn("root:x:0:0:root:/root:/bin/bash", (self.output / "identity/passwd").read_text())
        self.assertTrue((self.output / "home").is_dir())
        self.assertFalse((self.output / "identity/compose.env").exists())
        self.assertNotIn("env_file:", config)
        self.assertFalse(list(self.output.glob(".prepare-runtime.*")))
        for name in ("LOCAL_UID", "LOCAL_GID", "LOCAL_USER", "ASCEND_IMAGE", "IDENTITY_DIR", "CODE_DIR"):
            self.env.pop(name, None)
        self.run_prepare()
        self.assertEqual(self.config(), config)
        calls = [json.loads(line) for line in Path(self.env["MOCK_LOG"]).read_text().splitlines()]
        self.assertFalse(any(any(item in ("run", "start", "exec", "pull") for item in call[:3]) for call in calls))

    def test_cli_identity_overrides_are_normalized(self):
        self.run_prepare("--uid", "001234", "--gid", "002345", "--user", "customuser")
        self.assertIn("user: '0:0'", self.config())
        self.assertIn("customuser:*:1234:2345:", (self.output / "identity/passwd").read_text())

    def test_custom_subnet_and_invalid_networks_fail_before_docker(self):
        for subnet in ("bad", "", "192.168.240.1/24", "192.168.240.0/33", "192.168.240.0/31",
                       "192.168.240.1/32", "8.8.8.0/24", "127.0.0.0/8", "0.0.0.0/0", "fd00::/64"):
            with self.subTest(subnet=subnet):
                result = self.run_prepare("--runtime-subnet", subnet, expected=1)
                self.assertIn("--runtime-subnet", result.stderr)
        self.assertFalse(Path(self.env["MOCK_LOG"]).exists())
        self.assertFalse(self.output.exists())
        result = self.run_prepare("--runtime-subnet", "192.168.241.0/24")
        self.assertIn("subnet: '192.168.241.0/24'", self.config())
        self.assertIn("Runtime subnet: 192.168.241.0/24", result.stdout)

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
        # Generic character devices exercise path/type checks without NPU hardware.
        self.run_prepare("--device", "/dev/null", "--device", "/dev/zero",
                         "--driver-root", str(driver), "--dcmi-dir", str(dcmi), "--install-info", str(info),
                         "--group-add", "0077", "--group-add", "77", "--group-add", "88",
                         "--runtime-subnet", "10.254.240.0/24")
        config = self.config()
        self.assertIn("user: '0:0'", config)
        self.assertIn("subnet: '10.254.240.0/24'", config)
        self.assertIsNone(re.search(r"(?<!\$)\$(?:\{|[A-Za-z_])", config))
        self.assertNotIn("env_file:", config)
        self.assertIn("'/dev/null:/dev/null'", config)
        self.assertEqual(config.count("      - '77'\n"), 1)
        self.assertEqual(config.count("      - '88'\n"), 1)
        self.assertEqual(config.count(f"      - '{os.stat('/dev/null').st_gid}'\n"), 1)
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
