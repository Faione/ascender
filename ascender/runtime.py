"""Generate a runtime bundle without starting a container or changing project ownership."""
import os
from pathlib import Path
import shlex
import stat
import tempfile

from . import accounts, compose
from .config import clean_text
from .docker import Docker
from .errors import require


def npu_resources(options):
    devices = [Path(value) for value in (options.device or ["/dev/davinci0", "/dev/davinci_manager", "/dev/hisi_hdc"])]
    groups = [accounts.numeric_id(value) for value in options.group_add]
    for path in devices:
        require(path.is_absolute() and ":" not in str(path) and stat.S_ISCHR(path.stat().st_mode),
                f"NPU device must be an existing absolute character-device path: {path}")
        groups.append(path.stat().st_gid)
    driver = Path(options.driver_root or "/usr/local/Ascend/driver").resolve()
    dcmi = Path(options.dcmi_dir or "/usr/local/dcmi").resolve()
    info = Path(options.install_info or "/etc/ascend_install.info").absolute()
    mounts = [(dcmi, "/usr/local/dcmi", True), (driver / "lib64", "/usr/local/Ascend/driver/lib64", True),
              (driver / "version.info", "/usr/local/Ascend/driver/version.info", True),
              (info, "/etc/ascend_install.info", True)]
    for index, (source, _, _) in enumerate(mounts):
        require((source.is_dir() if index < 2 else source.is_file()) and os.access(source, os.R_OK),
                f"Missing/unreadable driver path: {source}")
    return list(dict.fromkeys(groups)), devices, mounts


def local_inputs(options):
    """Read-only preflight shared by integrated builds and standalone generation."""
    for value in vars(options).values():
        for item in value if isinstance(value, list) else [value]:
            if item is not None:
                clean_text(str(item))
    user = accounts.User.current(options.uid, options.gid, options.user)
    code = Path(options.code_dir).resolve()
    clean_text(str(code))
    require(code.is_dir() and os.access(code, os.R_OK | os.W_OK | os.X_OK),
            f"Source directory must exist and be readable/writable: {code}")
    if options.output_dir is not None:
        output = Path(options.output_dir).resolve()
        clean_text(str(output))
        require(not output.exists() or output.is_dir(), f"Runtime output must be a directory: {output}")
    return user, code


def resources(options, target):
    if target == "npu":
        return npu_resources(options)
    require(not any((options.device, options.driver_root, options.dcmi_dir, options.install_info)),
            "Device and driver options require an NPU image.")
    return list(dict.fromkeys(accounts.numeric_id(value) for value in options.group_add)), [], []


def prepare(options, backend=Docker.local, *, image=None, expected_image_id=None, project=None):
    user, code = local_inputs(options)
    output = Path(options.output_dir).resolve()
    image = image if image is not None else Path(options.image_ref_file).read_text().strip()
    require(bool(image) and not image.startswith("-") and not any(char.isspace() for char in image),
            "image-ref.txt must contain one image reference.")
    docker = backend()
    image_id = docker.image_id(image)
    require(expected_image_id is None or image_id == expected_image_id,
            "Built image reference changed before runtime preparation; use the intended local image.")
    label = docker.target(image_id)
    target = options.target or label
    require(target in ("npu", "simulation"), "Image has no recognized target label; provide --target npu or simulation.")
    require(label not in ("npu", "simulation") or target == label, "--target conflicts with the image target label.")
    groups, devices, mounts = resources(options, target)
    # Validate canonical paths too: symlinks or the calling directory may introduce controls.
    for path in (code, output, *devices, *(source for source, _, _ in mounts)):
        clean_text(str(path))
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".prepare-runtime.", dir=output) as temporary:
        stage = Path(temporary)
        accounts.prepare(docker, image_id, user, stage / "identity")
        config = stage / "compose.yaml"
        config.write_text(compose.render(image, code, output, groups, devices, mounts, project=project))
        config.chmod(0o644)
        (output / "home").mkdir(exist_ok=True)
        (output / "identity").mkdir(exist_ok=True)
        for name in ("passwd", "group", "identity.txt"):
            (stage / "identity" / name).replace(output / "identity" / name)
        config.replace(output / "compose.yaml")
    print(f"Prepared {target} runtime: {output / 'compose.yaml'}")
    print(f"Start: docker compose -f {shlex.quote(str(output / 'compose.yaml'))} up -d")
    print(f"Enter: docker compose -f {shlex.quote(str(output / 'compose.yaml'))} exec ascend bash")
    return output / "compose.yaml"
