"""The WebAssembly target: a folder of generated files that Emscripten builds
into a program for Node (shell `node`).

Like the native target, Scribe only writes files. With `--build make` or
`--build ninja` it also writes the build file that runs `emcc`, so building
is `make -C folder`, and the C stays visible and auditable next to it.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .build import BUILD_SYSTEMS, BuildConfig
from .compiler import CompilationResult

# A folder Scribe wrote has this file, so a folder it did not write (or a
# native executable with the same name) is never overwritten.
MARKER = ".scribe-wasm"
_MARKER_TEXT = (
    "This folder was written by `scribe --target wasm`. Building the program\n"
    "again replaces the files Scribe wrote here.\n"
)


@dataclass(frozen=True)
class Shell:
    """Where the program runs, and what emcc needs for it."""

    name: str
    suffix: str                    # of the module emcc writes: <name><suffix>
    cflags: tuple[str, ...] = ()
    ldflags: tuple[str, ...] = ()


SHELLS = {
    # `node answer.js`; stdin, stdout and stderr are the process's own.
    "node": Shell("node", ".js", ldflags=("-sENVIRONMENT=node", "-sEXIT_RUNTIME=1")),
}


class WasmError(Exception):
    """The folder cannot be written; the message says why."""


def default_folder(source: Path) -> Path:
    """`examples/primes.scribe` -> `examples/primes`."""
    return source.with_suffix("")


def write_folder(result: CompilationResult, source: Path, folder: Path, shell: str,
                 build: str | None = None) -> list[Path]:
    """Write the program's folder; returns the files written."""
    _check_folder(folder)
    folder.mkdir(parents=True, exist_ok=True)
    name = source.stem
    spec = SHELLS[shell]
    written = [_write(folder / MARKER, _MARKER_TEXT), _write(folder / f"{name}.c", result.c_source)]
    if build is not None:
        config = BuildConfig(
            compiler="emcc",
            cflags=("-std=c11", "-O2", *spec.cflags),
            ldflags=spec.ldflags,
            libraries=result.link_libraries,
            side_outputs=(f"{name}.wasm",),
        )
        build_file = folder / ("build.ninja" if build == "ninja" else "Makefile")
        text = BUILD_SYSTEMS[build].generate(folder / f"{name}.c", folder / f"{name}{spec.suffix}", build_file, config)
        written.append(_write(build_file, text))
    return written


def _check_folder(folder: Path) -> None:
    if folder.exists() and not folder.is_dir():
        raise WasmError(f"{folder} is not a folder; choose another place with -o")
    if folder.is_dir() and any(folder.iterdir()) and not (folder / MARKER).exists():
        raise WasmError(f"{folder} was not written by scribe; choose another place with -o")


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path
