"""The only host module that executes Docker; replace this adapter for another backend."""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import re
import subprocess
import sys

from .errors import ToolError, require


class Docker:
    def __init__(self, context: str = ""):
        self.context = context

    def command(self, *args) -> list[str]:
        return ["docker", *(["--context", self.context] if self.context else []), *map(str, args)]

    def run(self, *args) -> str:
        result = subprocess.run(self.command(*args), text=True, capture_output=True)
        if result.returncode:
            raise ToolError(f"Docker {' '.join(map(str, args[:2]))}: {result.stderr.strip() or result.stdout.strip()}",
                            result.returncode if result.returncode > 0 else 128 - result.returncode)
        return result.stdout.strip()

    @classmethod
    def local(cls):
        require(not os.environ.get("DOCKER_HOST"), "Use a local Docker context instead of DOCKER_HOST.")
        docker = cls()
        docker.context = docker.run("context", "show")
        endpoint = docker.run("context", "inspect", docker.context, "--format", "{{.Endpoints.docker.Host}}")
        require(endpoint.startswith("unix://"), "Only a local Docker Engine context (unix socket) is supported.")
        docker.run("info")
        return docker

    def base_image(self, reference: str) -> str:
        driver = self.run("buildx", "inspect", self.context)
        require(bool(re.search(r"^Driver:\s+docker\s*$", driver, re.M)),
                "The context builder must use the docker driver; enable Docker Buildx's Engine builder.")
        platform = self.run("image", "inspect", "--format", "{{.Os}}/{{.Architecture}}", reference)
        require(platform == "linux/amd64", f"Base image is {platform}; linux/amd64 is required.")
        return self.image_id(reference)

    def image_id(self, reference: str) -> str:
        value = self.run("image", "inspect", "--format", "{{.Id}}", reference)
        require(bool(value), f"Image is not available locally: {reference}; prepare it manually.")
        return value

    def target(self, image_id: str) -> str:
        return self.run("image", "inspect", "--format", '{{index .Config.Labels "dev.ascend.target"}}', image_id)

    @contextmanager
    def container(self, image_id: str):
        """Create without starting or pulling. Always remove after copying files."""
        container = self.run("create", image_id)
        require(bool(container), "Docker did not return a temporary container ID.")
        try:
            yield container
        finally:
            # Preserve the original failure, but surface cleanup errors on success.
            failing = sys.exc_info()[0] is not None
            try:
                self.run("rm", container)
            except (ToolError, OSError) as error:
                if not failing:
                    raise
                print(f"WARNING: temporary container cleanup failed: {error}", file=sys.stderr)

    def copy(self, container: str, source: str, target: Path) -> None:
        self.run("cp", f"{container}:{source}", target)

    def build(self, config, selected, image, context: Path, report: Path) -> str:
        values = {
            "BASE_IMAGE": config.base_image, "TORCH_STAGE": "cann-only" if config.no_torch else "torch-install",
            "TORCH_VERSION": config.torch_version, "TORCH_NPU_VERSION": config.torch_npu_version,
            "TORCH_WHEEL_FILE": selected.torch.name if selected.torch else "",
            "TORCH_NPU_WHEEL_FILE": selected.torch_npu.name if selected.torch_npu else "",
            "MIRROR_URL": config.mirror_url, "STRICT": "1" if config.strict else "0",
            "DEV_WORKDIR": config.workdir, "INPUT_FINGERPRINT": image.fingerprint,
        }
        args = ["buildx", "build", "--builder", self.context, "--load", "--pull=false", "--platform", "linux/amd64",
                "--progress", config.progress, "--network", config.network, "--target", config.target,
                "--tag", image.reference, "--iidfile", str(report / "image-id.txt")]
        for key, value in values.items():
            args.extend(("--build-arg", f"{key}={value}"))
        if config.no_cache:
            args.append("--no-cache")
        args.extend(("-f", str(context / "Dockerfile"), str(context)))
        with (report / "build.log").open("wb") as log:
            process = subprocess.Popen(self.command(*args), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            try:
                for chunk in iter(lambda: process.stdout.read1(65536), b""):
                    log.write(chunk)
                    log.flush()
                    sys.stdout.write(chunk.decode(errors="replace"))
                    sys.stdout.flush()
                status = process.wait()
            except BaseException:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                raise
            finally:
                process.stdout.close()
        if status:
            raise ToolError(f"Docker build failed (status {status}); see {report / 'build.log'}.",
                            status if status > 0 else 128 - status)
        image_id = (report / "image-id.txt").read_text().strip()
        require(bool(image_id), "Docker did not return an image ID.")
        return image_id
