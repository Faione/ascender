"""Deterministic image identity, independent of local source/output paths."""
from dataclasses import dataclass
import hashlib

from .config import BuildConfig
from .errors import require
from .materials import Input, Materials


@dataclass(frozen=True)
class Image:
    reference: str
    fingerprint: str
    parameters: str
    hashes: str


def identify(config: BuildConfig, selected: Materials, inputs: list[Input], base_id: str) -> Image:
    parameters = {
        "target": config.target, "soc": config.soc, "cann": config.cann_version,
        "torch": config.torch_version, "torch_npu": config.torch_npu_version,
        "no_torch": int(config.no_torch), "base_id": base_id, "apt_mirror": config.apt_mirror,
        "pip_index": config.pip_index, "workdir": config.workdir,
    }
    settings = "".join(f"{key}={value}\n" for key, value in parameters.items())
    for key, values in (("apt", config.apt_package), ("pip", config.pip_package),
                        ("archive", [path.name for path in selected.archives])):
        settings += "".join(f"{key}={value}\n" for value in values)
    hashes = "".join(f"{item.sha256}  {item.destination}\n" for item in inputs)
    fingerprint = hashlib.sha256((settings + hashes).encode()).hexdigest()
    framework = "cann-only" if config.no_torch else f"torch{config.torch_version}-npu{config.torch_npu_version}"
    repository, target = ("ascend-sim", "sim") if config.target == "simulation" else ("ascend-dev", "npu")
    tag = f"{target}-cann{config.cann_version}-{config.soc}-{framework}-py310-amd64-{fingerprint[:12]}".replace("+", "_")
    require(len(tag) <= 128, "Generated tag exceeds Docker limit; component version names are too long.")
    return Image(f"{repository}:{tag}", fingerprint, settings, hashes)
