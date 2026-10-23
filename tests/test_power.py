"""The power operator `**` (docs/language.md, "Powers"), and the headers and
libraries a program needs only when it uses them."""
import pytest

from scribe_lang.build import BUILD_SYSTEMS, BuildConfig


# -- includes and libraries on demand -------------------------------------------------

def test_a_program_without_input_or_output_has_no_stdio(compiler):
    result = compiler.compile("a = 1.5\nb = a * 2\n")
    assert "stdio.h" not in result.c_source
    assert result.link_libraries == ()


@pytest.mark.parametrize("source", ['print "hi"\n', "print 1\n", "i64: n\ninput n\n", "a = 9223372036854775807\nb = a + 1\n"])
def test_input_output_and_runtime_checks_include_stdio(compiler, source):
    assert compiler.compile(source).c_source.startswith("#include <stdio.h>\n")


def test_programs_without_library_functions_need_no_libraries(compiler):
    result = compiler.compile("x = 2.5\nprint x * x\nn = 7\nprint n // 2\n")
    assert result.link_libraries == ()
    assert "Link with" not in result.c_source


@pytest.mark.parametrize("system, line", [("make", "LDLIBS ?= -lm"), ("ninja", "libs = -lm")])
def test_build_files_link_the_libraries(tmp_path, system, line):
    text = BUILD_SYSTEMS[system].generate(
        tmp_path / "prog.c", tmp_path / "prog", tmp_path / "rules", BuildConfig(libraries=("m",))
    )
    assert line in text
    assert "$(LDLIBS)" in text if system == "make" else "$in $libs" in text


@pytest.mark.parametrize("system, line", [("make", "LDLIBS ?=\n"), ("ninja", "libs =\n")])
def test_build_files_without_libraries(tmp_path, system, line):
    text = BUILD_SYSTEMS[system].generate(tmp_path / "prog.c", tmp_path / "prog", tmp_path / "rules", BuildConfig())
    assert line in text


# -- syntax and types --------------------------------------------------------------

from scribe_lang.ast import Binary, Grouped, IntLit, Unary  # noqa: E402
from scribe_lang.diagnostics import Diagnostics  # noqa: E402
from scribe_lang.parser import Parser  # noqa: E402
from scribe_lang.semantics import SemanticAnalyzer  # noqa: E402
from scribe_lang.types import F32, F64, I64  # noqa: E402

PARSER = Parser()


def parse_expr(text):
    diagnostics = Diagnostics("t.scribe")
    program = PARSER.parse(f"print {text}\n", diagnostics)
    assert program is not None, [d.message for d in diagnostics]
    return program.statements[0].value


def analyze(source):
    diagnostics = Diagnostics("t.scribe")
    program = PARSER.parse(source, diagnostics)
    assert program is not None, [d.message for d in diagnostics]
    model = SemanticAnalyzer().analyze(program, diagnostics)
    return list(diagnostics), model


def positions(source):
    return [(d.code.code, d.span.line, d.span.column) for d in analyze(source)[0]]


def test_power_binds_tighter_than_a_sign_on_its_left():
    tree = parse_expr("-2 ** 2")
    assert isinstance(tree, Unary) and isinstance(tree.operand, Binary) and tree.operand.operator == "**"


def test_power_is_right_associative():
    tree = parse_expr("2 ** 3 ** 2")
    assert tree.operator == "**" and isinstance(tree.left, IntLit)
    assert isinstance(tree.right, Binary) and tree.right.operator == "**"


def test_power_binds_tighter_than_multiplication_and_takes_a_signed_exponent():
    tree = parse_expr("3 * 2 ** -1")
    assert tree.operator == "*"
    assert tree.right.operator == "**" and isinstance(tree.right.right, Unary)


def test_a_parenthesised_base_is_the_base():
    tree = parse_expr("(-2) ** 2")
    assert tree.operator == "**" and isinstance(tree.left, Grouped)


@pytest.mark.parametrize("source", ["-2 ** 2", "2 ** 3 ** 2", "(-2) ** 2", "2 ** 0", "0 ** 0", "(-1) ** 99",
                                    "(-2) ** 63", "2 ** 62 + (2 ** 62 - 1)", "3 * 2 ** 3 // 4", "-(3 ** 3)"])
def test_constants_fold_like_python(run_scribe, source):
    assert run_scribe(f"print {source}\n") == f"{eval(source)}\n"


def test_constant_power_too_large_for_i64():
    assert positions("print 2 ** 63\n") == [("E0503", 1, 7)]


def test_huge_exponent_is_rejected_quickly():
    found = analyze("print 2 ** 1000000000000000000\n")[0]
    assert [(d.code.code, d.span.line, d.span.column) for d in found] == [("E0503", 1, 7)]
    assert "2 ** 1000000000000000000" in found[0].message


def test_an_exact_power_can_be_a_float():
    assert positions("f64: x = 2 ** 1000\nprint x\n") == []


@pytest.mark.parametrize("source, position", [("print 2 ** -1\n", (1, 12)), ("print 10 ** (2 - 5)\n", (1, 14))])
def test_negative_constant_exponent_is_an_error(source, position):
    found = analyze(source)[0]
    assert [(d.code.code, d.span.line, d.span.column) for d in found] == [("E0512", *position)]
    assert ".0 ** -" in found[0].help


@pytest.mark.parametrize("source, name, type_", [
    ("n = 3\nr = n ** 2\n", "r", I64),
    ("x = 2.5\nr = x ** 2\n", "r", F64),
    ("x = 2.5f\nr = x ** 0.5\n", "r", F32),
    ("x = 2.5f\ny = 2.0\nr = x ** y\n", "r", F64),
    ("r = 2 ** 0.5\n", "r", F64),
    ("r = 2.0 ** -1\n", "r", F64),
])
def test_power_types(source, name, type_):
    found, model = analyze(source)
    assert found == []
    assert model.root.symbols[name].type is type_


@pytest.mark.parametrize("source, code, position", [
    ("n = 3\nx = 2.0\nprint x ** n\n", "E0502", (3, 9)),
    ("n = 3\nprint n ** 0.5\n", "E0502", (2, 9)),
    ("t = true\nprint t ** 2\n", "E0506", (2, 9)),
])
def test_power_type_errors(source, code, position):
    assert positions(source) == [(code, *position)]


# -- emitted C and run time ----------------------------------------------------------

INT64_MIN, INT64_MAX = -2**63, 2**63 - 1


@pytest.mark.parametrize("source, fragment", [
    ("x = 2.5\nprint x ** 2\n", "pow(v_x, 2.0)"),
    ("x = 2.5f\nprint x ** 0.5\n", "powf(v_x, 0.5f)"),
    ("x = 2.5f\ny = 2.0\nprint x ** y\n", "pow((double)v_x, v_y)"),
    ("print 2 ** 0.5\n", "pow(2.0, 0.5)"),
    ("n = 3\nprint n ** 2\n", "scribe_pow_i64(v_n, INT64_C(2), 0)"),
])
def test_power_lowering(compiler, source, fragment):
    assert fragment in compiler.compile(source).c_source


def test_float_powers_link_the_maths_library(compiler):
    result = compiler.compile("x = 2.0\nprint x ** 0.5\n")
    assert result.link_libraries == ("m",)
    assert result.c_source.startswith("/* Link with: -lm */\n#include <stdio.h>\n")
    assert "#include <math.h>" in result.c_source


def test_integer_powers_need_no_library(compiler):
    result = compiler.compile("n = 3\nprint n ** 2\nprint 2 ** 10\n")
    assert result.link_libraries == ()


@pytest.mark.parametrize("source, output", [
    ("x = 2.0\nprint x ** 0.5\n", "1.41\n"),
    ("x = 9.0f\nprint x ** 0.5\n", "3.00\n"),
    ("x = 2.0\nprint x ** -1\n", "0.50\n"),
    ("x = 10.0\nprint x ** 400\n", "inf\n"),
    ("x = 0.0\nprint x ** -1.0\n", "inf\n"),
    ("x = -8.0\nprint x ** (1 / 3) != x ** (1 / 3)\n", "true\n"),  # NaN
    ("x = -2.0\nprint x ** 3\n", "-8.00\n"),
    ("print 2 ** 0.5 * 2 ** 0.5\n", "2.00\n"),
])
def test_float_powers(run_scribe, source, output):
    assert run_scribe(source) == output


def test_integer_powers_match_python(run_scribe):
    bases = [-3, -2, -1, 0, 1, 2, 3, 7, 10]
    lines, expected = ["i64: b, e"], []
    for b in bases:
        for e in range(0, 20):
            if INT64_MIN <= b ** e <= INT64_MAX:
                lines += [f"b, e = {b}, {e}", "print b ** e"]
                expected.append(str(b ** e))
    lines += ["b, e = -2, 63", "print b ** e", "b, e = 2, 62", "print b ** e", "b, e = -1, 9223372036854775807", "print b ** e"]
    expected += [str(INT64_MIN), str(2**62), "-1"]
    assert run_scribe("\n".join(lines) + "\n").split() == expected


@pytest.mark.parametrize("program, message", [
    ("b, e = 2, 63\nprint b ** e\n", "t.scribe:2:9: runtime error: integer overflow\n"),
    ("b, e = 3037000500, 2\nprint b ** e\n", "t.scribe:2:9: runtime error: integer overflow\n"),
    ("b, e = 2, -1\nprint b ** e\n", "t.scribe:2:9: runtime error: negative exponent\n"),
    ("b, e = 1, -1\nprint b ** e\n", "t.scribe:2:9: runtime error: negative exponent\n"),
])
def test_integer_power_runtime_errors(run_trapping, program, message):
    assert run_trapping(program) == message
