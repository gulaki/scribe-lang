import json

from conftest import EXAMPLES
from scribe_lang import cli
from scribe_lang.cli import main


def test_cli_compiles_an_example(tmp_path):
    out = tmp_path / "out.c"
    assert main([str(EXAMPLES / "scopes.scribe"), "-o", str(out)]) == 0
    assert "int main(void)" in out.read_text(encoding="utf-8")


def test_cli_prints_the_ast(tmp_path, capsys):
    out = tmp_path / "out.c"
    assert main([str(EXAMPLES / "classify.scribe"), "-o", str(out), "--ast"]) == 0
    assert "Elif(" in capsys.readouterr().out


def test_cli_reports_semantic_errors(tmp_path, capsys):
    src = tmp_path / "bad.scribe"
    src.write_text("{\n    y = 1\n}\nprint y\n", encoding="utf-8")
    assert main([str(src), "-o", str(tmp_path / "o.c")]) == 1
    assert "undeclared variable 'y'" in capsys.readouterr().err


def test_cli_reports_syntax_errors_for_the_old_keywords(tmp_path, capsys):
    src = tmp_path / "old.scribe"
    src.write_text("if 1 > 0 then\n    print 1\nendif\n", encoding="utf-8")
    assert main([str(src), "-o", str(tmp_path / "o.c")]) == 1
    assert "unexpected name 'then'" in capsys.readouterr().err


def write(tmp_path, text, name="prog.scribe"):
    src = tmp_path / name
    src.write_text(text, encoding="utf-8")
    return src


def test_cli_prints_every_error_in_gcc_style(tmp_path, capsys):
    src = write(tmp_path, "print a\nprint b\n")
    assert main([str(src), "-o", str(tmp_path / "o.c")]) == 1
    err = capsys.readouterr().err
    assert f"{src}:1:7: error[E0201]: use of undeclared variable 'a'\n 1 | print a\n   |       ^\n" in err
    assert f"{src}:2:7: error[E0201]: use of undeclared variable 'b'" in err
    assert err.endswith("2 errors generated.\n")


def test_cli_writes_no_c_file_on_error(tmp_path):
    out = tmp_path / "o.c"
    assert main([str(write(tmp_path, "print a\n")), "-o", str(out)]) == 1
    assert not out.exists()


def test_cli_success_is_silent(tmp_path, capsys):
    assert main([str(write(tmp_path, "print 1\n")), "-o", str(tmp_path / "o.c")]) == 0
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


def test_cli_json_diagnostics(tmp_path, capsys):
    src = write(tmp_path, "print a\n")
    assert main([str(src), "-o", str(tmp_path / "o.c"), "--diagnostics-format", "json"]) == 1
    (diag,) = json.loads(capsys.readouterr().err)
    assert diag["code"] == "E0201"
    assert diag["span"] == {"file": str(src), "line": 1, "column": 7, "end_line": 1, "end_column": 8}


def test_cli_missing_source_file(tmp_path, capsys):
    missing = tmp_path / "missing.scribe"
    assert main([str(missing), "-o", str(tmp_path / "o.c")]) == 1
    assert capsys.readouterr().err.startswith(f"{missing}: error[E0002]: cannot read {missing}: No such file")


def test_cli_source_that_is_not_utf8(tmp_path, capsys):
    src = tmp_path / "latin1.scribe"
    src.write_bytes(b'print "\xe9"\n')
    assert main([str(src), "-o", str(tmp_path / "o.c")]) == 1
    assert "error[E0002]" in capsys.readouterr().err


def test_cli_reports_a_compiler_crash_as_an_internal_error(tmp_path, capsys, monkeypatch):
    def crash(self, source, output, filename=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(cli.Compiler, "write_c", crash)
    assert main([str(write(tmp_path, "print 1\n")), "-o", str(tmp_path / "o.c")]) == cli.EXIT_INTERNAL_ERROR
    err = capsys.readouterr().err
    assert "error[E0001]: internal compiler error: RuntimeError: boom" in err
    assert "Traceback" in err


def test_cli_unwritable_output(tmp_path, capsys):
    out = tmp_path / "no-such-dir" / "o.c"
    assert main([str(write(tmp_path, "print 1\n")), "-o", str(out)]) == 1
    assert "cannot write" in capsys.readouterr().err
