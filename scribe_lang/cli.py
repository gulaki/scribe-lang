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
from .version import version
from .wasm import SHELLS, WasmError, default_folder, write_folder

# Exit codes. 2 is what argparse uses for a bad command line.
EXIT_OK = 0
EXIT_ERRORS = 1
EXIT_INTERNAL_ERROR = 3


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Scribe-lang compiler powered by Lark")
    p.add_argument("--version", action="version", version=f"scribe {version()}")
    p.add_argument("source", type=Path)
    p.add_argument(
        "-o", "--output", type=Path,
        help="where to write: the C file (default out.c), or for --target wasm a folder "
             "(default: next to the source, named after it)",
    )
    p.add_argument("--target", choices=["c", "wasm"], default="c", help="what to build (default: c)")
    p.add_argument(
        "--shell", choices=sorted(SHELLS),
        help="with --target wasm: where the program runs (default: node)",
    )
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


def _check_options(parser: argparse.ArgumentParser, args) -> None:
    """Options that only mean something with another one are errors without
    it, so a flag never silently does nothing."""
    if args.shell is not None and args.target != "wasm":
        parser.error("--shell needs --target wasm")
    if args.target == "wasm":
        args.shell = args.shell or "node"
    elif args.output is None:
        args.output = Path("out.c")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _check_options(parser, args)
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
    if args.target == "wasm":
        return _build_wasm(args, compiler, source, filename)
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


def _build_wasm(args, compiler: Compiler, source: str, filename: str) -> int:
    result = compiler.compile(source, filename)
    _print_diagnostics(result.diagnostics, source, args.diagnostics_format)
    if not result.ok:
        return EXIT_ERRORS
    if args.ast:
        print(result.ast)
    folder = args.output or default_folder(args.source)
    try:
        write_folder(result, args.source, folder, args.shell, args.build)
    except (WasmError, OSError) as exc:
        reason = exc.strerror if isinstance(exc, OSError) and exc.strerror else str(exc)
        print(f"scribe: error: {reason}", file=sys.stderr)
        return EXIT_ERRORS
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
