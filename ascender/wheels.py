"""Resolve exact or base framework versions to one compatible local wheel."""
from __future__ import annotations

from pathlib import Path
import re
import sys

from .errors import ToolError, require


def wheel_version(path: Path, package: str) -> str | None:
    pattern = (rf"{re.escape(package)}-(\d+\.\d+\.\d+[A-Za-z0-9.+_]*)-cp310-cp310-"
               r"(?:manylinux[A-Za-z0-9_.]*|linux)_x86_64\.whl")
    match = re.fullmatch(pattern, path.name)
    return match[1] if match else None


def matches(requested: str, actual: str, fuzzy: bool) -> bool:
    if requested == actual:
        return True
    if not fuzzy or not re.fullmatch(r"\d+\.\d+\.\d+", requested):
        return False
    # A base release can select a post/local build, never another release or
    # a prerelease. An explicitly supplied suffix always remains exact.
    return bool(re.fullmatch(re.escape(requested) + r"(?:\.post[0-9]+)?(?:\+[A-Za-z0-9]+(?:[._][A-Za-z0-9]+)*)?", actual))


def resolve(package: str, requested: str, directory: Path, explicit: str = "", *,
            fuzzy: bool = True, preview: bool = False) -> tuple[Path, str]:
    flag = package.replace("_", "-")
    if explicit:
        path = Path(explicit).absolute()
        actual = wheel_version(path, package)
        require(actual is not None and matches(requested, actual, fuzzy),
                f"Wheel filename/version/ABI/architecture mismatch: {path} (requested {requested})")
    else:
        candidates = [(path, wheel_version(path, package)) for path in sorted(directory.glob(f"{package}-*.whl")) if path.is_file()]
        exact = [(path, version) for path, version in candidates if version == requested]
        compatible = exact or [(path, version) for path, version in candidates
                               if version is not None and matches(requested, version, fuzzy)]
        if len(compatible) > 1:
            options = "\n".join(f"  {path} (version {version})" for path, version in compatible)
            print(f"WARNING: Multiple candidates for --{flag}-version {requested}:\n{options}", file=sys.stderr)
            raise ToolError(f"Select a full --{flag}-version or an exact --{flag}-wheel path; no wheel was selected.")
        if not compatible:
            require(preview, f"Missing compatible wheel for {package} {requested} (cp310/x86_64) in {directory}.")
            return directory / f"{package}-{requested}-cp310-cp310-*_x86_64.whl", requested
        path, actual = compatible[0]
    if actual != requested:
        print(f"Resolved {flag} version: {requested} -> {actual} ({path.name})")
    return path, actual
