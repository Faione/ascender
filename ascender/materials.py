"""Resolve the flat material layout and validate selected local inputs."""
from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatchcase
import hashlib
from pathlib import Path
import re

from . import archives, wheels
from .config import BuildConfig, clean_text
from .errors import require

PROJECT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


@dataclass(frozen=True)
class Input:
    source: Path
    destination: str
    sha256: str


@dataclass
class Materials:
    toolkit: Path
    ops: Path
    torch: Path | None = None
    torch_npu: Path | None = None
    archives: list[Path] = field(default_factory=list)
    init: Path | None = None
    env: Path | None = None
    check: Path | None = None


def choose(explicit: str, directory: Path, pattern: str, preview: bool) -> Path:
    if explicit:
        return Path(explicit).absolute()
    matches = sorted(path for path in directory.glob(pattern) if path.is_file())
    require(len(matches) <= 1, f"Multiple candidates for {pattern} in {directory}; specify the exact file.")
    require(bool(matches) or preview, f"Missing {pattern} in {directory}. Use --materials for guidance.")
    return matches[0] if matches else directory / pattern


def resolve(config: BuildConfig) -> Materials:
    root = config.materials_root.absolute()
    preview = config.mode in ("materials", "preview")
    selected = Materials(
        choose(config.toolkit, root / "cann", f"Ascend-cann-toolkit_{config.cann_version}_linux-x86_64.run", preview),
        choose(config.ops, root / "cann", f"Ascend-cann-{config.soc}-ops_{config.cann_version}_linux-x86_64.run", preview))
    if not config.no_torch:
        selected.torch, config.torch_version = wheels.resolve(
            "torch", config.torch_version, root / "torch", config.torch_wheel,
            fuzzy=not config.strict_versions, preview=preview)
        selected.torch_npu, config.torch_npu_version = wheels.resolve(
            "torch_npu", config.torch_npu_version, root / "torch", config.torch_npu_wheel,
            fuzzy=not config.strict_versions, preview=preview)
    if config.target == "simulation":
        directory = root / "camodel"
        selected.archives = ([(directory / name).absolute() for name in config.camodel_archive]
                             if config.camodel_archive else sorted(path for path in directory.glob("*ESLMODEL*.zip") if path.is_file()))
        selected.init = directory / (config.camodel_init or "init.sh")
        selected.env = directory / config.camodel_env if config.camodel_env else (
            directory / "env.sh" if (directory / "env.sh").is_file() else None)
        selected.check = directory / config.camodel_check if config.camodel_check else None
    return selected


def validate_pair(packages: list[Path]) -> None:
    require(bool(packages), "No *ESLMODEL*.zip files; place the main/config pair in materials/camodel/.")
    require(len({path.name for path in packages}) == len(packages), "Duplicate CAModel ZIP name.")
    require(len(packages) == 2, "Expected one CAModel main/config pair; use --camodel-archive to select two packages.")
    names = {path.name for path in packages}
    main = [name for name in names if not name.endswith("_config.zip")]
    require(len(main) == 1 and bool(re.fullmatch(r"x86_64_ESLMODEL_[A-Za-z0-9_.-]+\.zip", main[0])),
            "Expected x86_64_ESLMODEL_<model>_<version>.zip and its _config.zip package.")
    require(main[0][:-4] + "_config.zip" in names, "CAModel main/config package names do not match.")


def collect(config: BuildConfig, selected: Materials) -> list[Input]:
    result = []

    def add(path: Path, destination: str) -> None:
        clean_text(str(path))
        require(path.is_file() and path.stat().st_size > 0, f"Missing, unreadable or empty input: {path}")
        result.append(Input(path, destination, digest(path)))

    require(selected.toolkit.name.lower() == f"ascend-cann-toolkit_{config.cann_version}_linux-x86_64.run",
            f"Toolkit filename/version/architecture mismatch: {selected.toolkit}")
    require(selected.ops.name.lower() == f"ascend-cann-{config.soc}-ops_{config.cann_version}_linux-x86_64.run",
            f"Ops filename/model/version/architecture mismatch: {selected.ops}")
    add(selected.toolkit, "packages/cann/toolkit.run")
    add(selected.ops, "packages/cann/ops.run")
    if not config.no_torch:
        require(selected.torch != selected.torch_npu, "Torch and torch-npu must be distinct wheel files.")
        for path, prefix in ((selected.torch, f"torch-{config.torch_version}"),
                             (selected.torch_npu, f"torch_npu-{config.torch_npu_version}")):
            require(any(fnmatchcase(path.name, f"{prefix}-cp310-cp310-{platform}_x86_64.whl")
                        for platform in ("manylinux*", "linux")), f"Wheel filename/version/ABI/architecture mismatch: {path}")
            add(path, f"packages/torch/{path.name}")
    if config.target == "simulation":
        validate_pair(selected.archives)
        for path in selected.archives:
            add(path, f"camodel/archives/{path.name}")
        archives.validate(selected.archives)
        for path, name in ((selected.init, "init.sh"), (selected.env, "env.sh"), (selected.check, "check.sh")):
            if path is not None:
                add(path, f"camodel/{name}")
    for value, name in ((config.pip_constraints, "constraints.txt"), (config.post_install, "post-install.sh")):
        if value:
            add(Path(value).absolute(), f"config/{name}")
    add(PROJECT / "Dockerfile", "Dockerfile")
    for path in sorted((PROJECT / "scripts").glob("*.sh")):
        add(path, f"scripts/{path.name}")
    add(PROJECT / "ascender/archives.py", "scripts/archives.py")
    return result
