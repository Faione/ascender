"""Built-in CAModel initialization uses fake libraries and temporary install trees."""
import contextlib
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

from ascender.simulation import initialize


class SimulationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ascend simulation ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.cann = self.root / "cann"
        self.source = self.cann / "x86_64-linux/simulator/Ascend950DT/lib/libruntime_camodel.so"
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(b"CANN runtime")
        self.home = self.root / "CAModel"
        self.library = self.home / "vendor/lib"
        self.library.mkdir(parents=True)
        (self.library / "libnpu_drv_camodel.so").write_bytes(b"CAModel driver")
        (self.library / "libruntime_camodel.so").write_bytes(b"old runtime")
        self.loader = self.root / "etc/camodel-env.sh"
        self.settings = dict(soc="950dt", esl_soc_version="0x1000", simulator_soc_version="",
                             cann_install_dir=str(self.cann), camodel_lib_dir="")

    def initialize(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return initialize(self.settings, self.home, self.loader, environment={})

    def test_replaces_runtime_and_creates_relative_links_and_readable_environment(self):
        (self.library / "libruntime.so").write_bytes(b"old")
        (self.library / "libascend_hal.so").write_bytes(b"old")
        self.assertEqual(self.initialize(), self.library.resolve())
        self.assertEqual((self.library / "libruntime_camodel.so").read_bytes(), b"CANN runtime")
        self.assertEqual(os.readlink(self.library / "libruntime.so"), "libruntime_camodel.so")
        self.assertEqual(os.readlink(self.library / "libascend_hal.so"), "libnpu_drv_camodel.so")
        self.assertEqual((self.library / "set_env.sh").stat().st_mode & 0o777, 0o644)
        self.assertEqual(self.source.read_bytes(), b"CANN runtime")
        self.initialize()

    def test_generated_environment_sets_values_and_keeps_library_first_without_duplicates(self):
        self.settings["esl_soc_version"] = "0x2345"
        self.initialize()
        env = dict(os.environ, LD_LIBRARY_PATH=f"/vendor:{self.library}:/other:{self.library}")
        script = '''source "$1"; source "$1"
[[ "$ASCEND_DEVICE_ID" == 0 && "$ESL_HARDWARE_VERSION" == 0x1000 && "$ESL_SOC_VERSION" == 0x2345 ]]
[[ "$LD_LIBRARY_PATH" == "$2:/vendor:/other" ]]
'''
        result = subprocess.run(["/bin/bash", "-eu", "-c", script, "test", str(self.loader), str(self.library)],
                                env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_environment_handles_unset_library_path_and_literal_shell_characters(self):
        replacement = self.home / "user's $lib"
        self.library.rename(replacement)
        self.library = replacement
        self.initialize()
        env = dict(os.environ)
        env.pop("LD_LIBRARY_PATH", None)
        result = subprocess.run(["/bin/bash", "-eu", "-c", 'source "$1"; [[ "$LD_LIBRARY_PATH" == "$2" ]]',
                                 "test", str(self.loader), str(self.library)], env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_active_cann_environment_selects_root(self):
        self.settings["cann_install_dir"] = ""
        with contextlib.redirect_stdout(io.StringIO()):
            initialize(self.settings, self.home, self.loader, environment={"ASCEND_HOME_PATH": str(self.cann)})
        self.assertEqual((self.library / "libruntime_camodel.so").read_bytes(), b"CANN runtime")

    def test_explicit_simulator_and_library_directories_disambiguate(self):
        other = self.home / "another/lib"
        other.mkdir(parents=True)
        (other / "libnpu_drv_camodel.so").write_bytes(b"other driver")
        with self.assertRaisesRegex(ValueError, "--camodel-lib-dir"):
            self.initialize()
        self.settings.update(camodel_lib_dir="vendor/lib", simulator_soc_version="Ascend950DT")
        self.assertEqual(self.initialize(), self.library.resolve())

    def test_missing_cann_runtime_reports_expected_path_before_replacement(self):
        self.source.unlink()
        with self.assertRaisesRegex(ValueError, "Missing CANN simulator runtime") as error:
            self.initialize()
        self.assertIn("x86_64-linux/simulator/950dt/lib/libruntime_camodel.so", str(error.exception))
        self.assertEqual((self.library / "libruntime_camodel.so").read_bytes(), b"old runtime")

    def test_missing_driver_and_escaping_library_directory_are_rejected(self):
        (self.library / "libnpu_drv_camodel.so").unlink()
        with self.assertRaisesRegex(ValueError, "Missing CAModel driver library"):
            self.initialize()
        self.settings["camodel_lib_dir"] = "../outside"
        with self.assertRaisesRegex(ValueError, "inside CAMODEL_HOME"):
            self.initialize()

    def test_runtime_loader_runs_after_extra_env_and_in_ordinary_bash(self):
        self.initialize()
        (self.home / "env.sh").write_text('export LD_LIBRARY_PATH="/extra:${LD_LIBRARY_PATH:-}"\n')
        source = (Path(__file__).resolve().parents[1] / "scripts/shell-env.sh").read_text()
        cann_env = self.root / "cann-env.sh"
        cann_env.write_text('export LD_LIBRARY_PATH="/cann:${LD_LIBRARY_PATH:-}"\n')
        source = source.replace("/etc/ascend/cann-env.sh", shlex.quote(str(cann_env))).replace("/etc/ascend/camodel-env.sh", shlex.quote(str(self.loader)))
        loader = self.root / "environment.sh"
        loader.write_text(source)
        env = dict(os.environ, ASCEND_ENV_MODE="simulation", CAMODEL_HOME=str(self.home))
        for key in ("LD_LIBRARY_PATH", "_ASCEND_CANN_ENV_LOADED", "_ASCEND_SIM_ENV_LOADED"):
            env.pop(key, None)
        result = subprocess.run(["/bin/bash", "-eu", "-c", 'source "$1"; source "$1"; [[ "$LD_LIBRARY_PATH" == "$2:/extra:/cann" ]]',
                                 "test", str(loader), str(self.library)], env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_container_script_initializes_and_runs_only_selected_external_hook(self):
        project = Path(__file__).resolve().parents[1]
        scripts = self.root / "scripts"
        scripts.mkdir()
        shutil.copyfile(project / "ascender/archives.py", scripts / "archives.py")
        source = (project / "ascender/simulation.py").read_text()
        source = source.replace('Path("/etc/ascend/camodel-env.sh")', f"Path({str(self.loader)!r})")
        (scripts / "simulation.py").write_text(source)
        marker = self.root / "extra-init-called"
        (scripts / "verify-image.sh").write_text('[[ "$ESL_SOC_VERSION" == 0x1000 && "${LD_LIBRARY_PATH%%:*}" == "$CAMODEL_HOME/vendor/lib" ]]\n')
        cann_env = self.root / "cann-env.sh"
        cann_env.write_text(f"export ASCEND_HOME_PATH={shlex.quote(str(self.cann))}\n")
        environment = self.root / "environment.sh"
        environment.write_text((project / "scripts/shell-env.sh").read_text()
                               .replace("/etc/ascend/cann-env.sh", shlex.quote(str(cann_env)))
                               .replace("/etc/ascend/camodel-env.sh", shlex.quote(str(self.loader))))
        inputs = self.root / "inputs"
        (inputs / "archives").mkdir(parents=True)
        (inputs / "settings.json").write_text(json.dumps(self.settings))
        (inputs / "archives.txt").write_text("model.zip\nconfig.zip\n")
        with zipfile.ZipFile(inputs / "archives/model.zip", "w") as package:
            package.writestr("vendor/lib/libnpu_drv_camodel.so", "driver")
            package.writestr("init.sh", "exit 91\n")
            package.writestr("check.sh", "exit 92\n")
        with zipfile.ZipFile(inputs / "archives/config.zip", "w") as package:
            package.writestr("model.conf", "config")
        runner = self.root / "prepare.sh"
        runner.write_text((project / "scripts/prepare-simulation.sh").read_text()
                          .replace("/usr/local/lib/ascend", shlex.quote(str(scripts)))
                          .replace('"/tmp/camodel-inputs/$script"', shlex.quote(str(inputs)) + '/"$script"')
                          .replace("/tmp/camodel-inputs", shlex.quote(str(inputs)))
                          .replace("/etc/ascend/environment.sh", shlex.quote(str(environment))))
        binary = self.root / "bin"
        binary.mkdir()
        (binary / "python3").symlink_to(sys.executable)
        env = dict(os.environ, PATH=str(binary) + os.pathsep + os.environ["PATH"],
                   ASCEND_ENV_MODE="simulation", CAMODEL_HOME=str(self.home))
        for key in ("_ASCEND_CANN_ENV_LOADED", "_ASCEND_SIM_ENV_LOADED"):
            env.pop(key, None)
        for extra_hook in (False, True):
            with self.subTest(extra_hook=extra_hook):
                shutil.rmtree(self.home)
                self.loader.unlink(missing_ok=True)
                if extra_hook:
                    (inputs / "init.sh").write_text(f'[[ "$ESL_SOC_VERSION" == 0x1000 ]]\nprintf called > {shlex.quote(str(marker))}\n')
                result = subprocess.run(["/bin/bash", str(runner)], env=env, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(marker.exists(), extra_hook)


if __name__ == "__main__":
    unittest.main()
