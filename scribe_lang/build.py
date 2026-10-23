from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BuildConfig:
    compiler: str = "cc"
    cflags: tuple[str, ...] = ("-std=c11", "-O2", "-Wall", "-Wextra")
    # Libraries to link, such as ("m",) for the C maths library.
    libraries: tuple[str, ...] = ()

    @property
    def ldlibs(self) -> str:
        return " ".join(f"-l{lib}" for lib in self.libraries)


def _relative_to(path: Path, build_file: Path) -> str:
    """`path` as seen from the build file's directory.

    Make and Ninja are run from the build file's directory (`make -C dir`,
    `ninja -C dir`), so that is what every path in the build file is relative
    to, wherever the C file and executable were written.
    """
    return Path(os.path.relpath(Path(path).resolve(), Path(build_file).resolve().parent)).as_posix()


class BuildSystem:
    name = "base"

    def generate(self, source: Path, output: Path, build_file: Path, config: BuildConfig) -> str:
        raise NotImplementedError


class MakeBuildSystem(BuildSystem):
    name = "make"

    def generate(self, source: Path, output: Path, build_file: Path, config: BuildConfig) -> str:
        flags = " ".join(config.cflags)
        src = _relative_to(source, build_file)
        exe = _relative_to(output, build_file)
        return (
            f"CC ?= {config.compiler}\n"
            f"CFLAGS ?= {flags}\n"
            f"LDLIBS ?={' ' + config.ldlibs if config.ldlibs else ''}\n\n"
            f"all: {exe}\n\n"
            f"{exe}: {src}\n"
            f"\t$(CC) $(CFLAGS) -o $@ $< $(LDLIBS)\n\n"
            f"clean:\n"
            f"\trm -f {exe}\n"
        )


class NinjaBuildSystem(BuildSystem):
    name = "ninja"

    def generate(self, source: Path, output: Path, build_file: Path, config: BuildConfig) -> str:
        flags = " ".join(config.cflags)
        src = _relative_to(source, build_file)
        exe = _relative_to(output, build_file)
        return (
            f"cc = {config.compiler}\n"
            f"cflags = {flags}\n"
            f"libs ={' ' + config.ldlibs if config.ldlibs else ''}\n\n"
            f"rule cc\n"
            f"  command = $cc $cflags -o $out $in $libs\n"
            f"  description = CC $out\n\n"
            f"build {exe}: cc {src}\n"
        )


BUILD_SYSTEMS = {
    "make": MakeBuildSystem(),
    "ninja": NinjaBuildSystem(),
}
