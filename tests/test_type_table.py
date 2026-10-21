"""The scalar type table and the rule for mixing types (scribe_lang/types.py)."""
from fractions import Fraction
import itertools

import pytest

from scribe_lang import types
from scribe_lang.types import common_type, holds_all


@pytest.mark.parametrize("a, b, expected", [
    ("i64", "i64", "i64"),
    ("i32", "u32", "i64"),
    ("i8", "u8", "i16"),
    ("u8", "u16", "u16"),
    ("i64", "u64", None),
    ("i32", "f32", "f64"),
    ("i16", "f16", "f32"),
    ("u16", "f16", "f32"),
    ("i64", "f64", None),
    ("f32", "f64", "f64"),
    ("f16", "f32", "f32"),
])
def test_common_type_is_the_smallest_type_that_holds_both(a, b, expected):
    result = common_type(types.by_name(a), types.by_name(b))
    assert (result.name if result else None) == expected
    reverse = common_type(types.by_name(b), types.by_name(a))
    assert (reverse.name if reverse else None) == expected


def test_holds_all_is_consistent_with_the_value_ranges():
    for src, dst in itertools.product(types.NUMERIC, repeat=2):
        if holds_all(src, dst) and src.kind != "float" and dst.kind != "float":
            assert dst.min <= src.min and src.max <= dst.max, (src, dst)


def test_no_implicit_conversion_from_float_to_integer():
    for src, dst in itertools.product(types.NUMERIC, repeat=2):
        if src.kind == "float" and dst.kind != "float":
            assert not holds_all(src, dst)


@pytest.mark.parametrize("value, exact", [(2**24, True), (2**24 + 1, False), (2**24 + 2, True), (-(2**24) - 1, False)])
def test_f32_exact_integers(value, exact):
    assert (types.round_to_f32(Fraction(value)) == value) is exact


def test_f32_rounding_is_direct_not_via_double():
    # The double nearest to this decimal lies exactly halfway between two
    # floats, so rounding decimal -> double -> float picks the wrong one.
    text = "1.00000005960464477539062500000001"
    assert types.round_to_f32(Fraction(text)) == 1.0000001192092896


def test_f32_overflow_and_largest_value():
    assert types.round_to_f32(Fraction("3.4028235e38")) == 3.4028234663852886e38
    assert types.round_to_f32(Fraction(2**128)) == float("inf")
