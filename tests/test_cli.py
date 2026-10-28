"""CLI/ZIP/environment tests. Python is a test dependency only, not a host runtime requirement."""
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]


class BuilderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ascend test ")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.materials = self.path / "materials"
        self.cann = self.materials / "cann/9.1.0/linux-amd64"
        self.torch = self.materials / "torch/2.10.0/cp310/linux-amd64"
        self.cam = self.materials / "camodel/950/9.1.0"
        for directory in (self.cann, self.torch, self.cam):
            directory.mkdir(parents=True)
        for name in ("Ascend-cann-toolkit_9.1.0_linux-x86_64.run", "Ascend-cann-950-ops_9.1.0_linux-x86_64.run"):
            (self.cann / name).write_text("fixture installer; must not execute on host\n")
        for name in ("torch-2.10.0+cpu", "torch_npu-2.10.0.post4"):
            (self.torch / f"{name}-cp310-cp310-manylinux_2_28_x86_64.whl").write_bytes(b"fixture wheel")
        with zipfile.ZipFile(self.cam / "model.zip", "w") as archive:
            archive.writestr("model.txt", "fixture model")
        (self.cam / "init.sh").write_text("#!/bin/bash\ntrue\n")
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith("ASCEND_DEV_") and key != "DOCKER_HOST"}
        self.env.update(MOCK_LOG=str(self.path / "docker.log"),
                        MOCK_SNAPSHOT=str(self.path / "snapshot"),
                        MOCK_CONTEXT_FILE=str(self.path / "context-path"))
        binary = self.path / "bin"
        binary.mkdir()
        mock = binary / "docker"
        mock.write_text(f"#!{sys.executable}\n" + (ROOT / "tests/docker_mock.py").read_text())
        mock.chmod(0o755)
        self.env["PATH"] = str(binary) + os.pathsep + self.env["PATH"]
        self.common = ["--soc", "950", "--cann-version", "9.1.0", "--torch-version", "2.10.0+cpu",
                       "--torch-npu-version", "2.10.0.post4", "--materials-root", str(self.materials)]

    def run_cli(self, *args, expected=0, common=True):
        result = subprocess.run(["/bin/bash", str(ROOT / "build-image.sh")]
                                + (self.common if common else []) + list(args),
                                cwd=self.path, env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def image_from(self, output):
        return re.search(r"^Image: (ascend-\S+)$", output, re.M).group(1)

    def reports(self):
        return list((self.path / "build").glob("*/result.txt"))

    def simulation(self):
        return ["--target", "simulation", "--camodel-dir", str(self.cam), "--camodel-archive", "model.zip"]

    def test_help_and_unknown_tag(self):
        self.assertIn("--no-torch", self.run_cli("--help", common=False))
        self.assertIn("Unknown argument: --tag", self.run_cli("--tag", "custom:test", expected=1))

    def test_mutually_exclusive_modes(self):
        self.run_cli("--check", "--dry-run", expected=1)
        self.run_cli("--files-only", expected=1)

    def test_guidance_and_preview_need_no_files_or_docker(self):
        shutil.rmtree(self.materials)
        self.assertIn("https://", self.run_cli("--materials"))
        output = self.run_cli("--dry-run", "--pip-package", "numpy<2", "--pip-package", "foo[bar]>=1.0")
        self.assertIn("unresolved:", output)
        self.assertIn("pending", output)
        self.assertIn("foo[bar]>=1.0", output)
        self.assertFalse(Path(self.env["MOCK_LOG"]).exists())
        self.assertFalse((self.path / "build").exists())

    def test_files_only_never_calls_docker(self):
        self.assertIn("PASS", self.run_cli("--check", "--files-only"))
        self.assertFalse(Path(self.env["MOCK_LOG"]).exists())

    def test_missing_and_empty_inputs(self):
        wheel = next(self.torch.glob("torch_npu*"))
        wheel.write_bytes(b"")
        self.assertIn("empty input", self.run_cli("--check", "--files-only", expected=1))
        wheel.unlink()
        self.assertIn("Missing", self.run_cli("--check", "--files-only", expected=1))

    def test_ambiguous_wheels_require_explicit_selection(self):
        original = next(self.torch.glob("torch_npu*"))
        second = self.torch / original.name.replace("manylinux_2_28", "manylinux2014")
        shutil.copyfile(original, second)
        self.assertIn("Multiple candidates", self.run_cli("--check", "--files-only", expected=1))
        self.run_cli("--torch-npu-wheel", str(original), "--check", "--files-only")

    def test_full_post_version_cannot_be_bypassed(self):
        wrong = next(self.torch.glob("torch_npu*"))
        renamed = wrong.with_name(wrong.name.replace("post4", "post6"))
        wrong.rename(renamed)
        output = self.run_cli("--torch-npu-wheel", str(renamed), "--allow-unverified", "--check", "--files-only", expected=1)
        self.assertIn("mismatch", output)

    def test_model_and_abi_mismatch(self):
        for option, original, replacement in (
                ("--ops", next(self.cann.glob("*950*")), "Ascend-cann-910b-ops_9.1.0_linux-x86_64.run"),
                ("--torch-wheel", next(self.torch.glob("torch-*")), "torch-2.10.0+cpu-cp311-cp311-linux_x86_64.whl")):
            with self.subTest(option=option):
                wrong = self.path / replacement
                shutil.copyfile(original, wrong)
                self.assertIn("mismatch", self.run_cli(option, str(wrong), "--check", "--files-only", expected=1))

    def test_unknown_combination_requires_opt_in(self):
        self.run_cli("--cann-version", "9.2.0", "--check", expected=1)
        self.run_cli("--torch-npu-version", "2.7.1.post8", "--allow-unverified", "--check", expected=1)

    def test_no_torch_and_simulation_option_conflicts(self):
        self.run_cli("--no-torch", "--check", expected=1)
        self.run_cli("--camodel-dir", str(self.cam), "--check", expected=1)
        self.run_cli("--target", "simulation", "--check", expected=1)

    def test_cann_only_and_legacy_layout(self):
        legacy = self.path / "legacy/950/9.1.0"
        shutil.copytree(self.cann, legacy)
        output = self.run_cli("--soc", "950", "--cann-version", "9.1.0", "--no-torch",
                              "--cann-root", str(self.path / "legacy"), "--check", common=False)
        self.assertIn("cann-only", self.image_from(output))

    def test_identity_stability_and_material_changes(self):
        first = self.image_from(self.run_cli("--check"))
        self.env["ASCEND_DEV_TAG"] = "ignored:custom"
        moved = self.path / "other material location"
        shutil.copytree(self.materials, moved)
        second = self.image_from(self.run_cli("--materials-root", str(moved), "--output-dir", str(self.path / "other-output"),
                                              "--no-cache", "--progress", "auto", "--check"))
        self.assertEqual(first, second)
        next(self.cann.glob("*toolkit*")).write_text("changed installer")
        self.assertNotEqual(first, self.image_from(self.run_cli("--check")))

    def test_base_image_aliases_with_same_id_share_identity(self):
        # Here the mock returns one immutable base ID for both aliases.
        first = self.image_from(self.run_cli("--check"))
        self.assertEqual(first, self.image_from(self.run_cli("--base-image", "ubuntu-local:alias", "--check")))

    def test_simulation_identity_and_script_inputs(self):
        npu = self.image_from(self.run_cli("--check"))
        first = self.image_from(self.run_cli(*self.simulation(), "--check"))
        self.assertTrue(first.startswith("ascend-sim:sim-"))
        self.assertNotEqual(npu, first)
        (self.cam / "init.sh").write_text("echo changed\n")
        self.assertNotEqual(first, self.image_from(self.run_cli(*self.simulation(), "--check")))
        self.assertEqual(npu, self.image_from(self.run_cli("--check")))

    def test_simulation_duplicate_and_missing_scripts(self):
        self.run_cli(*self.simulation(), "--camodel-archive", "model.zip", "--check", expected=1)
        self.run_cli(*self.simulation(), "--camodel-env", "missing.sh", "--check", expected=1)

    def test_host_rejects_traversal_and_bad_zip(self):
        with zipfile.ZipFile(self.cam / "model.zip", "w") as package:
            package.writestr("../escape", "bad")
        self.assertIn("Unsafe ZIP entry", self.run_cli(*self.simulation(), "--check", expected=1))
        (self.cam / "model.zip").write_bytes(b"not zip")
        self.assertIn("Invalid ZIP", self.run_cli(*self.simulation(), "--check", expected=1))

    def test_wrong_base_architecture(self):
        self.env["MOCK_PLATFORM"] = "linux/arm64"
        self.assertIn("linux/amd64 is required", self.run_cli("--check", expected=1))

    def test_successful_build_reports_and_context_cleanup(self):
        marker = self.path / "must-not-execute"
        hook = self.path / "hook.sh"
        hook.write_text(f"touch '{marker}'\n")
        self.run_cli("--post-install", str(hook), "--apt-package", "vim", "--pip-package", "pytest")
        report = self.reports()[0].parent
        self.assertIn("exit_code=0", (report / "result.txt").read_text())
        self.assertTrue((report / "image-ref.txt").read_text().startswith("ascend-dev:"))
        self.assertFalse(marker.exists())
        context = Path(Path(self.env["MOCK_CONTEXT_FILE"]).read_text())
        self.assertFalse(context.exists())
        snapshot = Path(self.env["MOCK_SNAPSHOT"])
        self.assertFalse((snapshot / "camodel/archives/model.zip").exists())
        self.assertEqual((snapshot / "config/apt-packages.txt").read_text(), "vim\n")
        self.assertTrue((snapshot / "config/manifest.txt").exists())
        self.assertNotIn(str(self.path), (report / "manifest.txt").read_text())

    def test_cann_only_build_does_not_stage_torch(self):
        self.run_cli("--soc", "950", "--cann-version", "9.1.0", "--no-torch",
                     "--materials-root", str(self.materials), common=False)
        snapshot = Path(self.env["MOCK_SNAPSHOT"])
        self.assertFalse((snapshot / "packages/torch").exists())
        self.assertIn("cann-only", (self.reports()[0].parent / "image-ref.txt").read_text())

    def test_simulation_stages_only_selected_archives_in_order(self):
        shutil.copyfile(self.cam / "model.zip", self.cam / "tools.zip")
        shutil.copyfile(self.cam / "model.zip", self.cam / "unselected.zip")
        (self.cam / "check.sh").write_text("true\n")
        self.run_cli(*self.simulation(), "--camodel-archive", "tools.zip", "--camodel-check", "check.sh")
        staged = Path(self.env["MOCK_SNAPSHOT"]) / "camodel"
        self.assertEqual((staged / "archives.txt").read_text(), "model.zip\ntools.zip\n")
        self.assertFalse((staged / "archives/unselected.zip").exists())
        manifest = (self.reports()[0].parent / "manifest.txt").read_text()
        self.assertIn("simulation_validation=passed-build-script", manifest)
        self.assertEqual(manifest.count("simulation_validation="), 1)

    def test_failed_build_and_report_copy_clean_up(self):
        for variable in ("MOCK_BUILD_FAIL", "MOCK_CP_FAIL"):
            with self.subTest(variable=variable):
                self.env[variable] = "1"
                self.run_cli(expected=1 if variable == "MOCK_BUILD_FAIL" else 24)
                context = Path(Path(self.env["MOCK_CONTEXT_FILE"]).read_text())
                self.assertFalse(context.exists())
                self.env.pop(variable)
        for report in self.reports():
            self.assertNotIn("exit_code=0", report.read_text())
            self.assertFalse((report.parent / "image-ref.txt").exists())
        calls = [json.loads(line) for line in Path(self.env["MOCK_LOG"]).read_text().splitlines()]
        self.assertTrue(any("rm" in call for call in calls))

    def test_build_material_failure_still_leaves_report(self):
        toolkit = next(self.cann.glob("*toolkit*"))
        toolkit.write_bytes(b"")
        self.run_cli(expected=1)
        toolkit.unlink()
        self.run_cli(expected=1)
        for report in self.reports():
            self.assertIn("phase=materials", report.read_text())

    def test_untrusted_argument_is_not_executed(self):
        marker = self.path / "injected"
        self.run_cli("--pip-package", f"$(touch {marker})", "--dry-run", expected=1)
        self.run_cli("--pip-index", "https://secret@example.com/simple", "--check", expected=1)
        self.assertFalse(marker.exists())

    def test_archive_extractor_preserves_executables_and_rejects_symlinks(self):
        source = (ROOT / "scripts/prepare-simulation.sh").read_text()
        program = re.search(r"<<'PY'\n(.*?)\nPY", source, re.S).group(1)
        inputs = self.path / "archive-input"
        (inputs / "archives").mkdir(parents=True)
        (inputs / "archives.txt").write_text("model.zip\n")
        (inputs / "init.sh").write_text("true\n")
        archive_path = inputs / "archives/model.zip"
        member = zipfile.ZipInfo("bin/tool")
        member.external_attr = (stat.S_IFREG | 0o755) << 16
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr(member, "#!/bin/sh\ntrue\n")
        home = self.path / "extracted"
        home.mkdir()
        subprocess.run([sys.executable, "-I", "-", str(inputs), str(home)], input=program, text=True, check=True)
        self.assertTrue((home / "model/bin/tool").stat().st_mode & 0o111)
        shutil.rmtree(home)
        home.mkdir()
        member = zipfile.ZipInfo("link")
        member.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr(member, "../../outside")
        result = subprocess.run([sys.executable, "-I", "-", str(inputs), str(home)], input=program, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((home / "model").exists())

    def test_environment_loading_is_idempotent_and_restores_nounset(self):
        cann = self.path / "vendor-env.sh"
        cann.write_text('export VENDOR_PATH="${NOT_SET_ON_PURPOSE}"\nexport LOAD_COUNT=$((${LOAD_COUNT:-0}+1))\n')
        source = (ROOT / "scripts/shell-env.sh").read_text().replace("/etc/ascend/cann-env.sh", shlex.quote(str(cann)))
        loader = self.path / "loader.sh"
        loader.write_text(source)
        result = subprocess.run(["/bin/bash", "-eu", "-c", 'source "$1"; source "$1"; [[ "$LOAD_COUNT" == 1 && "$-" == *u* ]]',
                                 "test", str(loader)], env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
