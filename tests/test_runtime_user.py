"""Account-file generation regressions; Docker is mocked, no host /etc is edited."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RuntimeUserTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ascend identity ")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.identity = self.path / "accounts"
        binary = self.path / "bin"
        binary.mkdir()
        mock = binary / "docker"
        mock.write_text(f"#!{sys.executable}\n" + (ROOT / "tests/docker_mock.py").read_text())
        mock.chmod(0o755)
        self.env = dict(os.environ, PATH=str(binary) + os.pathsep + os.environ["PATH"],
                        ASCEND_IMAGE="ascend-dev:generated", IDENTITY_DIR=str(self.identity),
                        LOCAL_UID="1234", LOCAL_GID="2345", MOCK_LOG=str(self.path / "docker.log"))
        for key in ("LOCAL_USER", "MOCK_CP_FAIL", "MOCK_PASSWD", "MOCK_GROUP"):
            self.env.pop(key, None)

    def run_prepare(self, expected=0):
        result = subprocess.run(["/bin/bash", str(ROOT / "examples/prepare-user.sh")],
                                env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def test_new_user_has_name_home_shell_and_primary_group(self):
        self.run_prepare()
        passwd = (self.identity / "passwd").read_text()
        self.assertIn("root:x:0:0:root:/root:/bin/bash\n", passwd)
        self.assertIn("ascend-1234:*:1234:2345:Ascend developer:/workspace/home:/bin/bash\n", passwd)
        self.assertIn("ascend-2345:*:2345:ascend-1234\n", (self.identity / "group").read_text())
        calls = [json.loads(line) for line in Path(self.env["MOCK_LOG"]).read_text().splitlines()]
        self.assertTrue(any(call[0] == "rm" for call in calls))
        self.assertFalse(any(call[0] in ("run", "start", "exec", "pull") for call in calls))
        self.assertFalse(list(self.identity.glob(".prepare.*")))

    def test_existing_ids_reuse_names_and_preserve_other_accounts(self):
        self.env["MOCK_PASSWD"] = "root:x:0:0:root:/root:/bin/bash\nubuntu:x:1234:100:Ubuntu:/old-home:/bin/sh\ndaemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nologin\n"
        self.env["MOCK_GROUP"] = "root:x:0:\nproject:x:2345:existing\n"
        self.run_prepare()
        rows = [line.split(":") for line in (self.identity / "passwd").read_text().splitlines()]
        selected = [row for row in rows if row[2] == "1234"]
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0][0], "ubuntu")
        self.assertEqual(selected[0][3], "2345")
        self.assertEqual(selected[0][5], "/workspace/home")
        self.assertTrue(any(row[0] == "daemon" for row in rows))
        self.assertEqual((self.identity / "group").read_text(), self.env["MOCK_GROUP"])

    def test_explicit_name_and_leading_zero_ids(self):
        self.env.update(LOCAL_UID="001234", LOCAL_GID="002345", LOCAL_USER="developer")
        self.run_prepare()
        self.assertIn("developer:*:1234:2345:", (self.identity / "passwd").read_text())

    def test_name_collision_does_not_replace_prepared_files(self):
        self.run_prepare()
        original = (self.identity / "passwd").read_bytes()
        self.env.update(LOCAL_USER="taken", MOCK_PASSWD="root:x:0:0:root:/root:/bin/bash\ntaken:x:777:777:Other:/home/other:/bin/bash\n")
        self.assertIn("another UID", self.run_prepare(expected=1).stderr)
        self.assertEqual((self.identity / "passwd").read_bytes(), original)

    def test_invalid_identity_fails_before_docker(self):
        for key, value in (("LOCAL_UID", "0"), ("LOCAL_UID", "not-a-number"), ("LOCAL_UID", "2147483648"),
                           ("LOCAL_GID", "-1"), ("IDENTITY_DIR", "relative")):
            with self.subTest(key=key, value=value):
                previous = self.env[key]
                self.env[key] = value
                self.run_prepare(expected=1)
                self.env[key] = previous
        self.assertFalse(Path(self.env["MOCK_LOG"]).exists())

    def test_copy_failure_cleans_container_and_temporary_files(self):
        self.env["MOCK_CP_FAIL"] = "1"
        self.run_prepare(expected=24)
        calls = [json.loads(line) for line in Path(self.env["MOCK_LOG"]).read_text().splitlines()]
        self.assertTrue(any(call[0] == "rm" for call in calls))
        self.assertFalse(list(self.identity.glob(".prepare.*")))
        self.assertFalse((self.identity / "passwd").exists())


if __name__ == "__main__":
    unittest.main()
