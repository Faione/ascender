"""Account transformations are tested independently of Docker and CLI parsing."""
import unittest
from unittest.mock import patch

from ascender.accounts import User, account_files
from ascender.errors import ToolError

PASSWD = "root:x:0:0:root:/root:/bin/bash\nnobody:x:65534:65534:nobody:/nonexistent:/bin/false\n"
GROUP = "root:x:0:\nnogroup:x:65534:\n"


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.user = User.current("001234", "002345")

    def test_adds_name_home_shell_and_group_preserving_system_accounts(self):
        result = account_files(PASSWD, GROUP, self.user)
        self.assertIn(PASSWD, result["passwd"])
        self.assertIn("developer:*:1234:2345:Ascend developer:/workspace/home:/bin/bash\n", result["passwd"])
        self.assertIn("ascend-2345:*:2345:developer\n", result["group"])

    def test_defaults_use_current_ids_without_environment_configuration(self):
        with patch("ascender.accounts.os.getuid", return_value=5678), patch("ascender.accounts.os.getgid", return_value=6789):
            with patch.dict("os.environ", {"LOCAL_UID": "9999", "LOCAL_GID": "9999", "LOCAL_USER": "wrong"}):
                self.assertEqual(User.current(), User(5678, 6789, "developer"))

    def test_replaces_selected_uid_and_reuses_primary_group(self):
        result = account_files(PASSWD + "old:x:1234:100:Old:/old:/bin/sh\n", GROUP + "project:x:2345:existing\n", self.user)
        self.assertNotIn("old:x:", result["passwd"])
        self.assertEqual(result["passwd"].count(":1234:"), 1)
        self.assertEqual(result["group"], GROUP + "project:x:2345:existing\n")

    def test_username_collision_requires_explicit_override(self):
        passwd = PASSWD + "developer:x:777:777:Other:/home/other:/bin/bash\n"
        with self.assertRaisesRegex(ToolError, "another UID"):
            account_files(passwd, GROUP, self.user)
        self.assertIn("custom:*:1234:2345:", account_files(passwd, GROUP, User.current(1234, 2345, "custom"))["passwd"])

    def test_group_name_collision_is_rejected(self):
        with self.assertRaisesRegex(ToolError, "another GID"):
            account_files(PASSWD, GROUP + "ascend-2345:x:777:\n", self.user)

    def test_invalid_ids_and_names(self):
        for uid, gid, name in ((0, 1, "dev"), ("bad", 1, "dev"), (2147483648, 1, "dev"),
                               (1, -1, "dev"), (1, 1, "root"), (1, 1, "bad:name")):
            with self.subTest(uid=uid, gid=gid, name=name), self.assertRaises(ToolError):
                User.current(uid, gid, name)

    def test_malformed_image_databases_are_rejected(self):
        with self.assertRaisesRegex(ToolError, "Malformed passwd"):
            account_files("invalid", GROUP, self.user)
        with self.assertRaisesRegex(ToolError, "Malformed group"):
            account_files(PASSWD, "invalid", self.user)


if __name__ == "__main__":
    unittest.main()
