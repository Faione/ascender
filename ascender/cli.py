"""Argument parsing and process exit handling; business logic lives in workflows."""
import argparse
import os
from pathlib import Path
import signal
import sys

from .config import BuildConfig, RuntimeConfig, DEFAULT_MIRROR_URL, DEFAULT_RUNTIME_SUBNET
from .errors import ToolError


def build_options(argv=None):
    parser = argparse.ArgumentParser(description="Build Ascend NPU/simulation images from local materials; tags are automatic.", allow_abbrev=False)
    environment = parser.add_argument_group("environment")
    for flag, default, choices in (("target", "npu", ("npu", "simulation")), ("soc", "", None),
                                    ("cann-version", "", None), ("torch-version", "", None),
                                    ("torch-npu-version", "", None), ("base-image", "ubuntu:22.04", None)):
        help_text = f"Default: {default}" if default else "Optional filter; default: detect from local materials"
        if flag == "soc":
            help_text = "Optional SoC model/family filter, e.g. 950dt; default: detect from the ops installer"
        environment.add_argument(f"--{flag}", default=os.environ.get("ASCEND_DEV_" + flag.upper().replace("-", "_")) or default,
                                 choices=choices, help=help_text)
    environment.add_argument("--no-torch", action="store_true", help="CANN-only image; omit all Torch options")
    environment.add_argument("--strict-versions", action="store_true", help="Require exact Torch/torch-npu versions; disable base-version fallback")
    environment.add_argument("--strict-soc", action="store_true", help="Require an exact SoC model; disable numeric-family fallback")
    local = parser.add_argument_group("local materials: ROOT/cann, ROOT/torch, ROOT/camodel")
    local.add_argument("--materials-root", type=Path, default=Path(os.environ.get("ASCEND_DEV_MATERIALS_ROOT") or "materials"), help="Default: ./materials")
    for flag in ("toolkit", "ops", "torch-wheel", "torch-npu-wheel"):
        local.add_argument(f"--{flag}", default="", help="Exact file path; overrides directory lookup")
    simulation = parser.add_argument_group("simulation inputs: paths relative to ROOT/camodel unless absolute")
    simulation.add_argument("--camodel-archive", action="append", default=[], help="Select ZIP; repeat for main/config pair (default: *ESLMODEL*.zip)")
    simulation.add_argument("--camodel-init", default="", help="Optional extra initialization after built-in setup; default: use init.sh if present")
    simulation.add_argument("--camodel-env", default="", help="Default: optional env.sh")
    simulation.add_argument("--camodel-check", default="", help="Optional build-time simulation smoke test")
    simulation.add_argument("--simu-soc", default=os.environ.get("ASCEND_DEV_SIMU_SOC") or "", help="CANN simulator directory model, e.g. Ascend950DT; default: resolved --soc")
    simulation.add_argument("--esl-soc-version", default=os.environ.get("ASCEND_DEV_ESL_SOC_VERSION") or "", help="Exported ESL_SOC_VERSION only; default: matched --simu-soc directory name")
    simulation.add_argument("--esl-hardware-version", default=os.environ.get("ASCEND_DEV_ESL_HARDWARE_VERSION") or "", help="ESL_HARDWARE_VERSION (default: 0x1000)")
    simulation.add_argument("--cann-install-dir", default="", help="Container CANN installation root; default: active CANN environment/standard paths")
    simulation.add_argument("--camodel-lib-dir", default="", help="Library directory inside /opt/CAModel; default: locate unique libnpu_drv_camodel.so")
    adjust = parser.add_argument_group("build adjustments")
    adjust.add_argument("--mirror-url", default=os.environ.get("ASCEND_DEV_MIRROR_URL") or DEFAULT_MIRROR_URL,
                        help=f"APT/pip mirror origin; default: {DEFAULT_MIRROR_URL} (ASCEND_DEV_MIRROR_URL)")
    for flag, default, help_text in (
            ("pip-constraints", "", "Local additional pip constraints"), ("post-install", "", "Local Bash customization script"),
            ("workdir", "/workspace", "Image working directory")):
        adjust.add_argument(f"--{flag}", default=default, help=help_text)
    adjust.add_argument("--apt-package", action="append", default=[], help="Additional APT package; repeatable")
    adjust.add_argument("--pip-package", action="append", default=[], help="Additional pip requirement; repeatable")
    adjust.add_argument("--network", choices=("default", "none"), default="default", help="RUN network; none is not a complete offline mode")
    adjust.add_argument("--progress", choices=("plain", "auto", "tty"), default="plain")
    adjust.add_argument("--no-cache", action="store_true")
    adjust.add_argument("--output-dir", type=Path, default=Path("build"), help="Report parent directory (default: ./build)")
    modes = parser.add_mutually_exclusive_group()
    for flag, mode, help_text in (("materials", "materials", "Show download/storage guidance without Docker"),
                                  ("dry-run", "preview", "Preview without Docker or file writes"),
                                  ("check", "check", "Fast material/Docker checks without building; add --strict for content checks")):
        modes.add_argument(f"--{flag}", dest="mode", action="store_const", const=mode, help=help_text)
    parser.set_defaults(mode="build")
    parser.add_argument("--files-only", action="store_true", help="With --check: do not access Docker")
    parser.add_argument("--strict", action="store_true", help="Enable SHA-256, ZIP/installer checks, staged-copy and image verification; record a content fingerprint")
    return BuildConfig(**vars(parser.parse_args(argv)))


def runtime_options(argv=None):
    parser = argparse.ArgumentParser(description="Generate standalone Compose/account files; never start a container.", allow_abbrev=False)
    parser.add_argument("--image", required=True, help="Existing local Ascend runtime image name:tag or image ID")
    parser.add_argument("--code-dir", required=True, type=Path)
    parser.add_argument("--output", "-o", type=Path, default=Path("compose.yaml"),
                        help="Compose file path; default: ./compose.yaml. HOME/identity are stored beside it")
    parser.add_argument("--target", choices=("npu", "simulation"), help="Default: image label")
    parser.add_argument("--runtime-subnet", dest="subnet", help=f"Private IPv4 CIDR for the Compose bridge; default: {DEFAULT_RUNTIME_SUBNET} (not the build network)")
    parser.add_argument("--uid", help="Developer account UID; default: current non-root UID. Compose always runs as root")
    parser.add_argument("--gid", help="Developer account GID; default: current GID")
    parser.add_argument("--user", default="developer", help="Developer account name; default: developer. Does not change Compose's root user")
    parser.add_argument("--group-add", action="append", default=[], help="Supplementary numeric GID; repeatable")
    parser.add_argument("--device", action="append", default=[], help="NPU device; repeat to replace default device list")
    parser.add_argument("--driver-root", help="NPU only; default /usr/local/Ascend/driver")
    parser.add_argument("--dcmi-dir", help="NPU only; default /usr/local/dcmi")
    parser.add_argument("--install-info", help="NPU only; default /etc/ascend_install.info")
    return RuntimeConfig(**vars(parser.parse_args(argv)))


def main(command, argv=None):
    def terminate(_signum, _frame):
        raise SystemExit(143)

    previous = signal.signal(signal.SIGTERM, terminate)
    try:
        if command == "build":
            from .builder import build
            build(build_options(argv))
        else:
            from .runtime import prepare
            prepare(runtime_options(argv))
        return 0
    except ToolError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return error.code
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    finally:
        signal.signal(signal.SIGTERM, previous)
