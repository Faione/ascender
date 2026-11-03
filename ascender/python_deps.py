"""Read installed Python metadata inside the image; no third-party imports."""
import argparse
import importlib.metadata as metadata
import json
from pathlib import Path
import re
import subprocess


def installed():
    packages = {}
    for distribution in metadata.distributions():
        name = distribution.metadata.get("Name")
        if name:
            key = re.sub(r"[-_.]+", "-", name).lower()
            packages.setdefault(key, {"version": distribution.version,
                                      "requires": sorted(distribution.requires or [])})
    return packages


def requirements(before, after):
    """Keep the actual declarations, including bounds, extras and markers for pip."""
    return sorted({requirement for name, package in after.items() if before.get(name) != package
                   for requirement in package["requires"]})


def inventory(output):
    system = subprocess.check_output(["dpkg-query", "-W", "-f=${Package}=${Version}\n"], text=True)
    python = "".join(f"{name}=={package['version']}\n" for name, package in sorted(installed().items()))
    output.write_text(f"[system]\n{system}\n[python]\n{python}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("snapshot", "requirements", "inventory"))
    parser.add_argument("output", type=Path)
    parser.add_argument("--before", type=Path)
    args = parser.parse_args()
    if args.action == "snapshot":
        args.output.write_text(json.dumps(installed(), sort_keys=True))
    elif args.action == "requirements":
        if args.before is None:
            parser.error("requirements needs --before SNAPSHOT")
        values = requirements(json.loads(args.before.read_text()), installed())
        args.output.write_text("".join(value + "\n" for value in values))
        for value in values:
            print(f"CANN dependency: {value}")
    else:
        inventory(args.output)


if __name__ == "__main__":
    main()
