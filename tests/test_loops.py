"""`break`, `continue` and named loops (docs/language.md, "Leaving a loop")."""
import pytest

from scribe_lang.ast import Break, Continue, While
from scribe_lang.diagnostics import Diagnostics
from scribe_lang.parser import Parser
from scribe_lang.semantics import SemanticAnalyzer

PARSER = Parser()


def parse(source):
    diagnostics = Diagnostics("t.scribe")
    program = PARSER.parse(source, diagnostics)
    assert program is not None, [d.message for d in diagnostics]
    return program


def analyze(source):
    diagnostics = Diagnostics("t.scribe")
    program = PARSER.parse(source, diagnostics)
    assert program is not None, [d.message for d in diagnostics]
    SemanticAnalyzer().analyze(program, diagnostics)
    return list(diagnostics)


def positions(source):
    return [(d.code.code, d.span.line, d.span.column) for d in analyze(source)]


# -- syntax ---------------------------------------------------------------------------

def test_a_loop_can_have_a_name():
    loop = parse("while true as rows {\n}\n").statements[0]
    assert isinstance(loop, While) and loop.name == "rows"


def test_an_unnamed_loop_has_no_name():
    assert parse("while true {\n}\n").statements[0].name is None


def test_break_and_continue_with_and_without_a_name():
    body = parse("while true as rows {\n    break\n    continue\n    break rows\n    continue rows\n}\n").statements[0].body
    assert [type(s) for s in body.statements] == [Break, Continue, Break, Continue]
    assert [s.name for s in body.statements] == [None, None, "rows", "rows"]


def test_the_name_comes_after_the_whole_condition():
    loop = parse("n = 1\nwhile n < 3 and n > 0 as counting {\n}\n").statements[1]
    assert loop.name == "counting"


@pytest.mark.parametrize("word", ["break", "continue", "as"])
def test_new_reserved_words(compiler, word):
    # `break` and `continue` start a statement, so `break = 1` is a syntax
    # error; `as` lexes as a name there and is rejected as reserved.
    found = [d.code.code for d in compiler.compile(f"{word} = 1\n").diagnostics]
    assert found in (["E0101"], ["E0202"])


# -- checks ---------------------------------------------------------------------------

def test_valid_loops_have_no_diagnostics():
    source = (
        "i = 0\nwhile i < 3 as outer {\n    j = 0\n    while j < 3 {\n"
        "        if j == 1 {\n            continue outer\n        }\n"
        "        if i == 2 {\n            break outer\n        }\n"
        "        j = j + 1\n        break\n    }\n    i = i + 1\n    continue\n}\n"
    )
    assert analyze(source) == []


@pytest.mark.parametrize("source, position", [
    ("break\n", (1, 1)),
    ("continue\n", (1, 1)),
    ("if true {\n    break\n}\n", (2, 5)),
])
def test_break_outside_a_loop(source, position):
    found = analyze(source)
    assert [(d.code.code, d.span.line, d.span.column) for d in found] == [("E0304", *position)]


def test_unknown_loop_name():
    found = analyze("while true as rows {\n    while true {\n        break cols\n    }\n}\n")
    assert [(d.code.code, d.span.line, d.span.column) for d in found] == [("E0305", 3, 15)]
    assert "rows" in found[0].help


def test_a_loop_name_is_only_visible_inside_its_loop():
    assert positions("while true as rows {\n}\nwhile true {\n    break rows\n}\n") == [("E0305", 4, 11)]


def test_a_nested_loop_cannot_reuse_an_enclosing_name():
    found = analyze("while true as rows {\n    while true as rows {\n    }\n}\n")
    assert [(d.code.code, d.span.line, d.span.column) for d in found] == [("E0306", 2, 19)]
    assert found[0].notes[0].span.line == 1


def test_sibling_loops_may_share_a_name():
    assert analyze("while true as step {\n    break step\n}\nwhile true as step {\n    break step\n}\n") == []


def test_a_loop_name_is_checked_against_reserved_words():
    assert positions("while true as print {\n}\n") == [("E0202", 1, 15)]


# -- emitted C and run time ----------------------------------------------------------

def test_innermost_break_and_continue_are_plain_c(compiler):
    c = compiler.compile("i = 0\nwhile i < 9 {\n    i = i + 1\n    if i == 2 {\n        continue\n    }\n    break\n}\n").c_source
    assert "continue;" in c and "break;" in c and "goto" not in c


def test_a_named_break_of_the_innermost_loop_is_plain_c(compiler):
    c = compiler.compile("while true as only {\n    break only\n}\n").c_source
    assert "break;" in c and "goto" not in c


def test_an_outer_target_jumps_to_a_label(compiler):
    c = compiler.compile(
        "while true as rows {\n    while true {\n        continue rows\n    }\n}\n"
        "while true as rows {\n    while true {\n        break rows\n    }\n}\n"
    ).c_source
    assert "goto continue_rows_1;" in c and "continue_rows_1:;" in c
    assert "goto break_rows_2;" in c and "break_rows_2:;" in c
    # Only labels that are jumped to are emitted (-Wunused-label).
    assert "break_rows_1" not in c and "continue_rows_2" not in c


@pytest.mark.parametrize("source, output", [
    # break inside an if, inside a loop
    ("i = 0\nwhile true {\n    i = i + 1\n    if i == 3 {\n        break\n    }\n}\nprint i\n", "3\n"),
    # continue re-tests the condition
    ("i = 0\nwhile i < 5 {\n    i = i + 1\n    if i % 2 {\n        continue\n    }\n    print i\n}\n", "2\n4\n"),
    # continue an outer loop from two levels down
    ("i = 0\nwhile i < 3 as rows {\n    i = i + 1\n    j = 0\n    while j < 3 {\n        j = j + 1\n"
     "        if j == 2 {\n            continue rows\n        }\n        print i * 10 + j\n    }\n    print 0\n}\n",
     "11\n21\n31\n"),
    # break out of three loops at once
    ("a = 0\nwhile a < 5 as all {\n    b = 0\n    while b < 5 {\n        c = 0\n        while c < 5 {\n"
     "            if a * 100 + b * 10 + c == 123 {\n                break all\n            }\n"
     "            c = c + 1\n        }\n        b = b + 1\n    }\n    a = a + 1\n}\nprint a\n", "1\n"),
    # a declaration in the loop body runs again after a continue
    ("n = 0\nwhile n < 2 {\n    n = n + 1\n    i64: count\n    count = count + n\n    print count\n    continue\n}\n",
     "1\n2\n"),
])
def test_loops_run(run_scribe, source, output):
    assert run_scribe(source) == output


def test_find_a_pair_with_named_loops(run_scribe):
    source = '''target = 11
i = 1
found = false
while i <= 9 as search {
    j = i
    while j <= 9 {
        if i * j == target * 2 {
            found = true
            break search
        }
        j = j + 1
    }
    i = i + 1
}
print found
print i
'''
    # 22 = 2 * 11 has no factor pair with both factors in 1..9.
    assert run_scribe(source) == "false\n10\n"
