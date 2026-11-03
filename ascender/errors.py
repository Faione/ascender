"""Errors shared by workflows and their command-line boundary."""


class ToolError(Exception):
    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ToolError(message)


def missing_material(component, expected, location, option, candidates=(), summary=""):
    """Build an actionable missing-input diagnostic without performing filesystem I/O."""
    lines = [summary or f"Missing material: {component}",
             f"  Missing component: {component}", f"  Expected: {expected}",
             f"  Search location: {location}"]
    if candidates:
        lines.append("  Available/selected files (not matching the requirement):")
        lines.extend(f"    {path}" for path in candidates)
    else:
        lines.append("  Available candidates: none")
    lines.append(f"  Action: provide the expected material at this location or select it explicitly with {option}.")
    return ToolError("\n".join(lines))
