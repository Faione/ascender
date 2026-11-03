"""Build settings and validation; no filesystem or Docker operations."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
import re

from .errors import ToolError, require

REFERENCE_VERSIONS = (
    ("CANN", "cann_version", "9.1.0"),
    ("Torch", "torch_version", "2.10.0+cpu"),
    ("torch-npu", "torch_npu_version", "2.10.0.post4"),
)


def clean_text(value: str) -> str:
    require(not any(ord(char) < 32 or ord(char) == 127 for char in value),
            "Values and paths cannot contain control characters.")
    return value


@dataclass
class BuildConfig:
    target: str = "npu"
    soc: str = ""
    cann_version: str = ""
    torch_version: str = ""
    torch_npu_version: str = ""
    no_torch: bool = False
    base_image: str = "ubuntu:22.04"
    allow_unverified: bool = False
    strict_versions: bool = False
    strict_soc: bool = False
    materials_root: Path = Path("materials")
    toolkit: str = ""
    ops: str = ""
    torch_wheel: str = ""
    torch_npu_wheel: str = ""
    camodel_archive: list[str] = field(default_factory=list)
    camodel_init: str = ""
    camodel_env: str = ""
    camodel_check: str = ""
    esl_soc_version: str = ""
    simulator_soc_version: str = ""
    cann_install_dir: str = ""
    camodel_lib_dir: str = ""
    apt_mirror: str = ""
    pip_index: str = "https://pypi.org/simple"
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

    @property
    def simulation_settings(self):
        return {"soc": self.soc, "esl_soc_version": self.esl_soc_version,
                "simulator_soc_version": self.simulator_soc_version, "cann_install_dir": self.cann_install_dir,
                "camodel_lib_dir": self.camodel_lib_dir}

    @property
    def reference_versions(self):
        return REFERENCE_VERSIONS[:1] if self.no_torch else REFERENCE_VERSIONS

    @property
    def compatibility(self) -> str:
        supported = all(getattr(self, setting) == version for _, setting, version in self.reference_versions)
        return "documented" if supported else "unverified"

    def validate(self) -> None:
        for value in vars(self).values():
            for item in value if isinstance(value, list) else [value]:
                clean_text(str(item))
        require(self.target in ("npu", "simulation"), "--target must be npu or simulation.")
        require(self.mode in ("build", "materials", "preview", "check"), "Invalid operation mode.")
        require(self.network in ("default", "none"), "--network must be default or none.")
        require(self.progress in ("plain", "auto", "tty"), "--progress must be plain, auto or tty.")
        self.soc = self.soc.lower()
        require(bool(re.fullmatch(r"[a-z0-9]+", self.soc)), "--soc must be a model/family such as 950, 950dt or 910b.")
        require(bool(re.fullmatch(r"\d+\.\d+\.\d+[A-Za-z0-9._-]*", self.cann_version)),
                "--cann-version requires an exact version, e.g. 9.1.0.")
        if self.no_torch:
            require(not any((self.torch_version, self.torch_npu_version, self.torch_wheel, self.torch_npu_wheel)),
                    "--no-torch conflicts with Torch options/environment variables.")
        else:
            for version in (self.torch_version, self.torch_npu_version):
                require(bool(re.fullmatch(r"\d+\.\d+\.\d+[A-Za-z0-9.+_-]*", version)),
                        "Provide --torch-version and --torch-npu-version (base or full version), or --no-torch.")
            base = lambda version: re.split(r"\.post|\.dev|rc|\+", version)[0]
            require(base(self.torch_version) == base(self.torch_npu_version),
                    "Torch and torch-npu base versions differ; --allow-unverified cannot bypass this conflict.")
        require(not self.files_only or self.mode == "check", "--files-only requires --check.")
        require(bool(self.base_image) and not self.base_image.startswith("-")
                and not any(char.isspace() for char in self.base_image), "--base-image must be an image reference.")
        workdir = PurePosixPath(self.workdir)
        require(workdir.is_absolute() and ".." not in workdir.parts
                and workdir != PurePosixPath("/root") and PurePosixPath("/root") not in workdir.parents,
                "--workdir must be absolute and accessible to non-root users (not /root).")
        urls = [self.pip_index] + ([self.apt_mirror] if self.apt_mirror else [])
        for url in urls:
            require(bool(re.fullmatch(r"https?://[A-Za-z0-9.-]+(:[0-9]+)?(/[A-Za-z0-9._~%/+:-]*)?", url)),
                    "Repository URLs must be http(s) URLs without credentials, queries or whitespace.")
        for package in self.apt_package:
            require(bool(re.fullmatch(r"[a-z0-9][a-z0-9+.-]*(:[a-z0-9]+)?(=[A-Za-z0-9.+:~_-]+)?", package)),
                    f"Invalid APT package: {package}")
        for package in self.pip_package:
            require(bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*(\[[A-Za-z0-9_,.-]+\])?([<>=!~][A-Za-z0-9_.+*,<>=!~-]+)?", package)),
                    f"Invalid pip requirement: {package} (use name[extras] and version constraints).")
        if self.target == "simulation":
            self.esl_soc_version = self.esl_soc_version or "0x1000"
            require(bool(re.fullmatch(r"[A-Za-z0-9_.-]+", self.esl_soc_version)), "Invalid --esl-soc-version; use a value without whitespace or shell syntax.")
            require(not self.simulator_soc_version or bool(re.fullmatch(r"[A-Za-z0-9_.-]+", self.simulator_soc_version)),
                    "--simulator-soc-version must name one simulator subdirectory.")
            require(not self.cann_install_dir or self.cann_install_dir.startswith("/"), "--cann-install-dir must be an absolute container path.")
            require(".." not in PurePosixPath(self.camodel_lib_dir).parts and ":" not in self.camodel_lib_dir,
                    "--camodel-lib-dir cannot contain parent traversal or colons.")
        else:
            require(not any((self.camodel_archive, self.camodel_init, self.camodel_env, self.camodel_check,
                             self.esl_soc_version, self.simulator_soc_version, self.cann_install_dir, self.camodel_lib_dir)),
                    "CAModel options require --target simulation.")

    def validate_compatibility(self) -> None:
        """Check the recorded combination after wheel resolution supplies full versions."""
        if self.compatibility == "documented" or self.allow_unverified or self.mode in ("materials", "preview"):
            return
        combination = ", ".join(f"{name}={getattr(self, setting)}" for name, setting, _ in self.reference_versions)
        different = [name for name, setting, reference in self.reference_versions if getattr(self, setting) != reference]
        lines = ["Version combination is unrecorded.",
                 "Missing item: software compatibility record; this is not a missing-file diagnostic.",
                 f"  Missing record for: {combination}",
                 f"  Components differing from the recorded reference: {', '.join(different)}",
                 "Resolved versions compared with the recorded reference (DIFF marks a different version):"]
        for name, setting, reference in self.reference_versions:
            actual = getattr(self, setting)
            status = "MATCH" if actual == reference else "DIFF"
            flag = "--" + setting.replace("_", "-")
            lines.append(f"  {status:5} {name}={actual} ({flag}); recorded={reference}")
        if self.no_torch:
            lines.append("  Torch/torch-npu: not requested (--no-torch).")
        lines.extend(("See docs/downloads.md for recorded combinations.",
                      "If this combination is intentional, add --allow-unverified; material checks still apply."))
        raise ToolError("\n".join(lines))
