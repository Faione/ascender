"""CLI/ZIP/environment tests. Python host orchestration uses only the standard library."""
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MAIN = "x86_64_ESLMODEL_Ascend950DT_123A1.zip"
CONFIG = MAIN[:-4] + "_config.zip"


class BuilderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ascend test ")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.materials = self.path / "materials"
        self.cann = self.materials / "cann"
        self.torch = self.materials / "torch"
        self.cam = self.materials / "camodel"
        for directory in (self.cann, self.torch, self.cam):
            directory.mkdir(parents=True)
        for name in ("Ascend-cann-toolkit_9.1.0_linux-x86_64.run", "Ascend-cann-950-ops_9.1.0_linux-x86_64.run"):
            (self.cann / name).write_text("fixture installer; must not execute on host\n")
        for name in ("torch-2.10.0+cpu", "torch_npu-2.10.0.post4"):
            (self.torch / f"{name}-cp310-cp310-manylinux_2_28_x86_64.whl").write_bytes(b"fixture wheel")
        with zipfile.ZipFile(self.cam / MAIN, "w") as archive:
            archive.writestr("model.txt", "fixture model")
        with zipfile.ZipFile(self.cam / CONFIG, "w") as archive:
            archive.writestr("config/model.conf", "fixture config")
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
        result = subprocess.run([sys.executable, str(ROOT / "build.py")]
                                + (self.common if common else []) + list(args),
                                cwd=self.path, env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def image_from(self, output):
        return re.search(r"^Image: (ascend-\S+)$", output, re.M).group(1)

    def reports(self):
        return list((self.path / "build").glob("*/result.txt"))

    def simulation(self):
        return ["--target", "simulation"]

    def test_help_and_unknown_tag(self):
        self.assertIn("--no-torch", self.run_cli("--help", common=False))
        self.assertIn("unrecognized arguments: --tag", self.run_cli("--tag", "custom:test", expected=2))

    def test_mutually_exclusive_modes(self):
        self.run_cli("--check", "--dry-run", expected=2)
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

    def test_base_versions_resolve_to_full_versions_and_same_image(self):
        exact = self.image_from(self.run_cli("--check"))
        output = self.run_cli("--torch-version", "2.10.0", "--torch-npu-version", "2.10.0", "--check")
        self.assertIn("Resolved torch version: 2.10.0 -> 2.10.0+cpu", output)
        self.assertIn("Resolved torch-npu version: 2.10.0 -> 2.10.0.post4", output)
        self.assertIn("compatibility: documented", output)
        self.assertEqual(self.image_from(output), exact)
        self.run_cli("--torch-version", "2.10.0", "--torch-npu-version", "2.10.0", "--check", "--files-only")

    def test_resolved_full_versions_reach_docker_and_manifest(self):
        self.run_cli("--torch-version", "2.10.0", "--torch-npu-version", "2.10.0")
        calls = [json.loads(line) for line in Path(self.env["MOCK_LOG"]).read_text().splitlines()]
        build_call = next(call for call in calls if "buildx" in call and "build" in call)
        self.assertIn("TORCH_VERSION=2.10.0+cpu", build_call)
        self.assertIn("TORCH_NPU_VERSION=2.10.0.post4", build_call)
        report = self.reports()[0].parent
        manifest = (report / "manifest.txt").read_text()
        self.assertIn("torch=2.10.0+cpu\n", manifest)
        self.assertIn("torch_npu=2.10.0.post4\n", manifest)
        self.assertIn("torch2.10.0_cpu-npu2.10.0.post4", (report / "image-ref.txt").read_text())

    def test_multiple_fuzzy_candidates_warn_and_require_explicit_selection(self):
        for package, old, new in (("torch", "+cpu", "+cu128"), ("torch_npu", ".post4", ".post6")):
            with self.subTest(package=package):
                log = Path(self.env["MOCK_LOG"])
                log.unlink(missing_ok=True)
                original = next(self.torch.glob(f"{package}-*"))
                other = original.with_name(original.name.replace(old, new))
                shutil.copyfile(original, other)
                flag = package.replace("_", "-")
                args = ["--torch-version", "2.10.0", "--torch-npu-version", "2.10.0"]
                output = self.run_cli(*args, "--check", expected=1)
                self.assertIn("WARNING: Multiple candidates", output)
                self.assertIn(original.name, output)
                self.assertIn(other.name, output)
                self.assertIn(f"--{flag}-version", output)
                self.assertIn(f"--{flag}-wheel", output)
                self.assertFalse(log.exists())
                self.run_cli(*args, f"--{flag}-version", "2.10.0" + old, "--check", "--files-only")
                self.run_cli(*args, f"--{flag}-wheel", str(original), "--check", "--files-only")
                other.unlink()

    def test_fuzzy_same_version_multiple_platforms_still_require_file_selection(self):
        original = next(self.torch.glob("torch_npu-*"))
        other = original.with_name(original.name.replace("manylinux_2_28", "manylinux2014"))
        shutil.copyfile(original, other)
        output = self.run_cli("--torch-npu-version", "2.10.0", "--check", expected=1)
        self.assertIn("WARNING: Multiple candidates", output)
        self.assertIn(original.name, output)
        self.assertIn(other.name, output)
        self.assertFalse(Path(self.env["MOCK_LOG"]).exists())
        self.run_cli("--torch-npu-version", "2.10.0", "--torch-npu-wheel", str(original), "--check", "--files-only")

    def test_exact_versions_take_priority_over_suffix_candidates(self):
        for package, suffix in (("torch", "+cpu"), ("torch_npu", ".post4")):
            original = next(self.torch.glob(f"{package}-*"))
            shutil.copyfile(original, original.with_name(original.name.replace(suffix, "")))
        output = self.run_cli("--torch-version", "2.10.0", "--torch-npu-version", "2.10.0",
                              "--allow-unverified", "--check")
        self.assertNotIn("WARNING", output)
        self.assertNotIn("Resolved", output)
        self.assertIn("torch2.10.0-npu2.10.0-py310", self.image_from(output))

    def test_strict_versions_disable_base_version_fallback(self):
        self.assertIn("Missing compatible wheel", self.run_cli("--torch-version", "2.10.0", "--strict-versions",
                                                              "--check", "--files-only", expected=1))
        self.assertIn("mismatch", self.run_cli("--torch-npu-version", "2.10.0", "--strict-versions",
                                               "--torch-npu-wheel", str(next(self.torch.glob("torch_npu-*"))),
                                               "--check", "--files-only", expected=1))
        self.assertEqual(self.image_from(self.run_cli("--strict-versions", "--check")),
                         self.image_from(self.run_cli("--check")))

    def test_fuzzy_matching_preserves_release_abi_and_architecture_boundaries(self):
        original = next(self.torch.glob("torch-*"))
        original.unlink()
        for name in (original.name.replace("2.10.0+cpu", "2.10.1+cpu"),
                     original.name.replace("2.10.0+cpu", "2.10.0rc1"),
                     original.name.replace("2.10.0+cpu", "2.10.0.dev1"),
                     original.name.replace("cp310-cp310", "cp311-cp311"),
                     original.name.replace("x86_64", "aarch64")):
            with self.subTest(name=name):
                candidate = self.torch / name
                candidate.write_bytes(b"fixture wheel")
                self.assertIn("Missing compatible wheel", self.run_cli("--torch-version", "2.10.0", "--allow-unverified",
                                                                      "--check", "--files-only", expected=1))
                candidate.unlink()

    def test_fuzzy_resolution_does_not_bypass_unrecorded_combinations(self):
        original = next(self.torch.glob("torch_npu-*"))
        original.rename(original.with_name(original.name.replace("post4", "post6")))
        output = self.run_cli("--torch-npu-version", "2.10.0", "--check", "--files-only", expected=1)
        self.assertIn("Version combination is unrecorded", output)
        self.assertIn("torch-npu=2.10.0.post6", output)
        self.run_cli("--torch-npu-version", "2.10.0", "--allow-unverified", "--check", "--files-only")

    def test_soc_family_resolves_case_insensitively_and_keeps_same_image(self):
        original = next(self.cann.glob("*-ops_*.run"))
        original.rename(original.with_name(original.name.replace("950-ops", "950DT-ops")))
        output = self.run_cli("--check")
        self.assertIn("Resolved SoC: 950 -> 950dt", output)
        self.assertIn("SoC: 950dt", output)
        self.assertIn("-950dt-", self.image_from(output))
        self.assertEqual(self.image_from(output), self.image_from(self.run_cli("--soc", "950DT", "--check")))

    def test_soc_family_ambiguity_warns_and_requires_model_or_file(self):
        original = next(self.cann.glob("*-ops_*.run"))
        dt = original.with_name(original.name.replace("950-ops", "950dt-ops"))
        pr = original.with_name(original.name.replace("950-ops", "950pr-ops"))
        original.rename(dt)
        shutil.copyfile(dt, pr)
        output = self.run_cli("--check", expected=1)
        self.assertIn("WARNING: Multiple candidates for --soc 950", output)
        self.assertIn(dt.name, output)
        self.assertIn(pr.name, output)
        self.assertIn("--ops", output)
        self.assertFalse(Path(self.env["MOCK_LOG"]).exists())
        self.run_cli("--soc", "950dt", "--check", "--files-only")
        self.assertIn("-950pr-", self.image_from(self.run_cli("--ops", str(pr), "--check")))
        self.assertIn("mismatch", self.run_cli("--soc", "950dt", "--ops", str(pr), "--check", expected=1))

    def test_soc_exact_model_takes_priority_over_family_variants(self):
        original = next(self.cann.glob("*-ops_*.run"))
        for variant in ("950dt", "950pr"):
            shutil.copyfile(original, original.with_name(original.name.replace("950-ops", variant + "-ops")))
        output = self.run_cli("--check")
        self.assertNotIn("WARNING", output)
        self.assertNotIn("Resolved SoC", output)
        self.assertIn("-950-", self.image_from(output))

    def test_strict_soc_disables_family_fallback(self):
        original = next(self.cann.glob("*-ops_*.run"))
        dt = original.with_name(original.name.replace("950-ops", "950dt-ops"))
        original.rename(dt)
        self.assertIn("Missing ops installer", self.run_cli("--strict-soc", "--check", "--files-only", expected=1))
        self.assertIn("mismatch", self.run_cli("--strict-soc", "--ops", str(dt), "--check", expected=1))
        self.assertEqual(self.image_from(self.run_cli("--soc", "950dt", "--strict-soc", "--check")),
                         self.image_from(self.run_cli("--check")))

    def test_soc_family_preserves_model_version_and_architecture_boundaries(self):
        original = next(self.cann.glob("*-ops_*.run"))
        original.unlink()
        for name in (original.name.replace("950-ops", "9500-ops"),
                     original.name.replace("950-ops", "951dt-ops"),
                     original.name.replace("950-ops", "950dt-ops").replace("9.1.0", "9.2.0"),
                     original.name.replace("950-ops", "950dt-ops").replace("x86_64", "aarch64")):
            with self.subTest(name=name):
                candidate = self.cann / name
                candidate.write_text("fixture installer")
                self.assertIn("Missing ops installer", self.run_cli("--check", "--files-only", expected=1))
                candidate.unlink()

    def test_resolved_soc_is_recorded_in_manifest_and_tag(self):
        original = next(self.cann.glob("*-ops_*.run"))
        original.rename(original.with_name(original.name.replace("950-ops", "950pr-ops")))
        self.run_cli()
        report = self.reports()[0].parent
        self.assertIn("soc=950pr\n", (report / "manifest.txt").read_text())
        self.assertIn("-950pr-", (report / "image-ref.txt").read_text())

    def development_wheels(self):
        result = []
        for package, old, version in (("torch", "2.10.0+cpu", "2.7.1+cpu"),
                                       ("torch_npu", "2.10.0.post4", "2.7.1.post5.dev20261111")):
            original = next(self.torch.glob(f"{package}-*"))
            path = original.with_name(original.name.replace(old, version))
            original.rename(path)
            result.append(path)
        return result

    def test_post_dev_version_resolves_and_reaches_build_without_truncation(self):
        self.development_wheels()
        args = ["--torch-version", "2.7.1", "--torch-npu-version", "2.7.1"]
        output = self.run_cli(*args, "--check", "--files-only", expected=1)
        self.assertIn("Resolved torch-npu version: 2.7.1 -> 2.7.1.post5.dev20261111", output)
        self.assertIn("Version combination is unrecorded", output)
        output = self.run_cli(*args, "--allow-unverified")
        report = self.reports()[0].parent
        self.assertIn("torch_npu=2.7.1.post5.dev20261111\n", (report / "manifest.txt").read_text())
        self.assertIn("npu2.7.1.post5.dev20261111-", (report / "image-ref.txt").read_text())
        calls = [json.loads(line) for line in Path(self.env["MOCK_LOG"]).read_text().splitlines()]
        self.assertTrue(any("TORCH_NPU_VERSION=2.7.1.post5.dev20261111" in call for call in calls))
        self.assertEqual(self.image_from(output), self.image_from(self.run_cli(
            "--torch-version", "2.7.1+cpu", "--torch-npu-version", "2.7.1.post5.dev20261111",
            "--strict-versions", "--allow-unverified", "--check")))

    def test_post_dev_date_ambiguity_requires_complete_version(self):
        _, original = self.development_wheels()
        other = original.with_name(original.name.replace("20261111", "20261112"))
        shutil.copyfile(original, other)
        args = ["--torch-version", "2.7.1", "--torch-npu-version", "2.7.1", "--allow-unverified"]
        output = self.run_cli(*args, "--check", expected=1)
        self.assertIn("WARNING: Multiple candidates", output)
        self.assertIn("20261111", output)
        self.assertIn("20261112", output)
        self.assertFalse(Path(self.env["MOCK_LOG"]).exists())
        self.run_cli(*args, "--torch-npu-version", "2.7.1.post5.dev20261111", "--check", "--files-only")
        self.run_cli(*args, "--torch-npu-wheel", str(other), "--check", "--files-only")
        self.assertIn("Missing compatible wheel", self.run_cli(
            *args, "--torch-npu-version", "2.7.1.post5", "--check", "--files-only", expected=1))

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
        self.run_cli("--camodel-env", "env.sh", "--check", expected=1)

    def test_flat_layout_cann_only_and_removed_directory_options(self):
        output = self.run_cli("--soc", "950", "--cann-version", "9.1.0", "--no-torch",
                              "--materials-root", str(self.materials), "--check", common=False)
        self.assertIn("cann-only", self.image_from(output))
        for flag in ("--cann-root", "--torch-root", "--camodel-dir"):
            self.run_cli(flag, str(self.materials), "--check", expected=2)

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
        self.run_cli(*self.simulation(), "--camodel-archive", MAIN, "--camodel-archive", MAIN, "--check", expected=1)
        self.run_cli(*self.simulation(), "--camodel-env", "missing.sh", "--check", expected=1)

    def test_host_rejects_traversal_and_bad_zip(self):
        with zipfile.ZipFile(self.cam / MAIN, "w") as package:
            package.writestr("../escape", "bad")
        self.assertIn("Unsafe ZIP entry", self.run_cli(*self.simulation(), "--check", expected=1))
        (self.cam / MAIN).write_bytes(b"not zip")
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
        self.assertFalse((snapshot / f"camodel/archives/{MAIN}").exists())
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
        shutil.copyfile(self.cam / MAIN, self.cam / "unselected.zip")
        (self.cam / "check.sh").write_text("true\n")
        self.run_cli(*self.simulation(), "--camodel-archive", CONFIG, "--camodel-archive", MAIN,
                     "--camodel-check", "check.sh")
        staged = Path(self.env["MOCK_SNAPSHOT"]) / "camodel"
        self.assertEqual((staged / "archives.txt").read_text().splitlines(), [CONFIG, MAIN])
        self.assertFalse((staged / "archives/unselected.zip").exists())
        manifest = (self.reports()[0].parent / "manifest.txt").read_text()
        self.assertIn("simulation_validation=passed-build-script", manifest)
        self.assertEqual(manifest.count("simulation_validation="), 1)

    def test_simulation_discovers_pair_and_explicit_selection_overrides_discovery(self):
        self.run_cli(*self.simulation())
        staged = Path(self.env["MOCK_SNAPSHOT"]) / "camodel"
        self.assertEqual((staged / "archives.txt").read_text().splitlines(), [MAIN, CONFIG])
        other = MAIN.replace("123A1", "456B2")
        shutil.copyfile(self.cam / MAIN, self.cam / other)
        self.run_cli(*self.simulation(), "--check", expected=1)
        self.run_cli(*self.simulation(), "--camodel-archive", MAIN, "--camodel-archive", CONFIG)
        self.assertEqual((staged / "archives.txt").read_text().splitlines(), [MAIN, CONFIG])

    def test_simulation_pair_must_match(self):
        wrong = self.cam / CONFIG.replace("123A1", "456B2")
        (self.cam / CONFIG).rename(wrong)
        self.assertIn("do not match", self.run_cli(*self.simulation(), "--check", "--files-only", expected=1))
        wrong.unlink()
        self.assertIn("main/config pair", self.run_cli(*self.simulation(), "--check", "--files-only", expected=1))

    def test_simulation_missing_packages_allow_guidance_only(self):
        shutil.rmtree(self.cam)
        self.assertIn("No *ESLMODEL*.zip", self.run_cli(*self.simulation(), "--check", "--files-only", expected=1))
        self.assertIn("*ESLMODEL*.zip", self.run_cli(*self.simulation(), "--materials"))
        self.assertIn("unresolved:", self.run_cli(*self.simulation(), "--dry-run"))

    def test_failed_build_and_report_copy_clean_up(self):
        for variable in ("MOCK_BUILD_FAIL", "MOCK_CP_FAIL"):
            with self.subTest(variable=variable):
                self.env[variable] = "1"
                self.run_cli(expected=23 if variable == "MOCK_BUILD_FAIL" else 24)
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

    def test_sigterm_cleans_context_and_records_interruption(self):
        self.env["MOCK_BUILD_WAIT"] = "1"
        process = subprocess.Popen([sys.executable, str(ROOT / "build.py"), *self.common],
                                   cwd=self.path, env=self.env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            marker = Path(self.env["MOCK_CONTEXT_FILE"])
            deadline = time.monotonic() + 10
            while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(marker.exists(), "Build must reach the backend before interruption")
            process.send_signal(signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 143, stdout + stderr)
            self.assertFalse(Path(marker.read_text()).exists())
            report = self.reports()[0].parent
            self.assertIn("exit_code=143", (report / "result.txt").read_text())
            self.assertFalse((report / "image-ref.txt").exists())
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def test_untrusted_argument_is_not_executed(self):
        marker = self.path / "injected"
        self.run_cli("--pip-package", f"$(touch {marker})", "--dry-run", expected=1)
        self.run_cli("--pip-index", "https://secret@example.com/simple", "--check", expected=1)
        self.assertFalse(marker.exists())

    def run_extractor(self, *archives, expected=0):
        inputs = self.path / "archive-input"
        (inputs / "archives").mkdir(parents=True, exist_ok=True)
        names = [f"ESLMODEL-{index}.zip" for index in range(len(archives))]
        (inputs / "archives.txt").write_text("".join(name + "\n" for name in names))
        (inputs / "init.sh").write_text("true\n")
        for name, entries in zip(names, archives):
            with zipfile.ZipFile(inputs / "archives" / name, "w") as archive:
                for member, content in entries:
                    archive.writestr(member, content)
        home = self.path / "extracted"
        home.mkdir(exist_ok=True)
        result = subprocess.run([sys.executable, "-I", str(ROOT / "ascender/archives.py"), str(inputs), str(home)],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return home

    def test_archive_extractor_merges_two_packages_directly_and_preserves_executables(self):
        member = zipfile.ZipInfo("bin/tool")
        member.external_attr = (stat.S_IFREG | 0o755) << 16
        home = self.run_extractor([("bin/", ""), (member, "#!/bin/sh\ntrue\n")],
                                  [("bin/", ""), ("bin/other-tool", "other tool"), ("lib/model.so", "model")])
        self.assertTrue((home / "bin/tool").stat().st_mode & 0o111)
        self.assertEqual((home / "bin/other-tool").read_text(), "other tool")
        self.assertEqual((home / "lib/model.so").read_text(), "model")
        self.assertEqual((home / "init.sh").read_text(), "true\n")
        self.assertFalse((home / "ESLMODEL-0").exists())

    def test_archive_extractor_rejects_file_overwrites_between_packages(self):
        home = self.run_extractor([("lib/model.so", "original")],
                                  [("lib/model.so", "replacement")], expected=1)
        self.assertFalse((home / "lib/model.so").exists())

    def test_archive_extractor_rejects_symlinks(self):
        member = zipfile.ZipInfo("link")
        member.external_attr = (stat.S_IFLNK | 0o777) << 16
        home = self.run_extractor([(member, "../../outside")], expected=1)
        self.assertEqual(list(home.iterdir()), [])

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
