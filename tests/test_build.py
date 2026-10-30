"""Build files: the compiler, flags and outputs come from BuildConfig, so the
same Make and Ninja generators build native programs and WebAssembly."""
import pytest

from scribe_lang.build import BUILD_SYSTEMS, BuildConfig

EMCC = BuildConfig(
    compiler="emcc",
    cflags=("-std=c11", "-O2"),
    ldflags=("-sASYNCIFY", "--js-library=emscripten-pty.js"),
    side_outputs=("prog.wasm",),
)


def generate(system, tmp_path, config):
    return BUILD_SYSTEMS[system].generate(tmp_path / "prog.c", tmp_path / "prog.mjs", tmp_path / "rules", config)


def test_makefile_passes_link_flags_and_cleans_side_outputs(tmp_path):
    text = generate("make", tmp_path, EMCC)
    assert "ifeq ($(origin CC),default)\nCC = emcc\nendif\n" in text
    assert "LDFLAGS ?= -sASYNCIFY --js-library=emscripten-pty.js\n" in text
    assert "\t$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $< $(LDLIBS)\n" in text
    assert "\trm -f prog.mjs prog.wasm\n" in text
    assert "# Also writes prog.wasm." in text


def test_ninja_declares_side_outputs_as_implicit_outputs(tmp_path):
    text = generate("ninja", tmp_path, EMCC)
    assert "ldflags = -sASYNCIFY --js-library=emscripten-pty.js\n" in text
    assert "command = $cc $cflags $ldflags -o $out $in $libs\n" in text
    assert "build prog.mjs | prog.wasm: cc prog.c\n" in text


@pytest.mark.parametrize("system, line", [("make", "LDFLAGS ?=\n"), ("ninja", "ldflags =\n")])
def test_native_builds_have_no_link_flags(tmp_path, system, line):
    text = generate(system, tmp_path, BuildConfig())
    assert line in text
    assert "|" not in text and "Also writes" not in text


def test_the_makefile_runs_the_chosen_compiler(tmp_path):
    # Make predefines CC=cc; the build file must still use its own compiler,
    # while a CC from the command line wins.
    import shutil
    import subprocess

    if shutil.which("make") is None:
        pytest.skip("make not installed")
    config = BuildConfig(compiler="my-cc")
    (tmp_path / "Makefile").write_text(generate("make", tmp_path, config), encoding="utf-8")
    (tmp_path / "prog.c").write_text("int main(void) { return 0; }\n", encoding="utf-8")
    dry = subprocess.run(["make", "-n", "-C", str(tmp_path)], capture_output=True, text=True)
    assert dry.stdout.startswith("my-cc ")
    dry = subprocess.run(["make", "-n", "-C", str(tmp_path), "CC=other-cc"], capture_output=True, text=True)
    assert dry.stdout.startswith("other-cc ")
