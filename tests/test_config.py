"""Version record diagnostics identify resolved fields without claiming missing files."""
import unittest

from ascender.config import BuildConfig
from ascender.errors import ToolError


class CompatibilityTests(unittest.TestCase):
    def config(self, **overrides):
        settings = dict(cann_version="9.1.0", torch_version="2.10.0+cpu", torch_npu_version="2.10.0.post4")
        settings.update(overrides)
        return BuildConfig(**settings)

    def diagnostic(self, config):
        with self.assertRaises(ToolError) as result:
            config.validate_compatibility()
        return str(result.exception)

    def test_only_changed_component_is_marked_different(self):
        output = self.diagnostic(self.config(torch_npu_version="2.10.0.post6"))
        self.assertIn("MATCH CANN=9.1.0 (--cann-version); recorded=9.1.0", output)
        self.assertIn("MATCH Torch=2.10.0+cpu (--torch-version); recorded=2.10.0+cpu", output)
        self.assertIn("DIFF  torch-npu=2.10.0.post6 (--torch-npu-version); recorded=2.10.0.post4", output)
        self.assertIn("not a missing-file diagnostic", output)
        self.assertIn("Missing item: software compatibility record", output)
        self.assertIn("Components differing from the recorded reference: torch-npu", output)
        self.assertIn("Missing record for: CANN=9.1.0, Torch=2.10.0+cpu, torch-npu=2.10.0.post6", output)
        self.assertIn("--allow-unverified", output)

    def test_development_combination_shows_both_full_resolved_versions(self):
        output = self.diagnostic(self.config(torch_version="2.7.1+cpu", torch_npu_version="2.7.1.post5.dev20261111"))
        self.assertIn("DIFF  Torch=2.7.1+cpu (--torch-version); recorded=2.10.0+cpu", output)
        self.assertIn("DIFF  torch-npu=2.7.1.post5.dev20261111 (--torch-npu-version); recorded=2.10.0.post4", output)

    def test_cann_only_diagnostic_omits_unrequested_framework_comparisons(self):
        config = self.config(cann_version="9.2.0", no_torch=True, torch_version="", torch_npu_version="")
        output = self.diagnostic(config)
        self.assertIn("DIFF  CANN=9.2.0 (--cann-version); recorded=9.1.0", output)
        self.assertIn("not requested (--no-torch)", output)
        self.assertNotIn("--torch-version", output)
        self.assertNotIn("--torch-npu-version", output)

    def test_recorded_versions_and_explicit_opt_in_preserve_existing_behavior(self):
        self.config().validate_compatibility()
        self.config(no_torch=True, torch_version="", torch_npu_version="").validate_compatibility()
        for options in ({"allow_unverified": True}, {"mode": "preview"}, {"mode": "materials"}):
            self.config(torch_npu_version="2.10.0.post6", **options).validate_compatibility()


if __name__ == "__main__":
    unittest.main()
