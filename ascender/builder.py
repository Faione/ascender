"""Build workflow: coordinate modules without implementing their policies."""
from . import context, materials, reporting
from .docker import Docker
from .errors import require
from .image import identify


def build(config, backend=Docker.local):
    config.validate()
    report = reporting.Report(config.output_dir) if config.mode == "build" else None
    status = 1
    try:
        selected = materials.resolve(config)
        if config.mode == "materials":
            reporting.materials_help(config, selected)
            return
        if config.mode == "preview":
            reporting.show_plan(config, selected)
            print("Image: pending (input hashes and local base image ID are resolved at check/build time)")
            return
        inputs = materials.collect(config, selected)
        config.validate_compatibility()
        if config.files_only:
            print("PASS: local materials (package execution/ABI checks deferred to Docker).")
            return
        if report:
            report.phase = "docker"
        docker = backend()
        base_id = docker.base_image(config.base_image)
        image = identify(config, selected, inputs, base_id)
        reporting.show_plan(config, selected)
        print(f"Image: {image.reference}")
        if config.mode == "check":
            print("PASS: materials and local Docker builder; image not built.")
            return
        report.image = image.reference
        report.phase = "staging"
        text = reporting.manifest(config, selected, image)
        report.write("manifest.txt", text)
        report.write("materials.sha256", image.hashes)
        with context.stage(config, selected, inputs, image, text) as root:
            report.phase = "build"
            report.image_id = docker.build(config, selected, image, root, report.directory)
        report.phase = "report"
        require(docker.image_id(config.base_image) == base_id,
                "Base image changed during the build; rerun with a stable local base reference.")
        with docker.container(report.image_id) as container:
            docker.copy(container, "/usr/local/share/ascend/installed-packages.txt", report.directory / "installed-packages.txt")
        report.write("manifest.txt", reporting.manifest(config, selected, image, complete=True))
        report.write("image-ref.txt", image.reference + "\n")
        report.phase = "complete"
        status = 0
        print(f"Built: {image.reference}\nReport: {report.directory}")
    except BaseException as error:
        status = getattr(error, "code", 130 if isinstance(error, KeyboardInterrupt) else 1)
        raise
    finally:
        if report:
            report.finish(status)
