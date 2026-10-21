from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .ast import Program
from .build import BUILD_SYSTEMS, BuildConfig
from .diagnostics import Diagnostics
from .emitter import CEmitter
from .errors import ParseError, SemanticError
from .parser import Parser
from .render import render_text
from .semantics import SemanticAnalyzer, SemanticModel


@dataclass(frozen=True)
class CompilationResult:
    ast: Program
    semantic_model: SemanticModel
    c_source: str


class Compiler:
    """Orchestrates the front-end and selected backend."""

    def __init__(self, grammar_path: str | Path | None = None):
        self.parser = Parser(grammar_path)
        self.semantic = SemanticAnalyzer()

    def compile(self, source: str, filename: str | None = None) -> CompilationResult:
        diagnostics = Diagnostics(filename)
        ast = self.parser.parse(source, diagnostics)
        if ast is None:
            raise ParseError(render_text(diagnostics.errors, source), diagnostics)
        model = self.semantic.analyze(ast, diagnostics)
        if diagnostics.has_errors:
            raise SemanticError(render_text(diagnostics.errors, source), diagnostics)
        c_source = CEmitter().emit_program(ast, model)
        return CompilationResult(ast, model, c_source)

    def write_c(self, source: str, output: str | Path, filename: str | None = None) -> CompilationResult:
        result = self.compile(source, filename)
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
