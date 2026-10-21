from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .ast import Program
from .build import BUILD_SYSTEMS, BuildConfig
from .diagnostics import Diagnostic, Diagnostics
from .emitter import CEmitter
from .parser import Parser
from .render import render_json, render_text
from .semantics import SemanticAnalyzer, SemanticModel


def _position(diag: Diagnostic) -> tuple[int, int]:
    return (diag.span.line or 0, diag.span.column or 0)


@dataclass(frozen=True)
class CompilationResult:
    """Everything one compilation produced.

    `ok` is False when any error was reported. Phases only run while the
    earlier ones succeeded, so on failure the later fields are None: a syntax
    error leaves `ast` None, a semantic error leaves `c_source` None.
    """

    source: str
    filename: str | None
    diagnostics: tuple[Diagnostic, ...]
    ast: Program | None = None
    semantic_model: SemanticModel | None = None
    c_source: str | None = None

    @property
    def ok(self) -> bool:
        return not any(d.is_error for d in self.diagnostics)

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.is_error]

    def render(self, format: str = "text") -> str:
        if format == "json":
            return render_json(self.diagnostics)
        return render_text(self.diagnostics, self.source)


class Compiler:
    """Orchestrates the front-end and selected backend."""

    def __init__(self, grammar_path: str | Path | None = None):
        self.parser = Parser(grammar_path)
        self.semantic = SemanticAnalyzer()

    def compile(self, source: str, filename: str | None = None) -> CompilationResult:
        """Compile `source`. Never raises for errors in the program itself."""
        diagnostics = Diagnostics(filename)

        def result(**fields) -> CompilationResult:
            # Phases report in the order they work, e.g. gotos are checked
            # after the whole program; show them in source order.
            ordered = tuple(sorted(diagnostics, key=_position))
            return CompilationResult(source, filename, ordered, **fields)

        ast = self.parser.parse(source, diagnostics)
        if ast is None or diagnostics.has_errors:
            return result(ast=ast)
        model = self.semantic.analyze(ast, diagnostics)
        if diagnostics.has_errors:
            return result(ast=ast, semantic_model=model)
        c_source = CEmitter(filename=filename).emit_program(ast, model)
        return result(ast=ast, semantic_model=model, c_source=c_source)

    def write_c(self, source: str, output: str | Path, filename: str | None = None) -> CompilationResult:
        """Compile and, only if that succeeded, write the C file."""
        result = self.compile(source, filename)
        if result.ok:
            Path(output).write_text(result.c_source, encoding="utf-8")
        return result

    def write_build_file(
        self,
        build_system: str,
        c_source: str | Path,
        executable: str | Path,
        output: str | Path,
        config: BuildConfig | None = None,
    ) -> None:
        backend = BUILD_SYSTEMS[build_system]
        text = backend.generate(Path(c_source), Path(executable), Path(output), config or BuildConfig())
        Path(output).write_text(text, encoding="utf-8")
