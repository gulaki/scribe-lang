"""Scribe's built-in scalar types and the rules for mixing them.

One rule decides every implicit conversion: a value of type `src` may be used
where `dst` is expected only if *every* value of `src` is exactly a value of
`dst` (`holds_all`). An operator on two different types works in the smallest
type that holds all values of both (`common_type`); when there is none, the
program must say which conversion it wants with a cast such as `f64(n)`.

The whole table is defined here even though the language does not expose every
type yet, so the rule is tested once over all of them.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True)
class ScalarType:
    name: str
    kind: str          # "int" (signed), "uint", "float" or "bool"
    bits: int
    c_name: str
    mantissa: int = 0      # floats: significand bits, including the implicit one
    max_exponent: int = 0  # floats: emax, so the largest finite value is just below 2**(emax + 1)

    @property
    def is_integer(self) -> bool:
        return self.kind in ("int", "uint")

    @property
    def is_float(self) -> bool:
        return self.kind == "float"

    @property
    def min(self) -> int:
        """Smallest value of an integer type."""
        return -(2 ** (self.bits - 1)) if self.kind == "int" else 0

    @property
    def max(self) -> int:
        """Largest value of an integer type."""
        return 2 ** (self.bits - 1) - 1 if self.kind == "int" else 2 ** self.bits - 1

    def __str__(self) -> str:
        return self.name


I8 = ScalarType("i8", "int", 8, "int8_t")
I16 = ScalarType("i16", "int", 16, "int16_t")
I32 = ScalarType("i32", "int", 32, "int32_t")
I64 = ScalarType("i64", "int", 64, "int64_t")
U8 = ScalarType("u8", "uint", 8, "uint8_t")
U16 = ScalarType("u16", "uint", 16, "uint16_t")
U32 = ScalarType("u32", "uint", 32, "uint32_t")
U64 = ScalarType("u64", "uint", 64, "uint64_t")
F16 = ScalarType("f16", "float", 16, "_Float16", mantissa=11, max_exponent=15)
F32 = ScalarType("f32", "float", 32, "float", mantissa=24, max_exponent=127)
F64 = ScalarType("f64", "float", 64, "double", mantissa=53, max_exponent=1023)
F128 = ScalarType("f128", "float", 128, "_Float128", mantissa=113, max_exponent=16383)
# Stored as one byte that is always exactly 0 or 1 (never _Bool, so a bool
# array will be one byte per element and its C type is spelled the same
# everywhere).
BOOL = ScalarType("bool", "bool", 1, "uint8_t")

# Smallest first: `common_type` picks the first entry that holds both operands.
NUMERIC = (I8, U8, I16, U16, F16, I32, U32, F32, I64, U64, F64, F128)

_BY_NAME = {t.name: t for t in (*NUMERIC, BOOL)}
_BY_NAME.update({"char": U8, "byte": U8})

# Every name reserved for a type, including ones the language cannot use yet
# (`str` arrives with arrays), so programs written today keep working later.
TYPE_NAMES = frozenset(_BY_NAME) | {"str"}

# Types a program can name today (in a declaration or a cast).
SUPPORTED = (I64, F32, F64, BOOL)

# The type of a literal that nothing else gives a type to.
DEFAULT_INT = I64
DEFAULT_FLOAT = F64


def by_name(name: str) -> ScalarType:
    return _BY_NAME[name]


def holds_all(src: ScalarType, dst: ScalarType) -> bool:
    """True if every value of `src` is exactly representable in `dst`."""
    if src == dst:
        return True
    if BOOL in (src, dst):
        return False
    if dst.is_float:
        if src.is_float:
            return dst.mantissa >= src.mantissa and dst.max_exponent >= src.max_exponent
        # Integers up to 2**mantissa in magnitude are exact.
        return max(-src.min, src.max) <= 2 ** dst.mantissa
    if src.is_float:
        return False
    return dst.min <= src.min and src.max <= dst.max


def common_type(a: ScalarType, b: ScalarType) -> ScalarType | None:
    """The smallest type holding every value of `a` and of `b`, if any.

    The result is never wider than 64 bits unless an operand already is:
    f128 holds every i64 and f64, but quietly moving i64 + f64 into slow
    software floating point would be a surprise, so that is an error.
    """
    if a == b:
        return a
    widest = max(64, a.bits, b.bits)
    for candidate in NUMERIC:
        if candidate.bits <= widest and holds_all(a, candidate) and holds_all(b, candidate):
            return candidate
    return None


def round_float(value: Fraction, t: ScalarType) -> Fraction | None:
    """`value` rounded to the nearest value of float type `t` (ties to even),
    or None if it rounds to infinity.

    Works on exact fractions, so a decimal literal is rounded once, straight to
    `t`; going through a Python float first would round twice.
    """
    if value == 0:
        return Fraction(0)
    magnitude = abs(value)
    # The binary exponent: 2**exponent <= magnitude < 2**(exponent + 1).
    exponent = magnitude.numerator.bit_length() - magnitude.denominator.bit_length()
    if magnitude < Fraction(2) ** exponent:
        exponent -= 1
    # Subnormals share the smallest normal exponent.
    exponent = max(exponent, 1 - t.max_exponent)
    ulp = Fraction(2) ** (exponent - (t.mantissa - 1))
    rounded = round(magnitude / ulp) * ulp  # Fraction rounds half to even
    if rounded >= Fraction(2) ** (t.max_exponent + 1):
        return None
    return rounded if value > 0 else -rounded


def round_to_f32(value: Fraction) -> float:
    rounded = round_float(value, F32)
    if rounded is None:
        return float("inf") if value > 0 else float("-inf")
    return float(rounded)


def integer_fits(value: int, t: ScalarType) -> bool:
    """True if the integer `value` is exactly a value of `t`."""
    if t.is_integer:
        return t.min <= value <= t.max
    if t.is_float:
        return round_float(Fraction(value), t) == value
    return False
