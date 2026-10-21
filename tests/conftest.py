from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from scribe_lang.compiler import Compiler

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
C_COMPILER = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")


@pytest.fixture(scope="session")
def compiler() -> Compiler:
    return Compiler()


@pytest.fixture
def run_scribe(compiler, tmp_path):
    """Compile Teeny Tiny source all the way to a native binary and run it.

    Returns the program's stdout. The generated C is built with strict flags so
    that non-conforming output (for example a label at the end of a block)
    fails the test. Skipped when no C compiler is installed.
    """
    if C_COMPILER is None:
        pytest.skip("no C compiler (cc/gcc/clang) found on PATH")

    def run(source: str, stdin: str = "") -> str:
        result = compiler.compile(source)
        assert result.ok, result.render()
        c_file = tmp_path / "prog.c"
        c_file.write_text(result.c_source, encoding="utf-8")
        exe = tmp_path / ("prog.exe" if os.name == "nt" else "prog")
        build = subprocess.run(
            [C_COMPILER, "-std=c11", "-pedantic-errors", "-Wall", "-Wextra",
             "-o", str(exe), str(c_file)],
            capture_output=True, text=True,
        )
        assert build.returncode == 0, f"{build.stderr}\n--- generated C ---\n{result.c_source}"
        proc = subprocess.run(
            [str(exe)], input=stdin, capture_output=True, text=True, timeout=10
        )
        assert proc.returncode == 0
        return proc.stdout

    return run
