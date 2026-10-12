from conftest import EXAMPLES
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
    assert "unexpected token" in capsys.readouterr().err
