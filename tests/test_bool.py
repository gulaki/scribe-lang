"""`bool`, truth tests, `not`/`and`/`or`, comparisons as values and comparison
chains (docs/language.md, "Booleans")."""
import pytest

from scribe_lang.diagnostics import Diagnostics
from scribe_lang.parser import Parser
from scribe_lang.semantics import SemanticAnalyzer
from scribe_lang.types import BOOL, F64, I64

PARSER = Parser()


def analyze(source):
    """Parse and type-check only (no C), as (diagnostics, model)."""
    diagnostics = Diagnostics("t.scribe")
    program = PARSER.parse(source, diagnostics)
    assert program is not None, [d.message for d in diagnostics]
    model = SemanticAnalyzer().analyze(program, diagnostics)
    return list(diagnostics), model


def codes(compiler, source):
    return [d.code.code for d in analyze(source)[0]]


def positions(compiler, source):
    return [(d.code.code, d.span.line, d.span.column) for d in analyze(source)[0]]


def diagnostics(source):
    return analyze(source)[0]


# -- types --------------------------------------------------------------------

def test_boolean_values_have_type_bool(compiler):
    source = "n = 1\nt = true\nc = n < 2\nk = not n\nj = t and c\nd = n < 2 <= 3\n"
    found, model = analyze(source)
    assert found == []
    assert [model.root.symbols[name].type for name in "tckjd"] == [BOOL] * 5


def test_bool_declaration_and_casts(compiler):
    source = "bool: f, g = true\nn = 5\nf = bool(n)\nm = i64(g)\nx = f64(true)\n"
    found, model = analyze(source)
    assert found == [], [d.message for d in found]
    assert model.root.symbols["m"].type is I64
    assert model.root.symbols["x"].type is F64


# -- truth tests: bool or integer, never float -----------------------------------

@pytest.mark.parametrize("condition", ["true", "n", "1", "not n", "n and true", "n < 2 or false"])
def test_valid_truth_tests(compiler, condition):
    assert codes(compiler, f"n = 1\nif {condition} {{\n}}\nwhile {condition} {{\n}}\n") == []


@pytest.mark.parametrize("source, position", [
    ("x = 1.0\nif x {\n}\n", (2, 4)),
    ("if 1.5 {\n}\n", (1, 4)),
    ("x = 1.0\nwhile not x {\n}\n", (2, 11)),
    ("x = 1.0\nprint true and x\n", (2, 16)),
    ("x = 1.0f\nprint x or false\n", (2, 7)),
    ("x = 1.0\nprint bool(x)\n", (2, 12)),
])
def test_a_float_is_not_a_truth_value(compiler, source, position):
    assert positions(compiler, source) == [("E0505", *position)]


def test_truth_value_error_suggests_a_comparison(compiler):
    (diag,) = diagnostics("x = 1.0\nif x {\n}\n")
    assert diag.message == "a condition must be a bool or an integer, not f64"
    assert "x != 0.0" in diag.help


# -- bool is not a number -----------------------------------------------------------

@pytest.mark.parametrize("source, position", [
    ("print true + 1\n", (1, 12)),
    ("b = true\nprint b * b\n", (2, 9)),
    ("b = true\nprint -b\n", (2, 7)),
    ("print true < false\n", (1, 12)),
    ("p, q, r = true, false, true\nprint p <= q < r\n", (2, 9)),
])
def test_arithmetic_and_ordering_on_bool_are_errors(compiler, source, position):
    assert positions(compiler, source) == [("E0506", *position)]


def test_bools_compare_for_equality(compiler):
    assert codes(compiler, "f = true\nprint f == true\nprint f != false\nprint f == f == f\n") == []


@pytest.mark.parametrize("source", ["f = true\nprint f == 1\n", "f = true\nn = 1\nprint f == n\n"])
def test_bool_and_number_do_not_compare(compiler, source):
    assert codes(compiler, source) == ["E0502"]


@pytest.mark.parametrize("source", [
    "bool: f = 1\n",
    "f = true\nf = 0\n",
    "n = 1\nn = true\n",
    "f = true\nx = 1.0\nf = x\n",
])
def test_no_implicit_conversion_to_or_from_bool(compiler, source):
    assert codes(compiler, source) == ["E0501"]


def test_assigning_a_number_to_a_bool_suggests_a_cast(compiler):
    (diag,) = diagnostics("bool: f = 1\n")
    assert diag.message == "cannot assign a value of type i64 to 'f', which has type bool"
    assert "bool(" in diag.help


def test_input_into_a_bool_is_an_error(compiler):
    (diag,) = diagnostics("bool: f\ninput f\n")
    assert (diag.code.code, diag.span.line, diag.span.column) == ("E0509", 2, 1)
    assert "bool(" in diag.help


# -- comparison chains -------------------------------------------------------------

@pytest.mark.parametrize("chain", ["a < b <= c", "a > b >= c > d", "a == b == c", "a <= b <= c <= d"])
def test_valid_chains(compiler, chain):
    assert codes(compiler, f"a, b, c, d = 1, 2, 3, 4\nprint {chain}\n") == []


@pytest.mark.parametrize("chain, code, column", [
    ("a != b != c", "E0507", 9),
    ("a == b != c", "E0507", 14),
    ("a < b > c", "E0508", 13),
    ("a <= b == c", "E0508", 14),
])
def test_invalid_chains(compiler, chain, code, column):
    assert positions(compiler, f"a, b, c = 1, 2, 3\nprint {chain}\n") == [(code, 2, column)]


def test_a_chain_compares_in_the_common_type_of_all_its_operands(compiler):
    assert codes(compiler, "f = 1.0f\nd = 2.0\nprint 0 < f < d\n") == []
    assert codes(compiler, "n = 1\nd = 2.0\nprint 0 < n < d\n") == ["E0502"]


def test_undeclared_names_in_logic_do_not_cascade(compiler):
    assert codes(compiler, "if y and not y {\n}\n") == ["E0201"]


# -- generated C ---------------------------------------------------------------

def c_source(compiler, source):
    result = compiler.compile(source)
    assert result.ok, result.render()
    return result.c_source


@pytest.mark.parametrize("program, fragment", [
    ("f = true\ng = false\n", "    v_f = 1;\n    v_g = 0;\n"),
    ("f = true\n", "uint8_t v_f;"),
    ("bool: f\n", "    v_f = 0;\n"),
    ("n = 1\nb = not n\n", "v_b = (!v_n);"),
    ("a, b = true, false\nc = a and b\n", "v_c = (v_a && v_b);"),
    ("a, b = true, false\nc = a or b\n", "v_c = (v_a || v_b);"),
    ("a, b, c = true, false, true\nd = a or b or c\n", "v_d = ((v_a || v_b) || v_c);"),
    ("a, b, c = true, false, true\nd = a and b or c\n", "v_d = ((v_a && v_b) || v_c);"),
    ("n = 1\nc = n < 2\n", "v_c = (v_n < INT64_C(2));"),
    ("n = 1\nif n {\n}\n", "    if (v_n != 0) {\n"),
    ("f = true\nif f {\n}\n", "    if (v_f) {\n"),
    ("a, b = true, false\nwhile a or b {\n    a = b = false\n}\n", "    while (v_a || v_b) {\n"),
    ("n = 1\nif not n < 2 {\n}\n", "    if (!(v_n < INT64_C(2))) {\n"),
    ("while true {\n}\n", "    while (1) {\n"),
    ("a, b, c = 1, 2, 3\nx = a < b <= c\n", "v_x = ((v_a < v_b) && (v_b <= v_c));"),
    ("n = 5\nf = bool(n)\n", "v_f = (v_n != 0);"),
    ("f = true\nn = i64(f)\n", "v_n = ((int64_t)v_f);"),
    ("f = true\nprint f\n", '    puts(v_f ? "true" : "false");\n'),
])
def test_bool_c_shapes(compiler, program, fragment):
    assert fragment in c_source(compiler, program)


def test_bool_needs_stdint(compiler):
    assert "#include <stdint.h>" in c_source(compiler, "f = true\nprint f\n")


def test_chain_middle_is_evaluated_once_through_a_temporary(compiler):
    source = c_source(compiler, "a, b, c = 1, 2, 3\nx = a < b + 1 < c\n")
    assert "int64_t t_1 = 0;" in source
    assert "v_x = ((v_a < (t_1 = scribe_add_i64(v_b, INT64_C(1), 0))) && (t_1 < v_c));" in source
    assert source.count("scribe_add_i64(v_b") == 1


def test_temporaries_are_declared_at_the_top_of_their_block(compiler):
    source = c_source(compiler, "{\n    a, b, c = 1, 2, 3\n    while a < b + 1 < c {\n        a = 9\n    }\n}\n")
    block = source[source.index("    {\n"):]
    assert block.index("int64_t t_1 = 0;") < block.index("while (")


def test_conditions_have_no_doubled_parentheses(compiler):
    source = c_source(compiler, "a, b = true, false\nif a and not b {\n}\nwhile a or b {\n    a = b = false\n}\n")
    body = source[source.index("int main"):]
    assert "if (v_a && (!v_b)) {" in body
    assert "((" not in body


# -- behaviour -----------------------------------------------------------------

def test_print_shows_true_and_false(run_scribe):
    assert run_scribe("print true\nprint false\nprint 1 < 2\nprint not 1\nbool: f\nprint f\n") == (
        "true\nfalse\ntrue\nfalse\nfalse\n"
    )


def test_integer_conditions(run_scribe):
    program = 'n = 3\nwhile n {\n    print n\n    n = n - 1\n}\nif not n {\n    print "done"\n}\n'
    assert run_scribe(program) == "3\n2\n1\ndone\n"


def test_casts_between_bool_and_numbers(run_scribe):
    program = "n = -7\nprint bool(n)\nprint bool(0)\nprint i64(true) + i64(false)\nprint f64(true)\n"
    assert run_scribe(program) == "true\nfalse\n1\n1.00\n"


@pytest.mark.parametrize("program, expected", [
    # The right side would stop the program with "division by zero".
    ('n = 0\nif n == 0 or 10 / n > 1 {\n    print "guarded"\n}\n', "guarded\n"),
    ("n = 0\nprint n != 0 and 10 / n > 1\n", "false\n"),
    ("a, b, n = true, false, 0\nprint a or (b and 10 / n > 1)\n", "true\n"),
    ("a, b, n = false, false, 0\nprint a or (b and 10 / n > 1)\n", "false\n"),
    # A chain stops at the first comparison that fails: x + 1 would overflow.
    ("x = 9223372036854775807\nprint 1 > 2 > x + 1\n", "false\n"),
    ("x = 9223372036854775807\nprint 1 > 2 > x + 1 > 0\n", "false\n"),
])
def test_short_circuit_skips_the_rest(run_trapping_or_output, program, expected):
    assert run_trapping_or_output(program) == (0, expected)


def test_needed_right_side_is_still_evaluated(run_trapping):
    assert run_trapping("n = 0\nprint n == 0 and 10 / n > 1\n") == "t.scribe:2:21: runtime error: division by zero\n"


def test_truth_table_matches_a_python_reference(run_scribe):
    # Every allowed form, over a grid of integer values. Python's own `and`,
    # `or`, `not` and chained comparisons have the same truth values.
    expressions = [
        "a < b", "a == b", "not a", "not a == b", "a and b", "a or b",
        "not a and b or a", "a or b and not a", "(a or b) and not (a and b)",
        "a < b <= 3", "a >= b > -2", "a == b == 1", "-1 < a - b < 2",
        "a * b > a + b or a == 0", "not (a < b < 3) and b",
    ]
    values = [-2, 0, 1, 3]
    lines, expected = [], []
    for a in values:
        for b in values:
            lines.append(f"a, b = {a}, {b}")
            for text in expressions:
                lines.append(f"print {text}")
                expected.append("true" if eval(text, {}, {"a": a, "b": b}) else "false")
    assert run_scribe("\n".join(lines) + "\n").splitlines() == expected
