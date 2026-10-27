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


# -- `/` is float division ---------------------------------------------------------

@pytest.mark.parametrize("source, output", [
    ("f64: a = 7 / 2\nprint a\n", "3.50\n"),
    ("print 7 / 2\n", "3.50\n"),
    ("a = 7 / 2\nprint a\n", "3.50\n"),
    ("f32: a = 1 / 4\nprint a\n", "0.25\n"),
    ("print (2 + 3) / 2\n", "2.50\n"),
    ("print 7 // 2 / 2\n", "1.50\n"),
    ("x = 7.0\nprint x / 2\n", "3.50\n"),
    ("n = 7\nprint f64(n) / 2\n", "3.50\n"),
    ("print i64(7 / 2)\n", "3\n"),
    ("print 1 / 0\n", "inf\n"),
    ("print 7 / 2 > 3\n", "true\n"),
])
def test_slash_divides_as_floats(run_scribe, source, output):
    assert run_scribe(source) == output


def test_a_constant_quotient_is_a_float():
    found, model = analyze("a = 6 / 2\n")
    assert found == []
    assert str(model.root.symbols["a"].type) == "f64"


@pytest.mark.parametrize("source, position", [
    ("n = 7\nprint n / 2\n", (2, 9)),
    ("n = 7\nm = 2\nprint n / m\n", (3, 9)),
    ("n = 7\nprint 14 / n\n", (2, 10)),
])
def test_slash_on_integers_is_an_error(source, position):
    found = analyze(source)[0]
    assert [(d.code.code, d.span.line, d.span.column) for d in found] == [("E0511", *position)]
    assert found[0].message == "'/' divides floats, not i64"
    assert "'//'" in found[0].help and "f64(" in found[0].help


def test_a_float_quotient_does_not_fit_an_integer():
    assert positions("i64: a = 7 / 2\n") == [("E0501", 1, 10)]


def test_float_division_emits_plain_c(compiler):
    c = compiler.compile("f64: a = 7 / 2\n").c_source
    assert "v_a = (7.0 / 2.0);" in c
    assert "scribe_div_i64" not in c


# -- hardening ------------------------------------------------------------------------

def test_random_expressions_match_python(build_scribe):
    """Random `//`, `%`, `+`, `-`, `*` expressions over values near zero and
    near the limits, built with -Werror and UBSan. Cases whose Python value
    leaves i64 at any step, or divides by zero, are left out: those stop the
    program and are tested above."""
    import random

    from conftest import require_ubsan

    rng = random.Random(20261023)
    values = [INT64_MIN, INT64_MIN + 1, -2**62, -10**9, -97, -8, -3, -2, -1,
              1, 2, 3, 8, 97, 10**9, 2**62, INT64_MAX - 1, INT64_MAX]
    ops = ["//", "%", "//", "%", "+", "-", "*"]

    def checked(op, x, y):
        if op in ("//", "%") and y == 0:
            raise ArithmeticError
        z = {"//": x // y if y else 0, "%": x % y if y else 0, "+": x + y, "-": x - y, "*": x * y}[op]
        if not INT64_MIN <= z <= INT64_MAX:
            raise ArithmeticError
        return z

    lines, expected = ["i64: a, b, c"], []
    while len(expected) < 300:
        a, b, c = (rng.choice(values) for _ in range(3))
        op1, op2 = rng.choice(ops), rng.choice(ops)
        try:
            # (a op1 b) op2 c, all in checked i64 steps.
            value = checked(op2, checked(op1, a, b), c)
        except ArithmeticError:
            continue
        lines.append(f"a, b, c = {a}, {b}, {c}")
        lines.append(f"print (a {op1} b) {op2} c")
        expected.append(str(value))
    proc = build_scribe("\n".join(lines) + "\n", [*require_ubsan(), "-Werror"])("")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.split() == expected


@pytest.mark.parametrize("program, message", [
    ("a = -9223372036854775808\nb = 0\nprint a % b\n", "t.scribe:3:9: runtime error: division by zero\n"),
    ("a, b, c = 5, -1, 9223372036854775807\nprint a // b + c * 2\n", "t.scribe:2:18: runtime error: integer overflow\n"),
])
def test_more_runtime_errors(run_trapping, program, message):
    assert run_trapping(program) == message


def test_guarded_remainder_never_runs(run_trapping_or_output):
    assert run_trapping_or_output("n = 0\nprint n != 0 and 10 % n == 0\n") == (0, "false\n")


@pytest.mark.parametrize("a, b", [(INT64_MAX, 1), (INT64_MAX, -1), (INT64_MIN, 1), (INT64_MIN, 2), (INT64_MIN, INT64_MAX), (INT64_MAX, INT64_MIN)])
def test_extremes(run_scribe, a, b):
    out = run_scribe(f"i64: a = {a}, b = {b}\nprint a // b\nprint a % b\n")
    assert out == f"{a // b}\n{a % b}\n"
