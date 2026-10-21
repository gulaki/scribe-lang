from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from scribe_lang.compiler import Compiler

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
C_COMPILER = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")

STRICT_FLAGS = ["-std=c11", "-pedantic-errors", "-Wall", "-Wextra"]
# Any undefined behaviour the generated C reaches stops the program with a
# sanitizer report (and a nonzero exit) instead of going unnoticed.
UBSAN_FLAGS = ["-fsanitize=undefined", "-fno-sanitize-recover=all"]
# SCRIBE_SANITIZE=1 builds every end-to-end program with UBSan as well.
EXTRA_FLAGS = UBSAN_FLAGS if os.environ.get("SCRIBE_SANITIZE") == "1" else []


@pytest.fixture(scope="session")
def compiler() -> Compiler:
    return Compiler()


@pytest.fixture
def build_scribe(compiler, tmp_path):
    """Compile Scribe source to a native binary; returns a function that runs it.

    The generated C is built with strict flags so that non-conforming output
    (for example a label at the end of a block) fails the test. Skipped when
    no C compiler is installed.
    """
    if C_COMPILER is None:
        pytest.skip("no C compiler (cc/gcc/clang) found on PATH")

    def build(source: str, flags: list[str]):
        result = compiler.compile(source, filename="t.scribe")
        assert result.ok, result.render()
        c_file = tmp_path / "prog.c"
        c_file.write_text(result.c_source, encoding="utf-8")
        exe = tmp_path / ("prog.exe" if os.name == "nt" else "prog")
        build = subprocess.run(
            [C_COMPILER, *STRICT_FLAGS, *flags, "-o", str(exe), str(c_file)],
            capture_output=True, text=True,
        )
        assert build.returncode == 0, f"{build.stderr}\n--- generated C ---\n{result.c_source}"

        def run(stdin: str):
            return subprocess.run([str(exe)], input=stdin, capture_output=True, text=True, timeout=10)

        return run

    return build


@pytest.fixture
def run_scribe(build_scribe):
    """Build and run Scribe source; returns its stdout. It must exit with 0."""

    def run(source: str, stdin: str = "") -> str:
        proc = build_scribe(source, EXTRA_FLAGS)(stdin)
        assert proc.returncode == 0, proc.stderr
        return proc.stdout

    return run


@pytest.fixture
def run_trapping(build_scribe):
    """Build Scribe source with UBSan and run it, expecting a runtime error.

    Returns its stderr. A Scribe runtime check must stop the program *before*
    any undefined behaviour: if a check is missing, UBSan reports first and
    the stderr no longer matches.
    """

    def run(source: str, stdin: str = "") -> str:
        proc = build_scribe(source, UBSAN_FLAGS)(stdin)
        assert proc.returncode != 0, proc.stdout
        return proc.stderr

    return run
