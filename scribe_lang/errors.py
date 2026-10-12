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
    """Base class for compiler errors."""


class ParseError(CompilerError):
    pass


class SemanticError(CompilerError):
    pass
