"""Only input syntax and local framework version consistency are policy checks."""
import unittest
from unittest.mock import patch

from ascender.cli import build_options
from ascender.config import BuildConfig
from ascender.errors import ToolError


class ConfigurationTests(unittest.TestCase):
    def test_default_mirror_and_normalized_origin(self):
        default = BuildConfig()
        default.validate()
        self.assertEqual(default.mirror_url, "http://mirrors.tools.huawei.com")
        self.assertEqual(default.apt_mirror, "http://mirrors.tools.huawei.com/ubuntu")
        self.assertEqual(default.pip_index, "http://mirrors.tools.huawei.com/pypi/simple")
        custom = BuildConfig(mirror_url="https://mirror.example:8443/")
        custom.validate()
        self.assertEqual(custom.mirror_url, "https://mirror.example:8443")
        self.assertEqual(custom.apt_mirror, "https://mirror.example:8443/ubuntu")
        self.assertEqual(custom.pip_index, "https://mirror.example:8443/pypi/simple")

    def test_mirror_rejects_paths_credentials_queries_and_shell_text(self):
        for url in ("", "ftp://mirror.example", "https://mirror.example/ubuntu", "https://user@mirror.example",
                    "https://mirror.example?x=1", "https://mirror.example/#fragment", "https://mirror.example//",
                    "http://mirror.example;touch marker", "$(touch marker)", "https://mirror.example\n"):
            with self.subTest(url=url), self.assertRaises(ToolError):
                BuildConfig(mirror_url=url).validate()

    def test_mirror_cli_overrides_environment_and_default(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(build_options([]).mirror_url, BuildConfig().mirror_url)
        with patch.dict("os.environ", {"ASCEND_DEV_MIRROR_URL": "https://env.example"}):
            self.assertEqual(build_options([]).mirror_url, "https://env.example")
            self.assertEqual(build_options(["--mirror-url", "http://cli.example"]).mirror_url, "http://cli.example")

    def test_model_and_versions_can_be_omitted_for_directory_detection(self):
        config = BuildConfig()
        config.validate()
        self.assertEqual((config.soc, config.cann_version, config.torch_version, config.torch_npu_version), ("", "", "", ""))

    def test_arbitrary_version_combination_is_allowed(self):
        BuildConfig(soc="950pr", cann_version="9.2.0", torch_version="2.7.1+cpu",
                    torch_npu_version="2.7.1.post5.dev20261111").validate()

    def test_framework_base_version_mismatch_is_still_rejected(self):
        with self.assertRaisesRegex(ToolError, "base versions differ"):
            BuildConfig(torch_version="2.7.1+cpu", torch_npu_version="2.10.0.post4").validate()

    def test_provided_filters_must_have_valid_syntax(self):
        for options in ({"soc": "../950"}, {"cann_version": "latest"}, {"torch_version": "*"}):
            with self.subTest(options=options), self.assertRaises(ToolError):
                BuildConfig(**options).validate()

    def test_strict_matching_does_not_require_explicit_filters(self):
        BuildConfig(strict_versions=True, strict_soc=True).validate()

    def test_simu_soc_default_follows_resolved_soc_and_can_be_overridden(self):
        config = BuildConfig(target="simulation")
        config.validate()
        config.soc = "950dt"
        self.assertEqual(config.simulation_settings["simu_soc"], "950dt")
        config.simu_soc = "Ascend950PR"
        self.assertEqual(config.simulation_settings["simu_soc"], "Ascend950PR")
        self.assertEqual(config.soc, "950dt")

    def test_simu_soc_cli_overrides_environment(self):
        with patch.dict("os.environ", {"ASCEND_DEV_SIMU_SOC": "Ascend950DT"}):
            self.assertEqual(build_options(["--target", "simulation"]).simu_soc, "Ascend950DT")
            self.assertEqual(build_options(["--target", "simulation", "--simu-soc", "Ascend950PR"]).simu_soc, "Ascend950PR")


if __name__ == "__main__":
    unittest.main()
