"""The compiler's version. VERSION.txt, at the top of the repository, is the
only place it is written: pyproject.toml reads it when the package is built,
and a source checkout or editable install reads it here, so the two never
disagree."""
from __future__ import annotations

from importlib import metadata
from pathlib import Path

_VERSION_FILE = Path(__file__).resolve().parent.parent / "VERSION.txt"


def version() -> str:
    try:
        return _VERSION_FILE.read_text(encoding="utf-8").strip()
    except OSError:  # installed from a wheel: no repository around it
        return metadata.version("scribe-lang")
