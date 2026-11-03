"""Fast checks must not scan file content; strict checks retain deep validation."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import zipfile

from ascender import context, materials
from ascender.builder import build
from ascender.config import BuildConfig
from ascender.errors import ToolError
from ascender.image import Image, identify


class CheckModeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ascender checks ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "cann").mkdir()
        (self.root / "camodel").mkdir()
        for name in ("Ascend-cann-toolkit_9.1.0_linux-x86_64.run", "Ascend-cann-950-ops_9.1.0_linux-x86_64.run"):
            (self.root / "cann" / name).write_bytes(b"fixture")
        self.main = self.root / "camodel/x86_64_ESLMODEL_Ascend950DT_123A1.zip"
        self.other = self.main.with_name(self.main.stem + "_config.zip")
        for path, name in ((self.main, "model.bin"), (self.other, "model.conf")):
            with zipfile.ZipFile(path, "w") as package:
                package.writestr(name, b"payload")
        self.docker = MagicMock()
        self.docker.base_image.return_value = "sha256:base"
        self.docker.image_id.return_value = "sha256:base"
        self.docker.build.return_value = "sha256:output"
        self.docker.container.return_value.__enter__.return_value = "stopped"
        self.docker.copy.side_effect = lambda container, source, target: target.write_text("inventory")
        self.backend = MagicMock(return_value=self.docker)

    def config(self, **overrides):
        settings = dict(mode="check", files_only=True, target="simulation", soc="950", cann_version="9.1.0",
                        no_torch=True, materials_root=self.root, output_dir=self.root / "reports")
        settings.update(overrides)
        return BuildConfig(**settings)

    def run_build(self, **options):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            build(self.config(**options), backend=self.backend)
        return output.getvalue()

    def test_default_files_check_skips_hashes_crc_and_zip_payload_reads(self):
        with patch("ascender.materials.digest", side_effect=AssertionError("hash scan")), \
                patch.object(zipfile.ZipFile, "testzip", side_effect=AssertionError("CRC scan")), \
                patch.object(zipfile.ZipFile, "open", side_effect=AssertionError("ZIP payload scan")):
            output = self.run_build()
        self.assertIn("fast (SHA-256 and ZIP CRC skipped)", output)
        self.backend.assert_not_called()
        self.assertFalse((self.root / "reports").exists())

    def test_default_docker_check_names_image_without_calculating_fingerprint(self):
        with patch("ascender.materials.digest", side_effect=AssertionError("hash scan")), \
                patch("ascender.builder.identify", side_effect=AssertionError("unhashed identity")):
            output = self.run_build(files_only=False)
        self.assertIn("Image: ascend-sim:sim-cann9.1.0-950-cann-only", output)
        self.assertNotIn("Build identity:", output)
        self.docker.base_image.assert_called_once()
        self.docker.build.assert_not_called()
        self.docker.container.assert_not_called()

    def test_strict_files_check_hashes_inputs_and_scans_zip_crcs(self):
        crc_calls = []
        testzip = zipfile.ZipFile.testzip

        def checked_crc(package):
            crc_calls.append(Path(package.filename))
            return testzip(package)

        with patch("ascender.materials.digest", wraps=materials.digest) as hashing, \
                patch.object(zipfile.ZipFile, "testzip", checked_crc):
            output = self.run_build(strict=True)
        self.assertGreaterEqual(hashing.call_count, 4)
        self.assertEqual(crc_calls, [self.main, self.other])
        self.assertIn("strict (SHA-256 + ZIP CRC)", output)
        self.backend.assert_not_called()

    def test_strict_docker_check_computes_final_tag_without_building(self):
        output = self.run_build(strict=True, files_only=False)
        self.assertIn("Image: ascend-sim:", output)
        self.assertNotIn("Image: pending", output)
        self.docker.build.assert_not_called()

    def test_corrupt_payload_is_detected_only_by_strict_check(self):
        with zipfile.ZipFile(self.main) as package:
            member = package.getinfo("model.bin")
            offset = member.header_offset + 30 + len(member.filename.encode()) + len(member.extra)
        with self.main.open("r+b") as output:
            output.seek(offset)
            output.write(b"X")
        self.run_build()
        with self.assertRaisesRegex(ValueError, "Invalid ZIP"):
            self.run_build(strict=True)

    def test_zip_preflight_runs_only_in_strict_mode(self):
        with zipfile.ZipFile(self.main, "w") as package:
            package.writestr("../outside", b"payload")
        self.run_build()
        with self.assertRaisesRegex(ValueError, "Unsafe ZIP entry"):
            self.run_build(strict=True)

    def test_default_build_and_staging_never_hash_or_preflight_zip(self):
        with patch("ascender.materials.digest", side_effect=AssertionError("source hash scan")), \
                patch("ascender.context.digest", side_effect=AssertionError("staged hash scan")), \
                patch("ascender.image.hashlib.sha256", side_effect=AssertionError("identity hash")), \
                patch("ascender.materials.archives.validate", side_effect=AssertionError("ZIP preflight")):
            output = self.run_build(mode="build", files_only=False)
        report = next((self.root / "reports").iterdir())
        self.assertTrue((report / "image-ref.txt").is_file())
        self.assertFalse((report / "materials.sha256").exists())
        self.assertIn("Integrity validation: skipped", output)
        manifest = (report / "manifest.txt").read_text()
        self.assertIn("identity_mode=build-id\n", manifest)
        self.assertIn("integrity_validation=skipped\n", manifest)

    def test_short_tags_are_stable_while_build_ids_remain_unique(self):
        config = self.config(mode="build", files_only=False)
        selected = materials.resolve(config)
        inputs = materials.collect(config, selected)
        first = identify(config, selected, inputs, "sha256:base")
        second = identify(config, selected, inputs, "sha256:base")
        self.assertEqual(first.reference, second.reference)
        self.assertNotEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(first.hashes, "")

    def test_strict_build_hashes_sources_and_copies_and_scans_zip_crcs(self):
        digest = materials.digest
        with patch("ascender.materials.digest", wraps=digest) as hashing, \
                patch("ascender.context.digest", wraps=digest) as staged_hashing, \
                patch.object(zipfile.ZipFile, "testzip", autospec=True, return_value=None) as crc:
            self.run_build(mode="build", files_only=False, strict=True)
        self.assertGreaterEqual(hashing.call_count, 4)
        self.assertEqual(hashing.call_count, staged_hashing.call_count)
        self.assertEqual(crc.call_count, 2)
        report = next((self.root / "reports").iterdir())
        for line in (report / "materials.sha256").read_text().splitlines():
            self.assertRegex(line, r"^[0-9a-f]{64}  ")
        self.assertIn("identity_mode=content-sha256\n", (report / "manifest.txt").read_text())

    def test_default_staging_accepts_unhashed_inputs_without_checksum_file(self):
        config = self.config(mode="build", files_only=False)
        selected = materials.resolve(config)
        inputs = [materials.Input(self.main, "camodel/archives/model.zip")]
        image = identify(config, selected, inputs, "sha256:base")
        with patch("ascender.context.digest", side_effect=AssertionError("staged hash scan")):
            with context.stage(config, selected, inputs, image, "manifest") as root:
                self.assertEqual((root / "camodel/archives/model.zip").read_bytes(), self.main.read_bytes())
                self.assertFalse((root / "config/materials.sha256").exists())

    def test_strict_identity_and_staging_require_content_hashes(self):
        config = self.config(strict=True)
        selected = materials.resolve(config)
        inputs = [materials.Input(self.main, "camodel/main.zip")]
        with self.assertRaisesRegex(ToolError, "requires content hashes"):
            identify(config, selected, inputs, "sha256:base")
        with self.assertRaisesRegex(ToolError, "requires content hashes"):
            with context.stage(config, selected, inputs, Image("ref", "hash", "", ""), ""):
                self.fail("Unhashed materials must not reach staging")


if __name__ == "__main__":
    unittest.main()
