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
    """Validate runtime paths and account settings before Docker access."""
    for value in vars(options).values():
        for item in value if isinstance(value, list) else [value]:
            if item is not None:
                clean_text(str(item))
    options.network_subnet()
    user = accounts.User.current(options.uid, options.gid, options.user)
    code = Path(options.code_dir).resolve()
    clean_text(str(code))
    require(code.is_dir() and os.access(code, os.R_OK | os.W_OK | os.X_OK),
            f"Source directory must exist and be readable/writable: {code}")
    destination = Path(options.output).resolve()
    clean_text(str(destination))
    require(not destination.exists() or destination.is_file(), f"--output must be a file path: {destination}")
    require(not destination.parent.exists() or destination.parent.is_dir(),
            f"Compose parent must be a directory: {destination.parent}")
    require(destination.name not in ("home", "identity"), "--output cannot use reserved runtime directory names: home, identity.")
    return user, code, destination


def resources(options, target):
    if target == "npu":
        return npu_resources(options)
    require(not any((options.device, options.driver_root, options.dcmi_dir, options.install_info)),
            "Device and driver options require an NPU image.")
    return list(dict.fromkeys(accounts.numeric_id(value) for value in options.group_add)), [], []


def prepare(options, backend=Docker.local):
    user, code, destination = local_inputs(options)
    output = destination.parent
    image = options.image
    require(bool(image) and not image.startswith("-") and not any(char.isspace() for char in image),
            "--image must be one local image name:tag or image ID without whitespace.")
    docker = backend()
    image_id = docker.image_id(image)
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
        config.write_text(compose.render(image, code, output, groups, devices, mounts,
                                        subnet=options.network_subnet()))
        config.chmod(0o644)
        (output / "home").mkdir(exist_ok=True)
        (output / "identity").mkdir(exist_ok=True)
        for name in ("passwd", "group", "identity.txt"):
            (stage / "identity" / name).replace(output / "identity" / name)
        config.replace(destination)
    print(f"Prepared {target} runtime: {destination}")
    print(f"Runtime subnet: {options.network_subnet()}")
    print(f"Start: docker compose -f {shlex.quote(str(destination))} up -d")
    print(f"Enter: docker compose -f {shlex.quote(str(destination))} exec ascend bash")
    return destination
