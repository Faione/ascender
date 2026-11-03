"""Read real dist-info fixtures without importing CANN or installing anything."""
import importlib.metadata as metadata
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from ascender import python_deps


class PythonDependencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ascender metadata ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        distributions = metadata.distributions
        override = patch.object(python_deps.metadata, "distributions", side_effect=lambda: distributions(path=[str(self.root)]))
        override.start()
        self.addCleanup(override.stop)

    def package(self, name, version, requirements=()):
        directory = self.root / f"{name}-{version}.dist-info"
        directory.mkdir(exist_ok=True)
        text = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
        text += "".join(f"Requires-Dist: {value}\n" for value in requirements)
        (directory / "METADATA").write_text(text + "\n")

    def test_collects_only_added_or_changed_package_dependencies(self):
        self.package("existing", "1.0", ["unrelated>=1"])
        before = python_deps.installed()
        self.package("asc_op_compile_base", "9.2.0", ["psutil>=5.9", "numpy>=1.21"])
        self.assertEqual(python_deps.requirements(before, python_deps.installed()), ["numpy>=1.21", "psutil>=5.9"])
        self.assertEqual(python_deps.installed()["asc-op-compile-base"]["version"], "9.2.0")

    def test_preserves_markers_extras_bounds_and_removes_exact_duplicates(self):
        declarations = ['pyyaml>=6; python_version >= "3.9"', 'optional-tool; extra == "dev"', "helper[fast]>=1,<3"]
        self.package("cann_component", "1.0", declarations)
        self.package("asc_tools", "1.0", [declarations[0]])
        self.assertEqual(python_deps.requirements({}, python_deps.installed()), sorted(declarations))

    def test_detects_requirement_changes_even_without_version_changes(self):
        self.package("component", "1.0", ["psutil>=5"])
        before = python_deps.installed()
        self.package("component", "1.0", ["psutil>=6"])
        self.assertEqual(python_deps.requirements(before, python_deps.installed()), ["psutil>=6"])
        after = python_deps.installed()
        self.assertEqual(python_deps.requirements(after, after), [])

    def test_inventory_records_versions_without_running_pip_check(self):
        self.package("asc_op_compile_base", "9.2.0", ["psutil"])
        output = self.root / "installed-packages.txt"
        with patch.object(python_deps.subprocess, "check_output", return_value="python3=3.10\n") as command:
            python_deps.inventory(output)
        self.assertEqual(output.read_text(), "[system]\npython3=3.10\n\n[python]\nasc-op-compile-base==9.2.0\n")
        self.assertEqual(command.call_args[0][0][0], "dpkg-query")

    def test_cann_script_reads_declared_dependencies_and_checks_only_when_strict(self):
        project = Path(__file__).resolve().parents[1]
        scripts, packages, config, cann, binary = [self.root / name for name in ("scripts", "packages", "config", "cann/cann", "bin")]
        for directory in (scripts, packages, config, cann, binary):
            directory.mkdir(parents=True)
        self.package("asc_op_compile_base", "9.2.0", ["psutil>=5.9"])
        (cann / "set_env.sh").write_text(f"export PYTHONPATH={shlex.quote(str(self.root))}\n")
        shutil.copyfile(project / "ascender/python_deps.py", scripts / "python_deps.py")
        (scripts / "shell-env.sh").write_text((project / "scripts/shell-env.sh").read_text()
                                             .replace("/etc/ascend/cann-env.sh", shlex.quote(str(config / "cann-env.sh"))))
        for name in ("toolkit", "ops"):
            (packages / f"{name}.run").write_text('printf "%s %s\\n" "${0##*/}" "$1" >> "$CALL_LOG"\n')
        (binary / "python3").symlink_to(sys.executable)
        source = (project / "scripts/install-cann.sh").read_text()
        for original, target in (("/usr/local/lib/ascend", scripts), ("/usr/local/Ascend", cann.parent),
                                 ("/etc/ascend", config), ("/tmp/cann-packages", packages),
                                 ("/tmp/cann-python-before.json", self.root / "before.json")):
            source = source.replace('"' + original, '"' + str(target)).replace(original, shlex.quote(str(target)))
        runner = self.root / "install.sh"
        runner.write_text(source)
        log = self.root / "calls.txt"
        env = dict(os.environ, PATH=str(binary) + os.pathsep + os.environ["PATH"], CALL_LOG=str(log), ASCEND_ENV_MODE="npu")
        for key in ("PYTHONPATH", "_ASCEND_CANN_ENV_LOADED"):
            env.pop(key, None)
        for strict in (False, True):
            with self.subTest(strict=strict):
                log.unlink(missing_ok=True)
                env["STRICT"] = "1" if strict else "0"
                result = subprocess.run(["bash", str(runner)], env=env, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                calls = log.read_text().splitlines()
                self.assertEqual(sum(line.endswith("--check") for line in calls), 2 if strict else 0)
                self.assertEqual(sum(line.endswith("--install") for line in calls), 2)
                self.assertEqual((config / "cann-requirements.txt").read_text(), "psutil>=5.9\n")
                self.assertFalse((self.root / "before.json").exists())


if __name__ == "__main__":
    unittest.main()
