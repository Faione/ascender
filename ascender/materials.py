"""Resolve the flat material layout and validate selected local inputs."""
from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatchcase
import hashlib
from pathlib import Path
import re

from . import archives, chips, toolkits, wheels
from .config import BuildConfig, clean_text
from .errors import ToolError, missing_material, require

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
    sha256: str | None = None


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


def resolve(config: BuildConfig) -> Materials:
    if not config.requested_components:
        config.requested_components = config.image_components
    root = config.materials_root.absolute()
    preview = config.mode in ("materials", "preview")
    toolkit, config.cann_version = toolkits.resolve(config.cann_version, root / "cann", config.toolkit, preview=preview)
    ops, config.soc = chips.resolve(config.soc, config.cann_version, root / "cann", config.ops,
                                    fuzzy=not config.strict_soc, preview=preview)
    selected = Materials(toolkit, ops)
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
        selected.init = directory / config.camodel_init if config.camodel_init else (
            directory / "init.sh" if (directory / "init.sh").is_file() else None)
        selected.env = directory / config.camodel_env if config.camodel_env else (
            directory / "env.sh" if (directory / "env.sh").is_file() else None)
        selected.check = directory / config.camodel_check if config.camodel_check else None
    return selected


def validate_pair(packages: list[Path], directory: Path) -> None:
    if not packages:
        raise missing_material("CAModel main/config ZIP pair", "*ESLMODEL*.zip and its matching *_config.zip",
                               directory, "--camodel-archive (twice)", summary="No *ESLMODEL*.zip files were selected.")
    require(len({path.name for path in packages}) == len(packages), "Duplicate CAModel ZIP name.")
    if len(packages) == 1:
        path = packages[0]
        is_config = path.name.endswith("_config.zip")
        expected = path.name[:-11] + ".zip" if is_config else path.stem + "_config.zip"
        component = "CAModel main ZIP" if is_config else "CAModel configuration ZIP"
        raise missing_material(component, expected, path.parent, "--camodel-archive (twice)", packages,
                               summary=f"Incomplete CAModel main/config pair: missing {component}.")
    require(len(packages) == 2, "Expected one CAModel main/config pair; use --camodel-archive to select two packages.")
    names = {path.name for path in packages}
    main = [name for name in names if not name.endswith("_config.zip")]
    require(len(main) == 1 and bool(re.fullmatch(r"x86_64_ESLMODEL_[A-Za-z0-9_.-]+\.zip", main[0])),
            "Expected x86_64_ESLMODEL_<model>_<version>.zip and its _config.zip package.")
    expected = main[0][:-4] + "_config.zip"
    if expected not in names:
        raise missing_material("matching CAModel configuration ZIP in the selected pair", expected, directory,
                               "--camodel-archive (twice)", packages, summary="CAModel main/config package names do not match.")


def collect(config: BuildConfig, selected: Materials) -> list[Input]:
    """Locate usable inputs; scan content only when strict is requested."""
    result = []
    hash_inputs = config.strict

    def add(path: Path, destination: str, component: str = "", option: str = "") -> None:
        clean_text(str(path))
        component = component or destination
        if not path.is_file():
            if not option:
                raise ToolError(f"Missing project file: {component}\n  Expected path: {path}\n  Action: restore a complete project checkout.")
            raise missing_material(component, path.name, path.parent, option)
        if path.stat().st_size == 0:
            raise ToolError(f"Invalid material: {component}\n  Problem: empty input file\n  Path: {path}\n  Action: replace it with a complete file.")
        try:
            checksum = digest(path) if hash_inputs else None
        except PermissionError as error:
            raise ToolError(f"Unreadable material: {component}\n  Path: {path}\n  Action: grant the current user read access.") from error
        result.append(Input(path, destination, checksum))

    require(selected.toolkit.name.lower() == f"ascend-cann-toolkit_{config.cann_version}_linux-x86_64.run".lower(),
            f"Toolkit filename/version/architecture mismatch: {selected.toolkit}")
    require(selected.ops.name.lower() == f"ascend-cann-{config.soc}-ops_{config.cann_version}_linux-x86_64.run".lower(),
            f"Ops filename/model/version/architecture mismatch: {selected.ops}")
    add(selected.toolkit, "packages/cann/toolkit.run", "CANN Toolkit installer", "--toolkit")
    add(selected.ops, "packages/cann/ops.run", "CANN ops installer", "--ops")
    if not config.no_torch:
        require(selected.torch != selected.torch_npu, "Torch and torch-npu must be distinct wheel files.")
        for path, prefix in ((selected.torch, f"torch-{config.torch_version}"),
                             (selected.torch_npu, f"torch_npu-{config.torch_npu_version}")):
            require(any(fnmatchcase(path.name, f"{prefix}-cp310-cp310-{platform}_x86_64.whl")
                        for platform in ("manylinux*", "linux")), f"Wheel filename/version/ABI/architecture mismatch: {path}")
            package = "Torch" if path == selected.torch else "torch-npu"
            option = "--torch-wheel" if path == selected.torch else "--torch-npu-wheel"
            add(path, f"packages/torch/{path.name}", f"{package} wheel", option)
    if config.target == "simulation":
        validate_pair(selected.archives, config.materials_root.absolute() / "camodel")
        for path in selected.archives:
            add(path, f"camodel/archives/{path.name}", f"CAModel ZIP {path.name}", "--camodel-archive")
        if config.strict:
            archives.validate(selected.archives, crc=True)
        for path, name in ((selected.init, "init.sh"), (selected.env, "env.sh"), (selected.check, "check.sh")):
            if path is not None:
                option = {"init.sh": "--camodel-init", "env.sh": "--camodel-env", "check.sh": "--camodel-check"}[name]
                add(path, f"camodel/{name}", f"CAModel {name}", option)
    for value, name in ((config.pip_constraints, "constraints.txt"), (config.post_install, "post-install.sh")):
        if value:
            option = "--pip-constraints" if name == "constraints.txt" else "--post-install"
            add(Path(value).absolute(), f"config/{name}", name, option)
    add(PROJECT / "Dockerfile", "Dockerfile")
    for path in sorted((PROJECT / "scripts").glob("*.sh")):
        add(path, f"scripts/{path.name}")
    add(PROJECT / "ascender/archives.py", "scripts/archives.py")
    add(PROJECT / "ascender/simulation.py", "scripts/simulation.py")
    add(PROJECT / "ascender/python_deps.py", "scripts/python_deps.py")
    return result
