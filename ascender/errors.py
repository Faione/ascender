"""Errors shared by workflows and their command-line boundary."""


class ToolError(Exception):
    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ToolError(message)
