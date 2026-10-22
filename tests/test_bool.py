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
