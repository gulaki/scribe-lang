from scribe_lang.compiler import Compiler


COMPILER = Compiler()


def test_fibonacci_compiles():
    source = '''\
print "How many fibonacci numbers do you want?"
input nums
a = 0
b = 1
while nums > 0 {
    print a
    c = a + b
    a = b
    b = c
    nums = nums - 1
}
'''
    result = COMPILER.compile(source)
    assert "#include <stdio.h>" in result.c_source
    assert "while (v_nums > 0.0f)" in result.c_source
    assert "v_c = (v_a + v_b);" in result.c_source


def test_nested_if_and_while():
    source = '''\
x = 5
if x >= 5 {
    print "yes"
    while x > 0 {
        x = x - 1
    }
}
'''
    result = COMPILER.compile(source)
    assert "if (v_x >= 5.0f)" in result.c_source
    assert "while (v_x > 0.0f)" in result.c_source


def test_parentheses_are_supported():
    result = COMPILER.compile("x = (2 + 3) * 4\nprint x\n")
    assert "((2.0f + 3.0f) * 4.0f)" in result.c_source


def error_codes(source):
    result = COMPILER.compile(source)
    assert not result.ok
    return [d.code.code for d in result.diagnostics]


def test_undeclared_read_is_rejected():
    assert error_codes("print x\n") == ["E0201"]


def test_undeclared_goto_is_rejected():
    assert error_codes("goto nowhere\n") == ["E0301"]


def test_duplicate_label_is_rejected():
    assert error_codes("label x\nlabel x\n") == ["E0302"]


def test_comments_and_blank_lines():
    result = COMPILER.compile("# comment\n\nx = 2 # inline\nprint x\n")
    assert "float v_x;" in result.c_source


def test_bad_syntax_is_rejected():
    assert error_codes("= 4\n") == ["E0101"]


def test_identifiers_that_start_with_a_keyword_are_plain_identifiers():
    source = "iffy = 1\nelsewhere = 2\nwhilex = 3\nprinter = 4\nprint iffy + elsewhere + whilex + printer\n"
    result = COMPILER.compile(source)
    for name in ("iffy", "elsewhere", "whilex", "printer"):
        assert f"float v_{name};" in result.c_source


# -- the compilation result ---------------------------------------------------

def test_successful_result_has_every_stage_and_no_diagnostics():
    result = COMPILER.compile("x = 1\nprint x\n", "ok.scribe")
    assert result.ok
    assert result.diagnostics == () and result.errors == []
    assert result.ast is not None and result.semantic_model is not None
    assert "int main(void)" in result.c_source
    assert result.filename == "ok.scribe"
    assert result.render() == ""


def test_syntax_error_stops_before_semantic_analysis():
    # `y` is undeclared too, but that is not reported once parsing failed.
    result = COMPILER.compile("print y\nx = \n")
    assert not result.ok
    assert result.ast is None and result.semantic_model is None and result.c_source is None
    assert [d.code.code for d in result.diagnostics] == ["E0101"]


def test_semantic_error_keeps_the_ast_but_emits_no_c():
    result = COMPILER.compile("print y\n")
    assert result.ast is not None and result.semantic_model is not None
    assert result.c_source is None


def test_diagnostics_are_in_source_order():
    # gotos are checked after the whole program has been read.
    result = COMPILER.compile("goto nowhere\nprint a\nprint b\n")
    assert [(d.code.code, d.span.line) for d in result.diagnostics] == [
        ("E0301", 1), ("E0201", 2), ("E0201", 3),
    ]


def test_render_text_and_json():
    import json

    result = COMPILER.compile("print a\n", "p.scribe")
    assert result.render().startswith("p.scribe:1:7: error[E0201]: use of undeclared variable 'a'\n 1 | print a\n")
    assert json.loads(result.render("json"))[0]["code"] == "E0201"


def test_write_c_does_not_write_a_file_for_a_broken_program(tmp_path):
    out = tmp_path / "out.c"
    result = COMPILER.write_c("print a\n", out)
    assert not result.ok
    assert not out.exists()


def test_write_c_writes_a_working_program(tmp_path):
    out = tmp_path / "out.c"
    assert COMPILER.write_c("print 1\n", out).ok
    assert out.read_text(encoding="utf-8") == COMPILER.compile("print 1\n").c_source
