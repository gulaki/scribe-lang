"""Built-in scalar types: literals, inference, mixing rules, casts and checked
integer arithmetic (docs/design/type-system.md).

The run_scribe tests build the generated C with strict flags and run it, and
the run_trapping tests check that a runtime error stops the program with a
located message instead of reaching undefined behaviour in C.
"""
import pytest

from scribe_lang.types import F32, F64, I64


def codes(compiler, source):
    return [d.code.code for d in compiler.compile(source).diagnostics]


# -- literals -------------------------------------------------------------------

@pytest.mark.parametrize("literal, expected", [
    ("5", "5\n"), ("0x1f", "31\n"), ("0X1F", "31\n"), ("0o17", "15\n"), ("0b101", "5\n"),
    ("1_000_000", "1000000\n"), ("0", "0\n"), ("00", "0\n"),
    ("9223372036854775807", "9223372036854775807\n"),
    ("-9223372036854775808", "-9223372036854775808\n"),
])
def test_integer_literals(run_scribe, literal, expected):
    assert run_scribe(f"a = {literal}\nprint a\n") == expected


@pytest.mark.parametrize("literal, expected", [
    ("5.0", "5.00\n"), ("2.5", "2.50\n"), (".5", "0.50\n"), ("5.", "5.00\n"),
    ("1e3", "1000.00\n"), ("1_000.5", "1000.50\n"), ("2.5f", "2.50\n"), ("1e2f", "100.00\n"),
])
def test_float_literals(run_scribe, literal, expected):
    assert run_scribe(f"b = {literal}\nprint b\n") == expected


def test_leading_zero_is_rejected_with_an_explanation(compiler):
    result = compiler.compile("x = 017\n")
    assert [d.code.code for d in result.diagnostics] == ["E0109"]
    assert "0o17" in result.diagnostics[0].help


def test_literal_types(compiler):
    model = compiler.compile("a = 5\nb = 5.0\nc = 5.0f\n").semantic_model
    assert [model.root.symbols[n].type for n in "abc"] == [I64, F64, F32]


def test_integer_literal_too_large_for_i64(compiler):
    assert codes(compiler, "x = 9223372036854775808\n") == ["E0401"]


def test_float_literal_too_large(compiler):
    assert codes(compiler, "x = 1e309\n") == ["E0401"]
    assert codes(compiler, "x = 1e39f\n") == ["E0401"]


def test_integer_literal_must_be_exact_in_a_float_context(compiler):
    assert codes(compiler, "f = 1.0f\nprint f + 16777216\n") == []
    assert codes(compiler, "f = 1.0f\nprint f + 16777217\n") == ["E0401"]


# -- constant folding -----------------------------------------------------------

def test_integer_division_truncates_toward_zero(run_scribe):
    assert run_scribe("print 7 / 2\nprint -7 / 2\nx = 7\nprint x / 2\ny = -7\nprint y / 2\n") == "3\n-3\n3\n-3\n"


def test_constants_are_folded_exactly(run_scribe):
    # The intermediate 2**64 does not fit any C integer type.
    assert run_scribe("print 4294967296 * 4294967296 / 4294967296\n") == "4294967296\n"


def test_constant_overflow(compiler):
    assert codes(compiler, "print 9223372036854775807 + 1\n") == ["E0503"]


def test_constant_division_by_zero(compiler):
    assert codes(compiler, "print 1 / 0\n") == ["E0504"]


def test_float_division_by_zero_is_infinity(run_scribe):
    assert run_scribe("print 1.0 / 0\n") == "inf\n"


# -- inference and mixing -------------------------------------------------------

def test_a_variable_keeps_the_type_of_its_first_assignment(compiler):
    result = compiler.compile("a = 1\na = 2.5\n")
    assert [d.code.code for d in result.diagnostics] == ["E0501"]
    assert result.diagnostics[0].notes[0].span.line == 1


def test_integer_constant_into_a_float_variable(run_scribe):
    assert run_scribe("b = 1.0\nb = 3\nprint b\n") == "3.00\n"


def test_integer_variable_into_a_float_variable_needs_a_cast(compiler):
    assert codes(compiler, "a = 1\nb = 1.0\nb = a\n") == ["E0501"]
    assert codes(compiler, "a = 1\nb = 1.0\nb = f64(a)\n") == []


def test_f32_widens_to_f64(run_scribe):
    assert run_scribe("f = 2.5f\nd = 1.0\nd = f\nprint f + d\n") == "5.00\n"


def test_no_common_type(compiler):
    result = compiler.compile("a = 1\nb = 2.0\nprint a + b\n")
    assert [d.code.code for d in result.diagnostics] == ["E0502"]
    assert (result.diagnostics[0].span.line, result.diagnostics[0].span.column) == (3, 9)
    assert "f64(" in result.diagnostics[0].help


def test_integer_variable_and_float_literal_do_not_mix(compiler):
    assert codes(compiler, "a = 1\nprint a * 0.5\n") == ["E0502"]


def test_comparison_of_integer_and_float_needs_a_cast(compiler):
    assert codes(compiler, "a = 1\nb = 1.0\nif a < b {\n}\n") == ["E0502"]
    assert codes(compiler, "a = 1\nif a < 0.5 {\n}\n") == ["E0502"]
    assert codes(compiler, "b = 1.0\nif b < 1 {\n}\n") == []


def test_undeclared_variable_does_not_cascade_into_type_errors(compiler):
    assert codes(compiler, "x = y + 1\nx = 2.5\nprint x + 1.0\n") == ["E0201"]


def test_input_into_a_new_variable_is_f64(compiler):
    assert compiler.compile("input x\n").semantic_model.root.symbols["x"].type is F64


@pytest.mark.parametrize("stdin, expected", [
    ("42\n", "42\n"), ("-5\n", "-5\n"), ("9223372036854775807\n", "9223372036854775807\n"),
    ("9223372036854775808\n", "0\n"), ("4.5\n", "0\n"), ("abc\n", "0\n"), ("", "0\n"),
])
def test_input_into_an_integer_variable(run_scribe, stdin, expected):
    assert run_scribe("n = 0\ninput n\nprint n\n", stdin) == expected


def test_input_into_an_f32_variable(run_scribe):
    assert run_scribe("f = 0.0f\ninput f\nprint f\n", "1.5\n") == "1.50\n"


# -- casts ----------------------------------------------------------------------

def test_casts_between_integer_and_float(run_scribe):
    program = "a = 7\nb = 2.75\nprint f64(a) / 2\nprint i64(b)\nprint i64(-2.75)\nprint f32(a)\n"
    assert run_scribe(program) == "3.50\n2\n-2\n7.00\n"


def test_cast_of_integer_constant_checks_the_range(compiler):
    assert codes(compiler, "print i64(9223372036854775808)\n") == ["E0401"]
    assert codes(compiler, "print f32(1e39)\n") == ["E0401"]


def test_f64_to_f32_saturates_instead_of_undefined_behaviour(run_scribe):
    program = "d = 1.0\ninput d\nprint f32(d)\n"
    assert run_scribe(program, "1e300\n") == "inf\n"
    assert run_scribe(program, "-1e300\n") == "-inf\n"
    # Below the rounding threshold, IEEE rounding gives FLT_MAX, not infinity.
    assert run_scribe(program, "3.4028235e38\n") == "340282346638528859811704183484516925440.00\n"


def test_type_names_are_reserved(compiler):
    assert codes(compiler, "i64 = 1\n") == ["E0202"]
    assert codes(compiler, "u8 = 1\n") == ["E0202"]


# -- checked integer arithmetic -------------------------------------------------

@pytest.mark.parametrize("program, message", [
    ("x = 9223372036854775807\ny = x + 1\n", "t.scribe:2:7: runtime error: integer overflow\n"),
    ("x = -9223372036854775808\ny = x - 1\n", "t.scribe:2:7: runtime error: integer overflow\n"),
    ("x = 4294967296\ny = x * x\n", "t.scribe:2:7: runtime error: integer overflow\n"),
    ("x = -9223372036854775808\ny = -x\n", "t.scribe:2:5: runtime error: integer overflow\n"),
    ("x = -9223372036854775808\ny = x / -1\n", "t.scribe:2:7: runtime error: integer overflow\n"),
    ("x = 0\ny = 1 / x\n", "t.scribe:2:7: runtime error: division by zero\n"),
    ("d = 1.0\ninput d\nn = i64(d)\n", "t.scribe:3:5: runtime error: value out of range for i64\n"),
])
def test_runtime_errors_trap_with_a_location(run_trapping, program, message):
    assert run_trapping(program, stdin="1e300\n") == message


def test_i64_conversion_boundaries(run_scribe):
    program = "d = 1.0\ninput d\nprint i64(d)\n"
    assert run_scribe(program, "-9223372036854775808\n") == "-9223372036854775808\n"
    assert run_scribe(program, "9223372036854774784\n") == "9223372036854774784\n"


def test_arithmetic_near_the_limits_does_not_trap(run_scribe):
    program = (
        "x = 9223372036854775806\nprint x + 1\n"
        "y = -9223372036854775807\nprint y - 1\n"
        "z = 3037000499\nprint z * z\n"
        "w = -9223372036854775808\nprint w / 1\n"
    )
    assert run_scribe(program) == (
        "9223372036854775807\n-9223372036854775808\n9223372030926249001\n-9223372036854775808\n"
    )


def test_checks_are_only_emitted_when_needed(compiler):
    source = compiler.compile("x = 1.0\nprint x + 1\n").c_source
    assert "scribe_trap" not in source
    assert "scribe_add_i64" not in source
