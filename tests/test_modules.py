"""Module boundary checks: archive safety, immutable staging and backend replacement."""
from contextlib import contextmanager
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from ascender import archives, context
from ascender.builder import build
from ascender.config import BuildConfig
from ascender.errors import ToolError
from ascender.image import Image
from ascender.materials import Input, Materials, digest


class ModuleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)

    def test_container_annotations_are_not_evaluated_during_import(self):
        # Model Python <=3.8's built-in list/dict types, which do not implement
        # __class_getitem__. Both host entry points must survive module import.
        legacy_container = type("LegacyContainer", (), {})
        root = Path(__file__).resolve().parents[1]
        for name, builtin in (("image", "list"), ("accounts", "dict")):
            with self.subTest(module=name):
                module_name = f"ascender._compat_{name}"
                spec = importlib.util.spec_from_file_location(module_name, root / "ascender" / f"{name}.py")
                module = importlib.util.module_from_spec(spec)
                setattr(module, builtin, legacy_container)
                with patch.dict(sys.modules, {module_name: module}):
                    spec.loader.exec_module(module)

    def test_staging_rejects_inputs_changed_after_validation(self):
        source = self.path / "installer.run"
        source.write_text("original")
        item = Input(source, "packages/cann/toolkit.run", digest(source))
        source.write_text("changed")
        config = BuildConfig(strict=True)
        selected = Materials(source, source)
        with self.assertRaisesRegex(ToolError, "changed during staging"):
            with context.stage(config, selected, [item], Image("ref", "hash", "", ""), ""):
                self.fail("A changed input must never reach the backend")

    def test_archive_preflight_rejects_escaping_paths_and_file_directory_conflicts(self):
        package = self.path / "model.zip"
        for entries in ([('../outside', 'bad')], [('lib', 'file'), ('lib/tool', 'child')],
                        [('lib/tool', 'child'), ('lib', 'file')], [('/absolute', 'bad')]):
            with self.subTest(entries=entries):
                with zipfile.ZipFile(package, 'w') as output:
                    for name, value in entries:
                        output.writestr(name, value)
                destination = self.path / "output"
                with self.assertRaises(ValueError):
                    archives.extract([package], destination)
                self.assertFalse(destination.exists())

    def test_workflow_accepts_another_backend_and_rejects_base_image_movement(self):
        root = self.path / "materials"
        (root / "cann").mkdir(parents=True)
        for name in ("Ascend-cann-toolkit_9.1.0_linux-x86_64.run", "Ascend-cann-950-ops_9.1.0_linux-x86_64.run"):
            (root / "cann" / name).write_text("fixture")

        class Backend:
            moved = False
            context = None
            removed = False

            def base_image(self, _reference):
                return "sha256:base"

            def image_id(self, _reference):
                return "sha256:changed" if self.moved else "sha256:base"

            def build(self, config, selected, image, context_path, report):
                self.context = context_path
                assert (context_path / "scripts/archives.py").is_file()
                assert (context_path / "scripts/python_deps.py").is_file()
                (report / "image-id.txt").write_text("sha256:output")
                (report / "build.log").write_text("adapter build")
                return "sha256:output"

            @contextmanager
            def container(self, _image):
                try:
                    yield "stopped"
                finally:
                    self.removed = True

            def copy(self, _container, _source, target):
                target.write_text("package inventory")

        for moved in (False, True):
            with self.subTest(moved=moved):
                backend = Backend()
                backend.moved = moved
                config = BuildConfig(soc="950", cann_version="9.1.0", no_torch=True, strict=True,
                                     materials_root=root, output_dir=self.path / str(moved))
                if moved:
                    with self.assertRaisesRegex(ToolError, "Base image changed"):
                        build(config, backend=lambda: backend)
                else:
                    build(config, backend=lambda: backend)
                report = next(config.output_dir.iterdir())
                self.assertEqual((report / "image-ref.txt").exists(), not moved)
                self.assertEqual(backend.removed, not moved)
                self.assertFalse(backend.context.exists())


if __name__ == "__main__":
    unittest.main()
