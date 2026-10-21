from __future__ import annotations


class CompilerError(Exception):
    """Base class for compiler errors.

    Phases report problems to a `Diagnostics` collector and `Compiler.compile()`
    returns them in its result; it never raises for errors in the program.
    These exceptions are for callers that use a phase directly and want to
    stop at an error. They carry the diagnostics.
    """

    def __init__(self, message: str, diagnostics=()):
        super().__init__(message)
        self.diagnostics = list(diagnostics)


class ParseError(CompilerError):
    """Raised by `Parser.parse()` when it is called without a collector."""
