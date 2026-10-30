"""The WebAssembly target (`--target wasm`): a folder of generated files that
Emscripten builds into a program for Node (`--shell node`) or a browser
terminal (`--shell web`). Scribe only writes files; `--build make|ninja`
adds the build file that runs emcc."""
import pytest

from scribe_lang.cli import main

PROGRAM = 'print "hi"\nn = 6\nprint n * 7\n'


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "answer.scribe"
    path.write_text(PROGRAM, encoding="utf-8")
    return path


def run_cli(*args):
    return main([str(a) for a in args])


# -- command line ---------------------------------------------------------------------

@pytest.mark.parametrize("args, message", [
    (["--shell", "node"], "--shell needs --target wasm"),
    (["--target", "c", "--shell", "node"], "--shell needs --target wasm"),
    (["--web-assets", "cdn"], "--web-assets needs --target wasm"),
    (["--target", "wasm", "--shell", "node", "--web-assets", "cdn"], "--web-assets needs --shell web"),
])
def test_options_that_need_another_option_are_errors(source, capsys, args, message):
    with pytest.raises(SystemExit) as exit_:
        run_cli(source, *args)
    assert exit_.value.code == 2
    assert message in capsys.readouterr().err


def test_the_folder_defaults_to_one_next_to_the_source(source):
    assert run_cli(source, "--target", "wasm", "--shell", "node") == 0
    folder = source.parent / "answer"
    assert sorted(p.name for p in folder.iterdir()) == [".scribe-wasm", "answer.c"]


def test_o_names_the_folder(source, tmp_path):
    assert run_cli(source, "--target", "wasm", "--shell", "node", "-o", tmp_path / "out") == 0
    assert (tmp_path / "out" / "answer.c").exists()


def test_a_folder_scribe_did_not_write_is_left_alone(source, capsys):
    folder = source.parent / "answer"
    folder.mkdir()
    (folder / "notes.txt").write_text("mine", encoding="utf-8")
    assert run_cli(source, "--target", "wasm", "--shell", "node") == 1
    assert "was not written by scribe" in capsys.readouterr().err
    assert sorted(p.name for p in folder.iterdir()) == ["notes.txt"]


def test_a_file_in_the_way_is_an_error(source, capsys):
    (source.parent / "answer").write_text("a native binary", encoding="utf-8")
    assert run_cli(source, "--target", "wasm", "--shell", "node") == 1
    assert "is not a folder" in capsys.readouterr().err


def test_building_again_replaces_the_files(source):
    assert run_cli(source, "--target", "wasm", "--shell", "node") == 0
    source.write_text('print "changed"\n', encoding="utf-8")
    assert run_cli(source, "--target", "wasm", "--shell", "node") == 0
    assert "changed" in (source.parent / "answer" / "answer.c").read_text(encoding="utf-8")


def test_errors_in_the_program_write_nothing(source, capsys):
    source.write_text("print nope\n", encoding="utf-8")
    assert run_cli(source, "--target", "wasm", "--shell", "node") == 1
    assert not (source.parent / "answer").exists()


# -- build files ---------------------------------------------------------------------------

def test_node_makefile(source):
    assert run_cli(source, "--target", "wasm", "--shell", "node", "--build", "make") == 0
    text = (source.parent / "answer" / "Makefile").read_text(encoding="utf-8")
    assert "CC = emcc\n" in text
    assert "LDFLAGS ?= -sENVIRONMENT=node -sEXIT_RUNTIME=1\n" in text
    assert "answer.js: answer.c\n" in text and "# Also writes answer.wasm." in text


def test_node_ninja(source):
    assert run_cli(source, "--target", "wasm", "--shell", "node", "--build", "ninja") == 0
    text = (source.parent / "answer" / "build.ninja").read_text(encoding="utf-8")
    assert "build answer.js | answer.wasm: cc answer.c\n" in text


def test_the_maths_library_is_linked_when_needed(source):
    source.write_text("x = 2.0\nprint x ** 0.5\n", encoding="utf-8")
    assert run_cli(source, "--target", "wasm", "--shell", "node", "--build", "make") == 0
    assert "LDLIBS ?= -lm\n" in (source.parent / "answer" / "Makefile").read_text(encoding="utf-8")


# -- the web shell ----------------------------------------------------------------------

VENDORED = ["xterm.css", "xterm.js", "addon-fit.js", "xterm-pty.js"]


def web_folder(source, *args):
    assert run_cli(source, "--target", "wasm", *args) == 0
    return source.parent / "answer"


def test_web_is_the_default_shell_and_vendors_the_libraries(source):
    folder = web_folder(source)
    names = sorted(p.name for p in folder.iterdir())
    assert names == sorted([".scribe-wasm", "answer.c", "index.html", "scribe-term.js", "scribe-term.css",
                            "emscripten-pty.js", "LICENSES.txt", *VENDORED])
    page = (folder / "index.html").read_text(encoding="utf-8")
    assert '<body data-program="answer">' in page and "<title>answer</title>" in page
    for file in VENDORED:
        assert f'"{file}"' in page
    assert "cdn.jsdelivr.net" not in page and "{{" not in page


def test_cdn_assets_are_linked_with_their_hashes(source):
    folder = web_folder(source, "--web-assets", "cdn")
    page = (folder / "index.html").read_text(encoding="utf-8")
    assert page.count('integrity="sha384-') == len(VENDORED)
    assert 'src="https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0/lib/xterm.js"' in page
    names = {p.name for p in folder.iterdir()}
    # emcc reads emscripten-pty.js, so it is copied either way.
    assert "emscripten-pty.js" in names and not names & set(VENDORED)


def test_switching_to_cdn_removes_the_vendored_copies(source):
    web_folder(source)
    folder = web_folder(source, "--web-assets", "cdn")
    assert not {p.name for p in folder.iterdir()} & set(VENDORED)


def test_the_vendored_files_match_the_manifest_hashes():
    import base64
    import hashlib
    from pathlib import Path

    from scribe_lang.wasm import manifest

    vendor = Path(__file__).resolve().parent.parent / "scribe_lang" / "web" / "vendor"
    for library in manifest()["libraries"]:
        assert (vendor / library["license"]).exists()
        for entry in library["files"]:
            data = (vendor / entry["file"]).read_bytes()
            if entry["kind"] != "build":
                digest = base64.b64encode(hashlib.sha384(data).digest()).decode()
                assert entry["integrity"] == f"sha384-{digest}", entry["file"]
                assert library["version"] in entry["url"]


def test_licenses_list_the_copied_libraries(source):
    vendored = (web_folder(source) / "LICENSES.txt").read_text(encoding="utf-8")
    assert "@xterm/xterm 5.5.0" in vendored and "xterm-pty 0.12.0" in vendored
    cdn = (web_folder(source, "--web-assets", "cdn") / "LICENSES.txt").read_text(encoding="utf-8")
    assert "xterm-pty 0.12.0" in cdn and "@xterm/xterm" not in cdn


def test_web_makefile(source):
    text = (web_folder(source, "--build", "make") / "Makefile").read_text(encoding="utf-8")
    assert "CFLAGS ?= -std=c11 -O2 -DSCRIBE_COLOR_ERRORS\n" in text
    assert "-sASYNCIFY -sFORCE_FILESYSTEM" in text and "--js-library=emscripten-pty.js" in text
    assert "answer.mjs: answer.c\n" in text


def test_the_page_script_is_valid_javascript(tmp_path):
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    script = Path(__file__).resolve().parent.parent / "scribe_lang" / "web" / "scribe-term.js"
    module = tmp_path / "scribe-term.mjs"  # node --check reads .mjs as a module
    module.write_text(script.read_text(encoding="utf-8"), encoding="utf-8")
    check = subprocess.run([node, "--check", str(module)], capture_output=True, text=True)
    assert check.returncode == 0, check.stderr


# -- red runtime errors --------------------------------------------------------------------

CRASH = "x = 9223372036854775807\ny = x + 1\n"


def test_runtime_errors_are_red_when_scribe_color_errors_is_defined(build_scribe):
    plain = build_scribe(CRASH, [])("")
    red = build_scribe(CRASH, ["-DSCRIBE_COLOR_ERRORS"])("")
    assert plain.stderr == "t.scribe:2:7: runtime error: integer overflow\n"
    assert red.stderr == "\x1b[31mt.scribe:2:7: runtime error: integer overflow\x1b[0m\n"
    assert plain.returncode != 0 and red.returncode != 0


# -- building with emcc: the same program, the same output ---------------------------------
# Every example is built for node through its generated Makefile and must
# print exactly what its native build prints. The web shell adds flags
# (Asyncify, the pty library), so a few examples are built with it too; the
# browser itself is checked by hand.

def _tools():
    import shutil

    missing = [tool for tool in ("emcc", "make", "node") if shutil.which(tool) is None]
    if missing:
        pytest.skip(f"needs {', '.join(missing)}")


def build_with_emcc(source_path, *args):
    import subprocess

    _tools()
    assert run_cli(source_path, "--target", "wasm", "--build", "make", *args) == 0
    folder = source_path.with_suffix("")
    make = subprocess.run(["make", "-C", str(folder)], capture_output=True, text=True)
    assert make.returncode == 0, make.stderr
    return folder


def run_node(folder, stdin=""):
    import subprocess

    return subprocess.run(["node", str(folder / f"{folder.name}.js")], input=stdin,
                          capture_output=True, text=True, encoding="utf-8", timeout=60)


def _example_runs():
    from test_end_to_end import EXAMPLE_RUNS

    return EXAMPLE_RUNS


@pytest.mark.parametrize("name", sorted(_example_runs()))
def test_every_example_prints_the_same_under_node(tmp_path, name):
    from conftest import EXAMPLES

    stdin, expected = _example_runs()[name]
    source_path = tmp_path / f"{name}.scribe"
    source_path.write_text((EXAMPLES / f"{name}.scribe").read_text(encoding="utf-8"), encoding="utf-8")
    run = run_node(build_with_emcc(source_path, "--shell", "node"), stdin)
    assert (run.returncode, run.stdout) == (0, expected), run.stderr


@pytest.mark.parametrize("program, message", [
    ("x = 9223372036854775807\ny = x + 1\n", "2:7: runtime error: integer overflow"),
    ("n = 0\nprint 10 // n\n", "2:10: runtime error: division by zero"),
    ("b, e = 2, -1\nprint b ** e\n", "2:9: runtime error: negative exponent"),
    ("x = 1e300\nprint i64(x)\n", "2:7: runtime error: value out of range for i64"),
])
def test_runtime_errors_are_the_same_under_node(tmp_path, program, message):
    source_path = tmp_path / "crash.scribe"
    source_path.write_text(program, encoding="utf-8")
    run = run_node(build_with_emcc(source_path, "--shell", "node"))
    assert run.returncode != 0
    # The message is the native one, uncoloured: node's stderr may be a file.
    assert run.stderr.startswith(f"{source_path}:{message}\n"), run.stderr


@pytest.mark.parametrize("name", ["sum_avg", "primes", "booleans"])
def test_examples_build_for_the_web_shell(tmp_path, name):
    from conftest import EXAMPLES

    source_path = tmp_path / f"{name}.scribe"
    source_path.write_text((EXAMPLES / f"{name}.scribe").read_text(encoding="utf-8"), encoding="utf-8")
    folder = build_with_emcc(source_path)
    assert (folder / f"{name}.mjs").stat().st_size > 0
    assert (folder / f"{name}.wasm").read_bytes()[:4] == b"\0asm"
