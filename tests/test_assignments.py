"""Chained (`a = b = 0`) and multiple (`a, b = b, a`) assignment."""
from scribe_lang.types import F64, I64


def codes(compiler, source):
    return [d.code.code for d in compiler.compile(source).diagnostics]


# -- chained assignment ---------------------------------------------------------
# `a = b = c = e` means `c = e`, then `b = c`, then `a = b`: the value is
# computed once and each step is an ordinary assignment.

def test_chained_assignment_gives_every_target_the_value(run_scribe):
    assert run_scribe("a = b = c = 10\nprint a\nprint b\nprint c\n") == "10\n10\n10\n"


def test_new_targets_take_the_type_of_the_target_to_their_right(compiler):
    model = compiler.compile("x = 1.0\na = b = x = 3\n").semantic_model
    assert [model.root.symbols[n].type for n in "abx"] == [F64, F64, F64]
    model = compiler.compile("a = b = 7\n").semantic_model
    assert [model.root.symbols[n].type for n in "ab"] == [I64, I64]


def test_each_step_must_convert_losslessly(compiler):
    assert codes(compiler, "f32: f\nd = 1.0\nd = f = 2.5\n") == []
    assert codes(compiler, "f32: f\nn = 1\nn = f = 2.0\n") == ["E0501"]


def test_chained_value_is_computed_once(compiler):
    source = compiler.compile("x = 2\na = b = x * x\n").c_source
    assert source.count("scribe_mul_i64(v_x, v_x") == 1
    assert "    v_b = scribe_mul_i64(v_x, v_x, 0);\n    v_a = v_b;\n" in source


def test_a_target_named_twice_is_an_error(compiler):
    assert codes(compiler, "a = 1\na = b = a = 2\n") == ["E0602"]


# -- multiple assignment --------------------------------------------------------
# `a, b = x, y` evaluates every value first, left to right, then assigns the
# targets left to right. It is not a tuple: nothing exists after the statement.

def test_multiple_assignment(run_scribe):
    assert run_scribe("a, b = 0, 1\nprint a\nprint b\n") == "0\n1\n"


def test_swap(run_scribe):
    assert run_scribe("a, b = 1, 2\na, b = b, a\nprint a\nprint b\n") == "2\n1\n"


def test_rotation(run_scribe):
    program = "a, b, c = 1, 2, 3\na, b, c = b, c, a\nprint a\nprint b\nprint c\n"
    assert run_scribe(program) == "2\n3\n1\n"


def test_fibonacci_step(run_scribe):
    program = "a, b = 0, 1\ni = 0\nwhile i < 10 {\n    a, b = b, a + b\n    i = i + 1\n}\nprint a\n"
    assert run_scribe(program) == "55\n"


def test_each_target_is_typed_by_its_own_value(compiler):
    model = compiler.compile("n, x = 1, 2.5\n").semantic_model
    assert [model.root.symbols[name].type for name in "nx"] == [I64, F64]


def test_values_see_the_old_values_even_with_widening(run_scribe):
    program = "f = 1.0f\nd = 2.0\nf, d = 3.0f, f\nprint f\nprint d\n"
    assert run_scribe(program) == "3.00\n1.00\n"


def test_a_new_target_cannot_be_read_by_the_values(compiler):
    # Every value is evaluated before any target exists, so sequential-style
    # `temp, a, b = a, b, temp` is an error; write `a, b = b, a` instead.
    assert codes(compiler, "a, b = 1, 2\ntemp, a, b = a, b, temp\n") == ["E0201"]


def test_count_mismatch(compiler):
    assert codes(compiler, "a, b = 1\n") == ["E0601"]
    assert codes(compiler, "a = 1, 2\n") == ["E0601"]
    assert codes(compiler, "a, b = 1, 2, 3\n") == ["E0601"]


def test_a_target_named_twice_in_multiple_assignment(compiler):
    assert codes(compiler, "a, a = 1, 2\n") == ["E0602"]


def test_temporaries_only_when_a_value_reads_an_earlier_target(compiler):
    plain = compiler.compile("a, b = 0, 1\nb, a = a, 2\n").c_source
    assert "t_1" not in plain
    assert "    v_b = v_a;\n    v_a = INT64_C(2);\n" in plain
    swap = compiler.compile("a, b = 0, 1\na, b = b, a\n").c_source
    assert (
        "    {\n"
        "        int64_t t_1 = v_b;\n"
        "        int64_t t_2 = v_a;\n"
        "        v_a = t_1;\n"
        "        v_b = t_2;\n"
        "    }\n"
    ) in swap


def test_values_are_evaluated_left_to_right(run_trapping):
    program = "x = 9223372036854775807\ny = 0\nx, y = x + 1, 1 / y\n"
    assert run_trapping(program) == "t.scribe:3:10: runtime error: integer overflow\n"
    swapped = "x = 9223372036854775807\ny = 0\nx, y = 1 / y, x + 1\n"
    assert run_trapping(swapped) == "t.scribe:3:10: runtime error: division by zero\n"
