"""Argument parsing and process exit handling; business logic lives in workflows."""
import argparse
import os
from pathlib import Path
import signal
import sys

from .config import BuildConfig
from .errors import ToolError


def build_options(argv=None):
    parser = argparse.ArgumentParser(description="Build Ascend NPU/simulation images from local materials; tags are automatic.", allow_abbrev=False)
    environment = parser.add_argument_group("environment")
    for flag, default, choices in (("target", "npu", ("npu", "simulation")), ("soc", "", None),
                                    ("cann-version", "", None), ("torch-version", "", None),
                                    ("torch-npu-version", "", None), ("base-image", "ubuntu:22.04", None)):
        help_text = f"Default: {default}" if default else ("Base or full version; required unless --no-torch" if flag.startswith("torch") else "Required")
        if flag == "soc":
            help_text = "SoC model/family, e.g. 950, 950dt or 950pr (required)"
        environment.add_argument(f"--{flag}", default=os.environ.get("ASCEND_DEV_" + flag.upper().replace("-", "_")) or default,
                                 choices=choices, help=help_text)
    environment.add_argument("--no-torch", action="store_true", help="CANN-only image; omit all Torch options")
    environment.add_argument("--allow-unverified", action="store_true", help="Allow an undocumented software combination")
    environment.add_argument("--strict-versions", action="store_true", help="Require exact Torch/torch-npu versions; disable base-version fallback")
    environment.add_argument("--strict-soc", action="store_true", help="Require an exact SoC model; disable numeric-family fallback")
    local = parser.add_argument_group("local materials: ROOT/cann, ROOT/torch, ROOT/camodel")
    local.add_argument("--materials-root", type=Path, default=Path(os.environ.get("ASCEND_DEV_MATERIALS_ROOT") or "materials"), help="Default: ./materials")
    for flag in ("toolkit", "ops", "torch-wheel", "torch-npu-wheel"):
        local.add_argument(f"--{flag}", default="", help="Exact file path; overrides directory lookup")
    simulation = parser.add_argument_group("simulation inputs: paths relative to ROOT/camodel unless absolute")
    simulation.add_argument("--camodel-archive", action="append", default=[], help="Select ZIP; repeat for main/config pair (default: *ESLMODEL*.zip)")
    simulation.add_argument("--camodel-init", default="", help="Default: required init.sh")
    simulation.add_argument("--camodel-env", default="", help="Default: optional env.sh")
    simulation.add_argument("--camodel-check", default="", help="Optional build-time simulation smoke test")
    adjust = parser.add_argument_group("build adjustments")
    for flag, default, help_text in (
            ("apt-mirror", "", "Ubuntu repository base URL"), ("pip-index", "https://pypi.org/simple", "Global pip source"),
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
                                  ("check", "check", "Validate without building")):
        modes.add_argument(f"--{flag}", dest="mode", action="store_const", const=mode, help=help_text)
    parser.set_defaults(mode="build")
    parser.add_argument("--files-only", action="store_true", help="With --check: do not access Docker")
    return BuildConfig(**vars(parser.parse_args(argv)))


def runtime_options(argv=None):
    parser = argparse.ArgumentParser(description="Generate standalone Compose/account files; never start a container.", allow_abbrev=False)
    for flag in ("image-ref-file", "code-dir", "output-dir"):
        parser.add_argument(f"--{flag}", required=True, type=Path)
    parser.add_argument("--target", choices=("npu", "simulation"), help="Default: image label")
    parser.add_argument("--uid", help="Default: current UID (non-root)")
    parser.add_argument("--gid", help="Default: current GID")
    parser.add_argument("--user", default="developer")
    parser.add_argument("--group-add", action="append", default=[], help="Supplementary numeric GID; repeatable")
    parser.add_argument("--device", action="append", default=[], help="NPU device; repeat to replace default device list")
    parser.add_argument("--driver-root", help="NPU only; default /usr/local/Ascend/driver")
    parser.add_argument("--dcmi-dir", help="NPU only; default /usr/local/dcmi")
    parser.add_argument("--install-info", help="NPU only; default /etc/ascend_install.info")
    return parser.parse_args(argv)


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
