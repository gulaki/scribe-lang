from __future__ import annotations

import argparse
from pathlib import Path
import sys
import traceback

from . import diagnostics as codes
from .build import BuildConfig
from .compiler import Compiler
from .diagnostics import Diagnostics
from .render import render_json, render_text

# Exit codes. 2 is what argparse uses for a bad command line.
EXIT_OK = 0
EXIT_ERRORS = 1
EXIT_INTERNAL_ERROR = 3


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Scribe-lang compiler powered by Lark")
    p.add_argument("source", type=Path)
    p.add_argument("-o", "--output", type=Path, default=Path("out.c"), help="generated C source")
    p.add_argument("--ast", action="store_true", help="print the AST")
    p.add_argument("--build", choices=["make", "ninja"], help="also generate a build file")
    p.add_argument("--build-output", type=Path, help="build file path (default: next to the C file)")
    p.add_argument(
        "--diagnostics-format", choices=["text", "json"], default="text",
        help="how errors are printed to stderr (default: text)",
    )
    return p


def _print_diagnostics(diagnostics, source: str | None, fmt: str) -> None:
    text = render_json(diagnostics) if fmt == "json" else render_text(diagnostics, source)
    if text:
        print(text, end="", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    filename = str(args.source)
    try:
        return _run(args, filename)
    except Exception as exc:  # a bug in the compiler, not in the program
        diags = Diagnostics(filename)
        diags.error(codes.INTERNAL_ERROR, None, detail=f"{type(exc).__name__}: {exc}")
        _print_diagnostics(diags, None, args.diagnostics_format)
        traceback.print_exc(file=sys.stderr)
        return EXIT_INTERNAL_ERROR


def _run(args, filename: str) -> int:
    try:
        source = args.source.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        diags = Diagnostics(filename)
        reason = exc.strerror if isinstance(exc, OSError) and exc.strerror else str(exc)
        diags.error(codes.CANNOT_READ_SOURCE, None, path=filename, reason=reason)
        _print_diagnostics(diags, None, args.diagnostics_format)
        return EXIT_ERRORS

    compiler = Compiler()
    try:
        result = compiler.write_c(source, args.output, filename)
    except OSError as exc:
        print(f"scribe: error: cannot write {args.output}: {exc.strerror or exc}", file=sys.stderr)
        return EXIT_ERRORS
    _print_diagnostics(result.diagnostics, source, args.diagnostics_format)
    if not result.ok:
        return EXIT_ERRORS

    if args.ast:
        print(result.ast)

    if args.build:
        default_name = "build.ninja" if args.build == "ninja" else "Makefile"
        build_file = args.build_output or args.output.parent / default_name
        executable = args.output.with_suffix("")
        try:
            config = BuildConfig(libraries=result.link_libraries)
            compiler.write_build_file(args.build, args.output, executable, build_file, config)
        except OSError as exc:
            print(f"scribe: error: cannot write {build_file}: {exc.strerror or exc}", file=sys.stderr)
            return EXIT_ERRORS
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
