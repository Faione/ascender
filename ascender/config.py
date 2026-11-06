"""Build settings and validation; no filesystem or Docker operations."""
from __future__ import annotations

from dataclasses import dataclass, field
from ipaddress import IPv4Network
from pathlib import Path, PurePosixPath
import re

from .errors import ToolError, require

DEFAULT_MIRROR_URL = "http://mirrors.tools.huawei.com"
DEFAULT_RUNTIME_SUBNET = "192.168.240.0/24"


def clean_text(value: str) -> str:
    require(not any(ord(char) < 32 or ord(char) == 127 for char in value),
            "Values and paths cannot contain control characters.")
    return value


@dataclass
class RuntimeConfig:
    code_dir: Path | None = None
    output_dir: Path | None = None
    image_ref_file: Path | None = None
    target: str | None = None
    uid: str | None = None
    gid: str | None = None
    user: str = "developer"
    group_add: list[str] = field(default_factory=list)
    device: list[str] = field(default_factory=list)
    driver_root: str | None = None
    dcmi_dir: str | None = None
    install_info: str | None = None
    subnet: str | None = None

    def network_subnet(self) -> str:
        value = DEFAULT_RUNTIME_SUBNET if self.subnet is None else self.subnet
        try:
            network = IPv4Network(value)
        except ValueError as error:
            raise ToolError(f"--runtime-subnet must be an IPv4 network CIDR without host bits, e.g. {DEFAULT_RUNTIME_SUBNET}: {value}") from error
        require(any(network.subnet_of(IPv4Network(block)) for block in
                    ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")),
                "--runtime-subnet must be within a private IPv4 range (10/8, 172.16/12 or 192.168/16).")
        require(network.prefixlen <= 30, "--runtime-subnet must have room for a gateway and container (prefix at most /30).")
        return str(network)


@dataclass
class BuildConfig:
    target: str = "npu"
    soc: str = ""
    cann_version: str = ""
    torch_version: str = ""
    torch_npu_version: str = ""
    no_torch: bool = False
    base_image: str = "ubuntu:22.04"
    strict_versions: bool = False
    strict_soc: bool = False
    strict: bool = False
    materials_root: Path = Path("materials")
    toolkit: str = ""
    ops: str = ""
    torch_wheel: str = ""
    torch_npu_wheel: str = ""
    camodel_archive: list[str] = field(default_factory=list)
    camodel_init: str = ""
    camodel_env: str = ""
    camodel_check: str = ""
    simu_soc: str = ""
    esl_soc_version: str = ""
    esl_hardware_version: str = ""
    cann_install_dir: str = ""
    camodel_lib_dir: str = ""
    mirror_url: str = DEFAULT_MIRROR_URL
    apt_package: list[str] = field(default_factory=list)
    pip_package: list[str] = field(default_factory=list)
    pip_constraints: str = ""
    post_install: str = ""
    workdir: str = "/workspace"
    network: str = "default"
    progress: str = "plain"
    no_cache: bool = False
    output_dir: Path = Path("build")
    mode: str = "build"
    files_only: bool = False
    requested_components: dict[str, str] = field(default_factory=dict, init=False, repr=False)

    @property
    def image_components(self):
        return {name: self.requested_components.get(name) or getattr(self, name)
                for name in ("soc", "cann_version", "torch_version", "torch_npu_version")}

    @property
    def apt_mirror(self) -> str:
        return self.mirror_url.rstrip("/") + "/ubuntu"

    @property
    def pip_index(self) -> str:
        return self.mirror_url.rstrip("/") + "/pypi/simple"

    @property
    def simulation_settings(self):
        return {"soc": self.soc, "simu_soc": self.simu_soc or self.soc, "esl_soc_version": self.esl_soc_version,
                "esl_hardware_version": self.esl_hardware_version, "cann_install_dir": self.cann_install_dir,
                "camodel_lib_dir": self.camodel_lib_dir}

    def validate(self) -> None:
        for value in vars(self).values():
            for item in value if isinstance(value, list) else [value]:
                clean_text(str(item))
        require(self.target in ("npu", "simulation"), "--target must be npu or simulation.")
        require(self.mode in ("build", "materials", "preview", "check"), "Invalid operation mode.")
        require(not self.strict or self.mode in ("build", "check"), "--strict applies to --check or an actual build.")
        require(self.network in ("default", "none"), "--network must be default or none.")
        require(self.progress in ("plain", "auto", "tty"), "--progress must be plain, auto or tty.")
        self.soc = self.soc.lower()
        require(not self.soc or bool(re.fullmatch(r"[a-z0-9]+", self.soc)), "--soc must be a model/family such as 950, 950dt or 910b.")
        require(not self.cann_version or bool(re.fullmatch(r"\d+\.\d+\.\d+[A-Za-z0-9._-]*", self.cann_version)),
                "--cann-version must be an exact version filter, e.g. 9.1.0.")
        if self.no_torch:
            require(not any((self.torch_version, self.torch_npu_version, self.torch_wheel, self.torch_npu_wheel)),
                    "--no-torch conflicts with Torch options/environment variables.")
        else:
            for version in (self.torch_version, self.torch_npu_version):
                require(not version or bool(re.fullmatch(r"\d+\.\d+\.\d+[A-Za-z0-9.+_-]*", version)),
                        "Torch version filters must be base or full versions, e.g. 2.7.1 or 2.7.1.post5.dev20261111.")
            self.validate_framework_versions()
        require(not self.files_only or self.mode == "check", "--files-only requires --check.")
        require(bool(self.base_image) and not self.base_image.startswith("-")
                and not any(char.isspace() for char in self.base_image), "--base-image must be an image reference.")
        workdir = PurePosixPath(self.workdir)
        require(workdir.is_absolute() and ".." not in workdir.parts
                and workdir != PurePosixPath("/root") and PurePosixPath("/root") not in workdir.parents,
                "--workdir must be absolute and accessible to non-root users (not /root).")
        require(bool(re.fullmatch(r"https?://[A-Za-z0-9.-]+(:[0-9]+)?/?", self.mirror_url)),
                "--mirror-url must be an http(s) origin without a path, credentials, query or whitespace.")
        self.mirror_url = self.mirror_url.rstrip("/")
        for package in self.apt_package:
            require(bool(re.fullmatch(r"[a-z0-9][a-z0-9+.-]*(:[a-z0-9]+)?(=[A-Za-z0-9.+:~_-]+)?", package)),
                    f"Invalid APT package: {package}")
        for package in self.pip_package:
            require(bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*(\[[A-Za-z0-9_,.-]+\])?([<>=!~][A-Za-z0-9_.+*,<>=!~-]+)?", package)),
                    f"Invalid pip requirement: {package} (use name[extras] and version constraints).")
        if self.target == "simulation":
            self.esl_hardware_version = self.esl_hardware_version or "0x1000"
            require(not self.simu_soc or bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", self.simu_soc)),
                    "--simu-soc must name a CANN simulator directory, e.g. Ascend950DT.")
            require(not self.esl_soc_version or bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", self.esl_soc_version)),
                    "--esl-soc-version must be an ESL_SOC_VERSION model string such as Ascend950DT.")
            require(not re.fullmatch(r"0[xX][0-9a-fA-F]+", self.esl_soc_version),
                    "--esl-soc-version expects a model such as Ascend950DT; use --esl-hardware-version for 0x1000.")
            require(bool(re.fullmatch(r"(?:0[xX][0-9a-fA-F]+|[0-9]+)", self.esl_hardware_version)),
                    "--esl-hardware-version must be a decimal or hexadecimal number, e.g. 0x1000.")
            require(not self.cann_install_dir or self.cann_install_dir.startswith("/"), "--cann-install-dir must be an absolute container path.")
            require(".." not in PurePosixPath(self.camodel_lib_dir).parts and ":" not in self.camodel_lib_dir,
                    "--camodel-lib-dir cannot contain parent traversal or colons.")
        else:
            require(not any((self.camodel_archive, self.camodel_init, self.camodel_env, self.camodel_check,
                             self.simu_soc, self.esl_soc_version, self.esl_hardware_version, self.cann_install_dir, self.camodel_lib_dir)),
                    "CAModel options require --target simulation.")

    def validate_framework_versions(self) -> None:
        """Check only consistency of requested/resolved framework base versions."""
        if self.no_torch or not self.torch_version or not self.torch_npu_version:
            return
        base = lambda version: re.match(r"\d+\.\d+\.\d+", version)[0]
        require(base(self.torch_version) == base(self.torch_npu_version),
                f"Torch and torch-npu base versions differ: Torch={self.torch_version}, "
                f"torch-npu={self.torch_npu_version}. Select matching --torch-version / --torch-npu-version or wheel files.")
