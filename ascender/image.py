"""Automatic image names: build IDs by default, content fingerprints in strict mode."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import uuid

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
    if config.strict:
        require(all(item.sha256 is not None for item in inputs),
                "Strict image identity requires content hashes for all inputs.")
    parameters = {
        "target": config.target, "soc": config.soc, "cann": config.cann_version,
        "torch": config.torch_version, "torch_npu": config.torch_npu_version,
        "no_torch": int(config.no_torch), "base_id": base_id, "mirror_url": config.mirror_url,
        "apt_mirror": config.apt_mirror, "pip_index": config.pip_index, "workdir": config.workdir,
        "identity_mode": "content-sha256" if config.strict else "build-id",
    }
    if config.target == "simulation":
        parameters.update(config.simulation_settings)
    settings = "".join(f"{key}={value}\n" for key, value in parameters.items())
    for key, values in (("apt", config.apt_package), ("pip", config.pip_package),
                        ("archive", [path.name for path in selected.archives])):
        settings += "".join(f"{key}={value}\n" for value in values)
    hashes = "".join(f"{item.sha256}  {item.destination}\n" for item in inputs) if config.strict else ""
    fingerprint = hashlib.sha256((settings + hashes).encode()).hexdigest() if config.strict else uuid.uuid4().hex
    framework = "cann-only" if config.no_torch else f"torch{config.torch_version}-npu{config.torch_npu_version}"
    repository, target = ("ascend-sim", "sim") if config.target == "simulation" else ("ascend-dev", "npu")
    tag = f"{target}-cann{config.cann_version}-{config.soc}-{framework}-py310-amd64-{fingerprint[:12]}".replace("+", "_")
    require(len(tag) <= 128, "Generated tag exceeds Docker limit; component version names are too long.")
    return Image(f"{repository}:{tag}", fingerprint, settings, hashes)
