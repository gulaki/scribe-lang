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
