from scribe_lang.compiler import Compiler
from scribe_lang.errors import ParseError, SemanticError


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
    assert "while ((nums > 0))" in result.c_source
    assert "c = (a + b);" in result.c_source


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
    assert "if ((x >= 5))" in result.c_source
    assert "while ((x > 0))" in result.c_source


def test_parentheses_are_supported():
    result = COMPILER.compile("x = (2 + 3) * 4\nprint x\n")
    assert "((2 + 3) * 4)" in result.c_source


def test_undeclared_read_is_rejected():
    try:
        COMPILER.compile("print x\n")
    except SemanticError as exc:
        assert "undeclared variable" in str(exc)
    else:
        raise AssertionError("expected SemanticError")


def test_undeclared_goto_is_rejected():
    try:
        COMPILER.compile("goto nowhere\n")
    except SemanticError as exc:
        assert "undeclared label" in str(exc)
    else:
        raise AssertionError("expected SemanticError")


def test_duplicate_label_is_rejected():
    try:
        COMPILER.compile("label x\nlabel x\n")
    except SemanticError as exc:
        assert "duplicate label" in str(exc)
    else:
        raise AssertionError("expected SemanticError")


def test_comments_and_blank_lines():
    result = COMPILER.compile("# comment\n\nx = 2 # inline\nprint x\n")
    assert "float x;" in result.c_source


def test_bad_syntax_is_rejected():
    try:
        COMPILER.compile("= 4\n")
    except ParseError:
        pass
    else:
        raise AssertionError("expected ParseError")


def test_identifiers_that_start_with_a_keyword_are_plain_identifiers():
    source = "iffy = 1\nelsewhere = 2\nwhilex = 3\nprinter = 4\nprint iffy + elsewhere + whilex + printer\n"
    result = COMPILER.compile(source)
    for name in ("iffy", "elsewhere", "whilex", "printer"):
        assert f"float {name};" in result.c_source
