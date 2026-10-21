"""Turn diagnostics into text for people (gcc/clang style) or JSON for tools.

Rendering is kept apart from detection: phases only record `Diagnostic`
objects, so a new output format never touches the compiler itself.
"""
from __future__ import annotations

import json
from collections.abc import Iterable

from .diagnostics import Diagnostic, Severity, Span

_TAB_WIDTH = 4


def _where(span: Span) -> str:
    where = span.filename or "<input>"
    if span.line is not None:
        where += f":{span.line}"
        if span.column is not None:
            where += f":{span.column}"
    return where


def _excerpt(span: Span, lines: list[str]) -> list[str]:
    """The source line `span` starts on, with the span underlined."""
    if span.line is None or not 1 <= span.line <= len(lines):
        return []
    text = lines[span.line - 1]
    shown = text.expandtabs(_TAB_WIDTH)
    column = span.column or 1
    start = len(text[: column - 1].expandtabs(_TAB_WIDTH))
    if span.end_line == span.line and span.end_column is not None and span.end_column > column:
        end = len(text[: span.end_column - 1].expandtabs(_TAB_WIDTH))
    elif span.end_line is not None and span.end_line > span.line:
        end = len(shown)  # multi-line span: underline to the end of this line
    else:
        end = start + 1
    width = max(end - start, 1)
    number = str(span.line)
    gutter = " " * len(number)
    return [
        f" {number} | {shown}".rstrip(),
        f" {gutter} | {' ' * start}^{'~' * (width - 1)}",
    ]


def _summary(diagnostics: list[Diagnostic]) -> str | None:
    errors = sum(d.severity is Severity.ERROR for d in diagnostics)
    warnings = sum(d.severity is Severity.WARNING for d in diagnostics)
    parts = []
    if errors:
        parts.append(f"{errors} error{'s' if errors != 1 else ''}")
    if warnings:
        parts.append(f"{warnings} warning{'s' if warnings != 1 else ''}")
    if not parts:
        return None
    return " and ".join(parts) + " generated."


def render_text(diagnostics: Iterable[Diagnostic], source: str | None = None) -> str:
    """Render in the familiar compiler format:

        prog.scribe:2:7: error[E0201]: use of undeclared variable 'total'
         2 | print total
           |       ^~~~~
        1 error generated.
    """
    items = list(diagnostics)
    lines = source.splitlines() if source is not None else []
    out: list[str] = []
    for diag in items:
        out.append(f"{_where(diag.span)}: {diag.severity.value}[{diag.code.code}]: {diag.message}")
        out.extend(_excerpt(diag.span, lines))
        for note in diag.notes:
            if note.span is not None and note.span.line is not None:
                out.append(f"{_where(note.span)}: note: {note.message}")
                out.extend(_excerpt(note.span, lines))
            else:
                out.append(f"note: {note.message}")
        if diag.help:
            out.append(f"help: {diag.help}")
    summary = _summary(items)
    if summary:
        out.append(summary)
    return "\n".join(out) + ("\n" if out else "")
