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
