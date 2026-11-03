"""Tags prefer requested component versions; actual build identities stay separate."""
from pathlib import Path
import unittest

from ascender.config import BuildConfig
from ascender.image import identify, image_reference
from ascender.materials import Materials


class ImageNamingTests(unittest.TestCase):
    def test_full_release_and_development_versions_have_no_platform_or_id_suffix(self):
        for target, repository, prefix in (("npu", "ascend-dev", "npu"), ("simulation", "ascend-sim", "sim")):
            with self.subTest(target=target):
                config = BuildConfig(target=target, cann_version="9.1.0", soc="950dt",
                                     torch_version="2.7.1+cpu", torch_npu_version="2.7.1.post5.dev20261111")
                self.assertEqual(image_reference(config),
                                 f"{repository}:{prefix}-cann9.1.0-950dt-torch2.7.1_cpu-npu2.7.1.post5.dev20261111")

    def test_cann_only_name(self):
        self.assertEqual(image_reference(BuildConfig(cann_version="9.1.0", soc="950dt", no_torch=True)),
                         "ascend-dev:npu-cann9.1.0-950dt-cann-only")

    def test_requested_versions_are_preserved_after_material_resolution(self):
        config = BuildConfig(cann_version="9.1.0", soc="950", torch_version="2.7.1", torch_npu_version="2.7.1")
        config.requested_components = config.image_components
        config.soc, config.torch_version, config.torch_npu_version = "950dt", "2.7.1+cpu", "2.7.1.post5.dev20261111"
        self.assertEqual(image_reference(config), "ascend-dev:npu-cann9.1.0-950-torch2.7.1-npu2.7.1")

    def test_only_omitted_versions_are_filled_from_materials(self):
        config = BuildConfig(torch_version="2.7.1")
        config.requested_components = config.image_components
        config.cann_version, config.soc = "9.1.0", "950dt"
        config.torch_version, config.torch_npu_version = "2.7.1+cpu", "2.7.1.post5.dev20261111"
        self.assertEqual(image_reference(config), "ascend-dev:npu-cann9.1.0-950dt-torch2.7.1-npu2.7.1.post5.dev20261111")

    def test_strict_identity_and_base_changes_do_not_lengthen_the_tag(self):
        config = BuildConfig(cann_version="9.1.0", soc="950dt", no_torch=True)
        selected = Materials(Path("toolkit.run"), Path("ops.run"))
        normal = identify(config, selected, [], "sha256:base")
        config.strict = True
        strict = identify(config, selected, [], "sha256:base")
        other = identify(config, selected, [], "sha256:other")
        self.assertEqual(normal.reference, strict.reference)
        self.assertEqual(strict.reference, other.reference)
        self.assertNotEqual(normal.fingerprint, strict.fingerprint)
        self.assertNotEqual(strict.fingerprint, other.fingerprint)


if __name__ == "__main__":
    unittest.main()
