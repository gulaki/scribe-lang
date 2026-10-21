"""Compiler diagnostics: what went wrong, where, and how to report it.

Every phase reports problems to a shared `Diagnostics` collector instead of
raising, so one run reports every error it can find. Each problem has a stable
code from the registry below (`E0201`), which is what tests and tooling match
on; the message text is free to improve.

Adding a check for a new language feature means registering a code here and
calling `diagnostics.error(CODE, location, ...)` from the phase that detects it.
Nothing else needs to change: formatting lives in `render.py`.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .ast import SourceLocation


class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class ErrorCode:
    """One kind of problem. `template` is filled in with `str.format`."""

    code: str
    name: str
    template: str
    severity: Severity = Severity.ERROR


CODES: dict[str, ErrorCode] = {}


def _register(code: str, name: str, template: str, severity: Severity = Severity.ERROR) -> ErrorCode:
    if code in CODES:
        raise ValueError(f"diagnostic code {code} registered twice")
    if any(existing.name == name for existing in CODES.values()):
        raise ValueError(f"diagnostic name {name!r} registered twice")
    CODES[code] = ErrorCode(code, name, template, severity)
    return CODES[code]


# Codes are grouped by hundreds and never reused or renumbered once released.
#   E00xx  driver and internal   E01xx  syntax       E02xx  names and scopes
#   E03xx  labels and goto       E04xx  literals     E05xx  types
#   E06xx  assignments

INTERNAL_ERROR = _register("E0001", "internal-error", "internal compiler error: {detail}")
CANNOT_READ_SOURCE = _register("E0002", "cannot-read-source", "cannot read {path}: {reason}")

UNEXPECTED_TOKEN = _register("E0101", "unexpected-token", "unexpected {found}; expected {expected}")
UNEXPECTED_CHARACTER = _register("E0102", "unexpected-character", "unexpected character {char}")
UNEXPECTED_END_OF_FILE = _register("E0103", "unexpected-end-of-file", "unexpected end of file; expected {expected}")
UNCLOSED_BLOCK = _register("E0104", "unclosed-block", "this block is never closed; missing '}}'")
MISPLACED_ELSE = _register("E0105", "misplaced-else", "'{word}' must be on the same line as the '}}' that closes the if block")
UNTERMINATED_STRING = _register("E0106", "unterminated-string", "unterminated string")
UNMATCHED_CLOSING_BRACE = _register("E0107", "unmatched-closing-brace", "unmatched '}}'")
INVALID_ESCAPE = _register("E0108", "invalid-escape", "invalid escape sequence '{escape}' in string")
LEADING_ZERO = _register("E0109", "leading-zero", "leading zeros are not allowed in the number {number}")

UNDECLARED_VARIABLE = _register("E0201", "undeclared-variable", "use of undeclared variable '{name}'")
RESERVED_NAME = _register("E0202", "reserved-name", "'{name}' is a reserved word and cannot be used as a {what} name")
ALREADY_DECLARED = _register("E0203", "already-declared", "'{name}' is already declared")

UNDECLARED_LABEL = _register("E0301", "undeclared-label", "goto to undeclared label '{name}'")
DUPLICATE_LABEL = _register("E0302", "duplicate-label", "duplicate label '{name}'")
GOTO_INTO_BLOCK = _register(
    "E0303", "goto-into-block",
    "goto '{name}' jumps into a nested block; a goto may only jump within its own block or out to an enclosing block",
)

NUMBER_TOO_LARGE = _register("E0401", "number-too-large", "number {value} does not fit in {type}")

TYPE_MISMATCH = _register(
    "E0501", "type-mismatch", "cannot assign a value of type {found} to '{name}', which has type {expected}",
)
NO_COMMON_TYPE = _register("E0502", "no-common-type", "'{op}' cannot mix {left} and {right}")
CONSTANT_OVERFLOW = _register("E0503", "constant-overflow", "constant expression {value} does not fit in {type}")
CONSTANT_DIVISION_BY_ZERO = _register(
    "E0504", "constant-division-by-zero", "division by zero in a constant expression",
)

ASSIGNMENT_COUNT_MISMATCH = _register(
    "E0601", "assignment-count-mismatch", "assignment has {targets} but {values}",
)
DUPLICATE_TARGET = _register(
    "E0602", "duplicate-assignment-target", "'{name}' is assigned more than once in one statement",
)


@dataclass(frozen=True)
class Span:
    """A source range. Lines and columns are 1-based; `end_column` is exclusive."""

    filename: str | None = None
    line: int | None = None
    column: int | None = None
    end_line: int | None = None
    end_column: int | None = None

    @classmethod
    def from_location(cls, location: SourceLocation | None, filename: str | None) -> Span:
        if location is None:
            return cls(filename)
        return cls(filename, location.line, location.column, location.end_line, location.end_column)


@dataclass(frozen=True)
class Note:
    """Extra context attached to a diagnostic, e.g. "first defined here"."""

    message: str
    span: Span | None = None


@dataclass(frozen=True)
class Diagnostic:
    code: ErrorCode
    message: str
    span: Span
    notes: tuple[Note, ...] = ()
    help: str | None = None

    @property
    def severity(self) -> Severity:
        return self.code.severity

    @property
    def is_error(self) -> bool:
        return self.severity is Severity.ERROR


class Diagnostics:
    """Collects diagnostics for one compilation, in the order they are found."""

    def __init__(self, filename: str | None = None):
        self.filename = filename
        self._items: list[Diagnostic] = []

    def report(
        self,
        code: ErrorCode,
        location: SourceLocation | Span | None,
        *,
        notes: tuple[tuple[str, SourceLocation | Span | None], ...] = (),
        help: str | None = None,
        **args,
    ) -> Diagnostic:
        """Record a diagnostic. `args` fill in the code's message template."""
        diagnostic = Diagnostic(
            code,
            code.template.format(**args),
            self._span(location),
            tuple(Note(message, self._span(where)) for message, where in notes),
            help,
        )
        self._items.append(diagnostic)
        return diagnostic

    # Most call sites report errors; the name reads better there.
    error = report

    def _span(self, where: SourceLocation | Span | None) -> Span:
        if isinstance(where, Span):
            return where
        return Span.from_location(where, self.filename)

    def __iter__(self):
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self._items if d.is_error]

    @property
    def has_errors(self) -> bool:
        return any(d.is_error for d in self._items)
