"""Read the CANN version from one local x86_64 Toolkit installer."""
from __future__ import annotations

from pathlib import Path
import re
import sys

from .errors import ToolError, missing_material, require


def version(path: Path) -> str | None:
    match = re.fullmatch(r"Ascend-cann-toolkit_(\d+\.\d+\.\d+[A-Za-z0-9._-]*)_linux-x86_64\.run", path.name, re.IGNORECASE)
    return match[1] if match else None


def resolve(requested: str, directory: Path, explicit: str = "", *, preview: bool = False) -> tuple[Path, str]:
    if explicit:
        path = Path(explicit).absolute()
        actual = version(path)
        require(actual is not None and (not requested or actual.lower() == requested.lower()),
                f"Toolkit filename/version/architecture mismatch: {path} (requested {requested or 'auto'})")
    else:
        candidates = [(path, version(path)) for path in sorted(directory.glob("*.run")) if path.is_file()]
        compatible = [(path, value) for path, value in candidates
                      if value is not None and (not requested or value.lower() == requested.lower())]
        if len(compatible) > 1:
            listing = "\n".join(f"  {path} (CANN {value})" for path, value in compatible)
            print(f"WARNING: Multiple CANN Toolkit candidates:\n{listing}", file=sys.stderr)
            raise ToolError("Select --cann-version or an exact --toolkit path; no Toolkit was selected.")
        if not compatible:
            pattern = f"Ascend-cann-toolkit_{requested or '*'}_linux-x86_64.run"
            if not preview:
                raise missing_material("CANN Toolkit installer", pattern, directory, "--cann-version / --toolkit",
                                       [path for path, _ in candidates])
            return directory / pattern, requested
        path, actual = compatible[0]
    if actual != requested:
        print(f"Detected CANN version: {actual} ({path.name})")
    return path, actual
