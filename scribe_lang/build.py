from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BuildConfig:
    compiler: str = "cc"
    cflags: tuple[str, ...] = ("-std=c11", "-O2", "-Wall", "-Wextra")


class BuildSystem:
    name = "base"

    def generate(self, source: Path, output: Path, config: BuildConfig) -> str:
        raise NotImplementedError


class MakeBuildSystem(BuildSystem):
    name = "make"

    def generate(self, source: Path, output: Path, config: BuildConfig) -> str:
        flags = " ".join(config.cflags)
        return (
            f"CC ?= {config.compiler}\n"
            f"CFLAGS ?= {flags}\n\n"
            f"all: {output.name}\n\n"
            f"{output.name}: {source.name}\n"
            f"\t$(CC) $(CFLAGS) -o $@ $<\n\n"
            f"clean:\n"
            f"\trm -f {output.name}\n"
        )


class NinjaBuildSystem(BuildSystem):
    name = "ninja"

    def generate(self, source: Path, output: Path, config: BuildConfig) -> str:
        flags = " ".join(config.cflags)
        return (
            f"cc = {config.compiler}\n"
            f"cflags = {flags}\n\n"
            f"rule cc\n"
            f"  command = $cc $cflags -o $out $in\n"
            f"  description = CC $out\n\n"
            f"build {output.name}: cc {source.name}\n"
        )


BUILD_SYSTEMS = {
    "make": MakeBuildSystem(),
    "ninja": NinjaBuildSystem(),
}
