"""Create a disposable build context from validated input snapshots."""
from contextlib import contextmanager
from pathlib import Path
import shutil
import tempfile

from .errors import require
from .materials import digest


@contextmanager
def stage(config, selected, inputs, image, manifest):
    with tempfile.TemporaryDirectory(prefix="ascend-dev.") as directory:
        root = Path(directory)
        for name in ("packages", "config", "camodel/archives"):
            (root / name).mkdir(parents=True)
        for item in inputs:
            target = root / item.destination
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(item.source, target)
            require(digest(target) == item.sha256, f"Input changed during staging: {item.source}")
        for name, values in (("apt-packages.txt", config.apt_package), ("pip-packages.txt", config.pip_package)):
            (root / "config" / name).write_text("".join(value + "\n" for value in values))
        (root / "config/constraints.txt").touch()
        (root / "camodel/archives.txt").write_text("".join(path.name + "\n" for path in selected.archives))
        (root / "config/manifest.txt").write_text(manifest)
        (root / "config/materials.sha256").write_text(image.hashes)
        yield root
