from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Diagnostic:
    message: str
    line: int | None = None
    column: int | None = None
    filename: str | None = None

    def format(self) -> str:
        where = ""
        if self.filename:
            where += self.filename
        if self.line is not None:
            where += f":{self.line}"
            if self.column is not None:
                where += f":{self.column}"
        if where:
            return f"{where}: error: {self.message}"
        return f"error: {self.message}"


class CompilerError(Exception):
    """Base class for compiler errors.

    Phases report problems to a Diagnostics collector. These exceptions exist
    for callers that want to stop at an error, and carry the diagnostics.
    """

    def __init__(self, message: str, diagnostics=()):
        super().__init__(message)
        self.diagnostics = list(diagnostics)


class ParseError(CompilerError):
    pass


class SemanticError(CompilerError):
    pass
