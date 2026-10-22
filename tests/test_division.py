"""Integer floor division `//` and remainder `%` (docs/language.md,
"Division and remainder"). Both round toward negative infinity, as in Python,
so `a == (a // b) * b + a % b` and `a % b` has the sign of `b`."""
import pytest

from scribe_lang.diagnostics import Diagnostics
from scribe_lang.parser import Parser
from scribe_lang.semantics import SemanticAnalyzer
from scribe_lang.types import I64

PARSER = Parser()
INT64_MIN = -2**63
INT64_MAX = 2**63 - 1


def analyze(source):
    """Parse and type-check only (no C), as (diagnostics, model)."""
    diagnostics = Diagnostics("t.scribe")
    program = PARSER.parse(source, diagnostics)
    assert program is not None, [d.message for d in diagnostics]
    model = SemanticAnalyzer().analyze(program, diagnostics)
    return list(diagnostics), model


def positions(source):
    return [(d.code.code, d.span.line, d.span.column) for d in analyze(source)[0]]


# -- syntax and types --------------------------------------------------------------

def test_floor_division_and_remainder_bind_like_multiplication():
    # 1 + ((7 % 4) * 2) and (20 // 3) // 2: one level, grouped from the left.
    found, model = analyze("a = 1 + 7 % 4 * 2\nb = 20 // 3 // 2\nc = 2 * 9 % 4\n")
    assert found == []
    assert model.root.symbols["a"].type is I64


@pytest.mark.parametrize("source, folded", [
    ("7 // 2", 3), ("-7 // 2", -4), ("7 // -2", -4), ("-7 // -2", 3),
    ("7 % 3", 1), ("-7 % 3", 2), ("7 % -3", -2), ("-7 % -3", -1),
    ("6 // 3", 2), ("-6 % 3", 0),
    ("-9223372036854775808 % -1", 0),
    ("4294967296 * 4294967296 // 4294967296", 4294967296),
])
def test_constants_fold_like_python(run_scribe, source, folded):
    assert eval(source) == folded
    assert run_scribe(f"print {source}\n") == f"{folded}\n"


@pytest.mark.parametrize("source, position", [
    ("print 7 // 0\n", (1, 9)),
    ("print 7 % (3 - 3)\n", (1, 9)),
])
def test_constant_division_by_zero_is_an_error(source, position):
    assert positions(source) == [("E0504", *position)]


def test_constant_floor_division_overflow_is_an_error():
    assert positions("print -9223372036854775808 // -1\n") == [("E0503", 1, 7)]


@pytest.mark.parametrize("source, position, op, type_", [
    ("x = 7.0\nprint x // 2\n", (2, 9), "//", "f64"),
    ("x = 7.0\nprint x % 2\n", (2, 9), "%", "f64"),
    ("print 7.5 // 2\n", (1, 11), "//", "f64"),
    ("print 7 % 2.5\n", (1, 9), "%", "f64"),
    ("y = 1.5f\nprint y // y\n", (2, 9), "//", "f32"),
])
def test_floor_division_and_remainder_need_integers(source, position, op, type_):
    found = analyze(source)[0]
    assert [(d.code.code, d.span.line, d.span.column) for d in found] == [("E0510", *position)]
    assert found[0].message == f"'{op}' works on integers, not {type_}"
    assert "i64(x)" in found[0].help


def test_floor_division_of_a_bool_is_a_bool_error():
    assert positions("t = true\nprint t // 2\nprint 3 % t\n") == [("E0506", 2, 9), ("E0506", 3, 9)]


# -- emitted C and run time ----------------------------------------------------------

def test_floor_division_and_remainder_use_checked_helpers(compiler):
    c = compiler.compile("a = 7\nb = 2\nprint a // b\nprint a % b\n").c_source
    assert "scribe_floordiv_i64(v_a, v_b, 0)" in c
    assert "scribe_mod_i64(v_a, v_b, 1)" in c


GRID = [INT64_MIN, INT64_MIN + 1, -10, -7, -3, -2, -1, 0, 1, 2, 3, 7, 10, INT64_MAX - 1, INT64_MAX]


def test_runtime_values_match_python(run_scribe):
    """Every pair of the grid, except the ones that stop the program."""
    lines, expected = ["i64: a, b"], []
    for a in GRID:
        for b in GRID:
            if b == 0:
                continue
            lines.append(f"a, b = {a}, {b}")
            lines.append("print a % b")
            expected.append(a % b)
            if not (a == INT64_MIN and b == -1):
                lines.append("print a // b")
                expected.append(a // b)
    output = run_scribe("\n".join(lines) + "\n")
    assert output.split() == [str(v) for v in expected]


def test_division_identity_holds(run_scribe):
    lines, expected = ["i64: a, b"], []
    for a in (-17, -1, 0, 5, 23):
        for b in (-5, -3, 3, 4):
            lines.append(f"a, b = {a}, {b}")
            lines.append("print (a // b) * b + a % b == a and (a % b == 0 or (a % b < 0) == (b < 0))")
            expected.append("true")
    assert run_scribe("\n".join(lines) + "\n").split() == expected


@pytest.mark.parametrize("program, message", [
    ("i64: a = 7, b = 0\nprint a // b\n", "t.scribe:2:9: runtime error: division by zero\n"),
    ("i64: a = 7, b = 0\nprint a % b\n", "t.scribe:2:9: runtime error: division by zero\n"),
    ("i64: a = -9223372036854775808\nb = -1\nprint a // b\n", "t.scribe:3:9: runtime error: integer overflow\n"),
])
def test_runtime_errors(run_trapping, program, message):
    assert run_trapping(program) == message


def test_remainder_of_the_smallest_i64_by_minus_one_is_zero(run_trapping_or_output):
    # C's INT64_MIN % -1 is undefined; the helper must not reach it.
    assert run_trapping_or_output("i64: a = -9223372036854775808\nb = -1\nprint a % b\n") == (0, "0\n")


def test_remainder_as_a_truth_test(run_scribe):
    source = "n = 1\nwhile n <= 6 {\n    if n % 2 {\n        print n\n    }\n    n = n + 1\n}\n"
    assert run_scribe(source) == "1\n3\n5\n"
