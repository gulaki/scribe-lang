from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .build import BuildConfig
from .compiler import Compiler
from .errors import CompilerError


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Teeny Tiny compiler powered by Lark")
    p.add_argument("source", type=Path)
    p.add_argument("-o", "--output", type=Path, default=Path("out.c"), help="generated C source")
    p.add_argument("--ast", action="store_true", help="print the AST")
    p.add_argument("--build", choices=["make", "ninja"], help="also generate a build file")
    p.add_argument("--build-output", type=Path, help="build file path")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        source = args.source.read_text(encoding="utf-8")
        compiler = Compiler()
        result = compiler.write_c(source, args.output, str(args.source))

        if args.ast:
            print(result.ast)

        if args.build:
            build_file = args.build_output or Path("build.ninja" if args.build == "ninja" else "Makefile")
            executable = args.output.with_suffix("")
            compiler.write_build_file(
                args.build,
                args.output,
                executable,
                build_file,
                BuildConfig(),
            )
        return 0
    except (OSError, CompilerError, KeyError) as exc:
        print(f"ttc: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
