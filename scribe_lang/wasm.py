"""The WebAssembly target: a folder of generated files that Emscripten builds
into a program for a browser terminal (shell `web`) or for Node (shell
`node`).

Like the native target, Scribe only writes files. With `--build make` or
`--build ninja` it also writes the build file that runs `emcc`, so building
is `make -C folder`, and the C stays visible and auditable next to it.

The web shell runs the program in xterm.js with xterm-pty, which gives it a
real terminal, and is compiled with Asyncify so that `input` can wait for a
line without blocking the page. Serve the folder (`python -m http.server`)
and open it in a browser.
"""
from __future__ import annotations

import html
import json
from dataclasses import dataclass
from pathlib import Path

from .build import BUILD_SYSTEMS, BuildConfig
from .compiler import CompilationResult

_WEB = Path(__file__).resolve().parent / "web"
_VENDOR = _WEB / "vendor"

# A folder Scribe wrote has this file, so a folder it did not write (or a
# native executable with the same name) is never overwritten. It lists the
# files Scribe wrote, so building again removes ones no longer needed.
MARKER = ".scribe-wasm"
_MARKER_TEXT = (
    "This folder was written by `scribe --target wasm`. Building the program\n"
    "again replaces the files Scribe wrote here, listed below.\n\n"
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
    # index.html + scribe-term.js load answer.mjs into an xterm.js terminal.
    # SCRIBE_COLOR_ERRORS shows runtime errors in red; the terminal is
    # always a terminal, while the node shell's stderr may be a file.
    "web": Shell(
        "web", ".mjs",
        cflags=("-DSCRIBE_COLOR_ERRORS",),
        ldflags=(
            "-sENVIRONMENT=web", "-sASYNCIFY", "-sFORCE_FILESYSTEM", "-sEXIT_RUNTIME=1",
            "-sMODULARIZE", "-sEXPORT_ES6", "--js-library=emscripten-pty.js",
        ),
    ),
}

WEB_ASSETS = ("vendored", "cdn")


class WasmError(Exception):
    """The folder cannot be written; the message says why."""


def default_folder(source: Path) -> Path:
    """`examples/primes.scribe` -> `examples/primes`."""
    return source.with_suffix("")


def write_folder(result: CompilationResult, source: Path, folder: Path, shell: str,
                 build: str | None = None, web_assets: str = "vendored") -> list[Path]:
    """Write the program's folder; returns the files written."""
    previous = _check_folder(folder)
    folder.mkdir(parents=True, exist_ok=True)
    name = source.stem
    spec = SHELLS[shell]
    files: dict[str, str | bytes] = {f"{name}.c": result.c_source}
    if shell == "web":
        files.update(_web_files(name, web_assets))
    if build is not None:
        config = BuildConfig(
            compiler="emcc",
            cflags=("-std=c11", "-O2", *spec.cflags),
            ldflags=spec.ldflags,
            libraries=result.link_libraries,
            side_outputs=(f"{name}.wasm",),
        )
        build_file = "build.ninja" if build == "ninja" else "Makefile"
        files[build_file] = BUILD_SYSTEMS[build].generate(
            folder / f"{name}.c", folder / f"{name}{spec.suffix}", folder / build_file, config,
        )
    for stale in previous - set(files):
        (folder / stale).unlink(missing_ok=True)
    written = [_write(folder / MARKER, _MARKER_TEXT + "".join(f"{f}\n" for f in sorted(files)))]
    written += [_write(folder / relative, content) for relative, content in files.items()]
    return written


def _check_folder(folder: Path) -> set[str]:
    """Refuse a folder Scribe did not write; returns the files it wrote there."""
    if folder.exists() and not folder.is_dir():
        raise WasmError(f"{folder} is not a folder; choose another place with -o")
    if not folder.is_dir() or not any(folder.iterdir()):
        return set()
    marker = folder / MARKER
    if not marker.exists():
        raise WasmError(f"{folder} was not written by scribe; choose another place with -o")
    listed = marker.read_text(encoding="utf-8").split("\n\n", 1)[-1].split("\n")
    # Only plain names in this folder, whatever the marker says.
    return {line for line in listed if line and "/" not in line and "\\" not in line and line != MARKER}


def manifest() -> dict:
    """scribe_lang/web/assets.json: the third-party files and their CDN copies."""
    return json.loads((_WEB / "assets.json").read_text(encoding="utf-8"))


def _web_files(name: str, web_assets: str) -> dict[str, str | bytes]:
    files: dict[str, str | bytes] = {
        "scribe-term.js": (_WEB / "scribe-term.js").read_text(encoding="utf-8"),
        "scribe-term.css": (_WEB / "scribe-term.css").read_text(encoding="utf-8"),
    }
    styles, scripts, licenses = [], [], []
    for library in manifest()["libraries"]:
        copied = False
        for entry in library["files"]:
            file, kind = entry["file"], entry["kind"]
            if kind == "build" or web_assets == "vendored":
                files[file] = (_VENDOR / file).read_bytes()
                copied = True
            if kind == "build":
                continue
            if web_assets == "vendored":
                href = file
                extra = ""
            else:
                href = entry["url"]
                extra = f' integrity="{entry["integrity"]}" crossorigin="anonymous"'
            if kind == "style":
                styles.append(f'<link rel="stylesheet" href="{html.escape(href)}"{extra}>')
            else:
                scripts.append(f'<script src="{html.escape(href)}"{extra}></script>')
        if copied:
            text = (_VENDOR / library["license"]).read_text(encoding="utf-8")
            licenses.append(f"{library['name']} {library['version']}\n{'=' * 40}\n{text.strip()}\n")
    page = (_WEB / "index.html").read_text(encoding="utf-8")
    for placeholder, value in (
        ("{{TITLE}}", html.escape(name)),
        ("{{PROGRAM}}", html.escape(name)),
        ("{{STYLES}}", "\n".join(styles)),
        ("{{SCRIPTS}}", "\n".join(scripts)),
    ):
        page = page.replace(placeholder, value)
    files["index.html"] = page
    files["LICENSES.txt"] = "Third-party files in this folder, and their licenses.\n\n" + "\n".join(licenses)
    return files


def _write(path: Path, content: str | bytes) -> Path:
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path
