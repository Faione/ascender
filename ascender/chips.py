"""Resolve a SoC model/family to one ops installer for the selected CANN version."""
from __future__ import annotations

from pathlib import Path
import re
import sys

from .errors import ToolError, require


def model(path: Path, cann_version: str) -> str | None:
    pattern = rf"Ascend-cann-([A-Za-z0-9]+)-ops_{re.escape(cann_version)}_linux-x86_64\.run"
    match = re.fullmatch(pattern, path.name, re.IGNORECASE)
    return match[1].lower() if match else None


def matches(requested: str, actual: str, fuzzy: bool) -> bool:
    return requested == actual or bool(fuzzy and re.fullmatch(r"[0-9]+", requested)
                                      and re.fullmatch(re.escape(requested) + r"[a-z][a-z0-9]*", actual))


def resolve(requested: str, cann_version: str, directory: Path, explicit: str = "", *,
            fuzzy: bool = True, preview: bool = False) -> tuple[Path, str]:
    if explicit:
        path = Path(explicit).absolute()
        actual = model(path, cann_version)
        require(actual is not None and matches(requested, actual, fuzzy),
                f"Ops filename/model/version/architecture mismatch: {path} (requested SoC {requested})")
    else:
        candidates = [(path, model(path, cann_version)) for path in sorted(directory.glob("*.run")) if path.is_file()]
        exact = [(path, actual) for path, actual in candidates if actual == requested]
        compatible = exact or [(path, actual) for path, actual in candidates
                               if actual is not None and matches(requested, actual, fuzzy)]
        if len(compatible) > 1:
            options = "\n".join(f"  {path} (SoC {actual})" for path, actual in compatible)
            print(f"WARNING: Multiple candidates for --soc {requested}:\n{options}", file=sys.stderr)
            raise ToolError("Select a full --soc model or an exact --ops path; no ops installer was selected.")
        if not compatible:
            require(preview, f"Missing ops installer for SoC {requested}, CANN {cann_version} (linux/x86_64) in {directory}.")
            return directory / f"Ascend-cann-{requested}-ops_{cann_version}_linux-x86_64.run", requested
        path, actual = compatible[0]
    if actual != requested:
        print(f"Resolved SoC: {requested} -> {actual} ({path.name})")
    return path, actual
