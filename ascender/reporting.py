"""Human-readable plans and durable build reports."""
from datetime import datetime, timezone
from pathlib import Path
import tempfile


def show_plan(config, selected):
    print(f"Target: {config.target} | SoC: {config.soc or 'pending detection'} | CANN: {config.cann_version or 'pending detection'}")
    print(f"Base: {config.base_image} (linux/amd64, Ubuntu 22.04, Python 3.10)")
    for name, path in (("Toolkit", selected.toolkit), ("Ops", selected.ops),
                       ("Torch", selected.torch), ("torch-npu", selected.torch_npu)):
        if path is not None:
            print(f"{name}: {path if path.is_file() else 'unresolved: ' + str(path)}")
    if config.target == "simulation":
        for path in selected.archives:
            print(f"CAModel archives: {path}")
        if not selected.archives:
            print(f"CAModel archives: unresolved: {config.materials_root.absolute()}/camodel/*ESLMODEL*.zip")
        print(f"CAModel init: built-in library replacement/symlinks/set_env.sh\nExtra init: {selected.init or 'none'}")
        print(f"CANN root: {config.cann_install_dir or 'active environment/standard paths'} | simulator SoC (--simu-soc): {config.simulation_settings['simu_soc']}")
        print(f"CAModel library dir: {config.camodel_lib_dir or 'auto: libnpu_drv_camodel.so'} | ESL_SOC_VERSION: {config.esl_soc_version or 'auto: matched simulator directory'} | ESL_HARDWARE_VERSION: {config.esl_hardware_version}")
        print(f"CAModel env: {selected.env or 'none'}\nCAModel check: {selected.check or 'none (simulation unverified)'}")
    print(f"Mirror URL: {config.mirror_url} | APT: {config.apt_mirror} | pip: {config.pip_index}")
    print(f"Workdir: {config.workdir}")
    print(f"Network: {config.network} | progress: {config.progress} | no-cache: {config.no_cache} | output: {config.output_dir}")
    for name, values in (("Extra APT", config.apt_package), ("Extra pip", config.pip_package)):
        if values:
            print(f"{name}: {', '.join(values)}")
    print(f"Constraints: {config.pip_constraints or 'none'} | post-install: {config.post_install or 'none'}")
    if config.runtime:
        print(f"Runtime code: {config.runtime.code_dir} | configuration: {config.runtime.output_dir or 'runtime/ in this build report'}")


def materials_help(config, selected):
    show_plan(config, selected)
    print("\nPrepare files manually; the tool does not download or upload them.")
    print(f"Base image: docker pull --platform linux/amd64 {config.base_image} (or docker load a prepared archive)")
    print("CANN Toolkit/ops: https://www.hiascend.com/developer/download/community/result?module=cann")
    print("PyTorch CPU wheel index: https://download.pytorch.org/whl/cpu/torch/")
    print("torch-npu releases: https://gitcode.com/Ascend/pytorch/releases")
    print("CAModel: obtain the matching x86_64_ESLMODEL_*.zip / *_config.zip pair; library initialization is built in. Extra scripts are optional.")
    print("Storage: ROOT/cann/, ROOT/torch/, ROOT/camodel/. Details: docs/downloads.md")


def manifest(config, selected, image, complete=False):
    validation = ("passed-build-script" if complete else "build-script-required") if selected.check else "not-performed"
    installation = ("passed-build-script" if complete else "build-script-required") if config.strict else "not-performed"
    requested = "".join(f"requested_{name}={value}\n" for name, value in config.requested_components.items() if value)
    return (image.parameters + requested + f"base_reference={config.base_image}\n"
            f"integrity_validation={'strict' if config.strict else 'skipped'}\n"
            f"installation_validation={installation}\n"
            f"image={image.reference}\nfingerprint={image.fingerprint}\n"
            f"device_validation=not-performed\nsimulation_validation={validation}\n")


class Report:
    def __init__(self, parent: Path):
        parent.mkdir(parents=True, exist_ok=True)
        prefix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-")
        self.directory = Path(tempfile.mkdtemp(prefix=prefix, dir=parent)).absolute()
        self.phase = "materials"
        self.image = ""
        self.image_id = ""
        print(f"Report: {self.directory}")

    def write(self, name: str, value: str):
        (self.directory / name).write_text(value)

    def finish(self, status: int):
        self.write("result.txt", f"exit_code={status}\nphase={self.phase}\nimage={self.image}\nimage_id={self.image_id}\n")
