"""Float floor division `//` and remainder `%` (docs/language.md, "Division
and remainder").

Both are exact on the values the floats hold, rounded once, as IEEE 754
rounds `+ - * /`:

* `x // y` is the floor of the exact quotient: `1 // 0.1` is 9, because the
  float 0.1 is a little more than one tenth (`floor(1 / 0.1)` would round the
  quotient up to 10 first). Once the quotient is past 2**53 (2**24 for f32),
  where every float is an integer, it is the rounded quotient `x / y`.
* `x % y` is `x - y * (x // y)` computed exactly, then rounded: it has the
  sign of `y`, as for integers.
* Like `/`, a zero divisor gives the IEEE 754 result instead of stopping:
  `x // 0.0` is ±inf (nan for 0 // 0), `x % 0.0` is nan.

The helpers are checked against exact rational arithmetic (`Fraction`) by a
small C harness that reads and writes hexadecimal floats, since `print` only
shows two decimals."""
import math
import os
import random
import struct
import subprocess
from fractions import Fraction

import pytest

from conftest import C_COMPILER, STRICT_FLAGS, require_ubsan
from scribe_lang.emitter import _HELPERS
from scribe_lang.types import F32, F64, round_float


# -- reference: exact arithmetic ----------------------------------------------------

def _signed_zero(negative):
    return -0.0 if negative else 0.0


def _negative(x):
    return math.copysign(1.0, x) < 0


def _round(value, t):
    """An exact value rounded once to type `t`, as a Python float."""
    rounded = round_float(value, t)
    if rounded is None:
        return -math.inf if value < 0 else math.inf
    return float(rounded)


def expected_floordiv(x, y, t):
    if math.isnan(x) or math.isnan(y):
        return math.nan
    xor = _negative(x) != _negative(y)
    if y == 0:
        return math.nan if x == 0 else (-math.inf if xor else math.inf)
    if math.isinf(x):
        return math.nan if math.isinf(y) else (-math.inf if xor else math.inf)
    if math.isinf(y):
        return -1.0 if x != 0 and xor else _signed_zero(xor)
    quotient = Fraction(x) / Fraction(y)
    rounded = _round(quotient, t) if quotient != 0 else _signed_zero(xor)
    if abs(rounded) > 2.0 ** t.mantissa:
        return rounded  # every float there is an integer
    floor = math.floor(quotient)
    return _round(Fraction(floor), t) if floor != 0 else _signed_zero(xor)


def expected_mod(x, y, t):
    if math.isnan(x) or math.isnan(y) or math.isinf(x) or y == 0:
        return math.nan
    if math.isinf(y):
        if x == 0:
            return _signed_zero(_negative(y))
        return x if _negative(x) == _negative(y) else y
    exact = Fraction(x) - Fraction(y) * math.floor(Fraction(x) / Fraction(y))
    return _round(exact, t) if exact != 0 else _signed_zero(_negative(y))


def same(a, b):
    """Equal as floats, telling -0.0 from 0.0; any nan matches any nan."""
    if math.isnan(a) or math.isnan(b):
        return math.isnan(a) and math.isnan(b)
    return a == b and _negative(a) == _negative(b)


# -- inputs ---------------------------------------------------------------------------

def to_f32(x):
    return struct.unpack("f", struct.pack("f", x))[0]


SPECIAL = [0.0, -0.0, math.inf, -math.inf, math.nan, 1.0, -1.0, 0.1, -0.1, 2.5, -7.5,
           5e-324, -5e-324, 1.7976931348623157e308, -1.7976931348623157e308, 2.0 ** 53, 3.0]

FIXED = [
    (1.0, 0.1),                                    # 9, not floor(1 / 0.1) = 10
    (6077264.882545823, 8.144928836659325e-10),    # Python's // gives one less
    (4.997117190822644e18, -564.021399676925),     # Python's // gives one less
    (-1e-100, 1e100),                              # the remainder rounds to 1e100
    (-7.5, 2.0), (7.5, -2.0), (-1e-300, 1e300), (1e300, 1e-300),
    (2.0 ** 53 - 1, 1.0), (-(2.0 ** 53) + 1, 1.0), (2.0 ** 53, 1.0 - 2.0 ** -53),
]


def random_pairs(count, seed):
    rng = random.Random(seed)
    pairs = []
    for _ in range(count):
        kind = rng.random()
        if kind < 0.5:
            # Any magnitudes, including subnormals and overflowing quotients.
            x = rng.uniform(-1, 1) * 2.0 ** rng.randint(-1074, 1023)
            y = rng.uniform(-1, 1) * 2.0 ** rng.randint(-1074, 1023)
        elif kind < 0.8:
            x = rng.uniform(-1, 1) * 10.0 ** rng.randint(-20, 20)
            y = rng.uniform(-1, 1) * 10.0 ** rng.randint(-20, 20)
        else:
            # Quotients near 2**52 ... 2**54, where rounding x / y matters most.
            y = rng.uniform(-1, 1) * 10.0 ** rng.randint(-10, 10)
            x = y * rng.uniform(2.0 ** 52, 2.0 ** 54) * rng.choice((1, -1))
        pairs.append((x, y))
    return pairs


def all_pairs(t):
    pairs = [(x, y) for x in SPECIAL for y in SPECIAL] + FIXED + random_pairs(20000, 1)
    if t is F32:
        pairs = [(to_f32(x), to_f32(y)) for x, y in pairs]
        pairs += [(x, y) for x, y in random_pairs(5000, 2) if math.isfinite(to_f32(x))]
        pairs = [(to_f32(x), to_f32(y)) for x, y in pairs]
    return pairs


# -- the C harness ----------------------------------------------------------------------

def helper_source(*names):
    """The C of the named helpers and of the helpers they need, in emitting order."""
    wanted = set()

    def need(name):
        if name not in wanted:
            wanted.add(name)
            for dependency in _HELPERS[name].needs:
                need(dependency)

    for name in names:
        need(name)
    includes = sorted({include for name in wanted for include in _HELPERS[name].includes})
    lines = [f"#include <{include}>" for include in ["stdio.h", "stdlib.h", *includes]]
    for name, helper in _HELPERS.items():
        if name in wanted:
            lines += helper.lines
    return "\n".join(lines) + "\n"


HARNESS_MAIN = {
    F64: """
int main(void) {
    char a[64], b[64];
    while (scanf("%63s %63s", a, b) == 2) {
        double x = strtod(a, NULL), y = strtod(b, NULL);
        printf("%a %a\\n", scribe_floordiv_f64(x, y), scribe_mod_f64(x, y));
    }
    return 0;
}
""",
    F32: """
int main(void) {
    char a[64], b[64];
    while (scanf("%63s %63s", a, b) == 2) {
        float x = strtof(a, NULL), y = strtof(b, NULL);
        printf("%a %a\\n", (double)scribe_floordiv_f32(x, y), (double)scribe_mod_f32(x, y));
    }
    return 0;
}
""",
}


def run_harness(t, pairs, tmp_path, flags):
    if C_COMPILER is None:
        pytest.skip("no C compiler (cc/gcc/clang) found on PATH")
    suffix = "f32" if t is F32 else "f64"
    c_file = tmp_path / f"harness_{suffix}.c"
    c_file.write_text(helper_source(f"scribe_floordiv_{suffix}", f"scribe_mod_{suffix}") + HARNESS_MAIN[t],
                      encoding="utf-8")
    exe = tmp_path / (f"harness_{suffix}.exe" if os.name == "nt" else f"harness_{suffix}")
    build = subprocess.run([C_COMPILER, *STRICT_FLAGS, "-Werror", *flags, "-o", str(exe), str(c_file), "-lm"],
                           capture_output=True, text=True)
    assert build.returncode == 0, build.stderr
    stdin = "".join(f"{x.hex()} {y.hex()}\n" for x, y in pairs)
    proc = subprocess.run([str(exe)], input=stdin, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return [tuple(float.fromhex(v) for v in line.split()) for line in proc.stdout.splitlines()]


@pytest.mark.parametrize("t", [F64, F32], ids=["f64", "f32"])
def test_helpers_are_exact(tmp_path, t):
    pairs = all_pairs(t)
    results = run_harness(t, pairs, tmp_path, require_ubsan())
    assert len(results) == len(pairs)
    wrong = [(x, y, q, r, expected_floordiv(x, y, t), expected_mod(x, y, t))
             for (x, y), (q, r) in zip(pairs, results)
             if not (same(q, expected_floordiv(x, y, t)) and same(r, expected_mod(x, y, t)))]
    assert wrong == [], f"{len(wrong)} wrong, e.g. (x, y, got //, got %, want //, want %): {wrong[:5]}"


def test_helpers_need_the_maths_library():
    for suffix in ("f64", "f32"):
        assert _HELPERS[f"scribe_floordiv_{suffix}"].libraries == ("m",)
        assert _HELPERS[f"scribe_mod_{suffix}"].libraries == ("m",)


# -- the language -----------------------------------------------------------------------

@pytest.mark.parametrize("source, fragment", [
    ("x = 7.0\ny = 2.0\nprint x // y\n", "scribe_floordiv_f64(v_x, v_y)"),
    ("x = 7.0\ny = 2.0\nprint x % y\n", "scribe_mod_f64(v_x, v_y)"),
    ("x = 7.0f\ny = 2.0f\nprint x // y\n", "scribe_floordiv_f32(v_x, v_y)"),
    ("x = 7.0f\nprint x % 2\n", "scribe_mod_f32(v_x, 2.0f)"),
    ("print 7.5 // 2\n", "scribe_floordiv_f64(7.5, 2.0)"),
])
def test_float_floor_division_and_remainder_use_the_helpers(compiler, source, fragment):
    result = compiler.compile(source)
    assert fragment in result.c_source
    assert result.link_libraries == ("m",)
    assert result.c_source.startswith("/* Link with: -lm */\n")


def test_integer_floor_division_needs_no_library(compiler):
    assert compiler.compile("a = 7\nb = 2\nprint a // b\nprint a % b\n").link_libraries == ()


@pytest.mark.parametrize("source, output", [
    ("x = 1.0\ny = 0.1\nprint x // y\nprint x % y > 0.09\n", "9.00\ntrue\n"),
    ("print 1 // 0.1\n", "9.00\n"),
    ("x = -7.5\nprint x // 2\nprint x % 2\n", "-4.00\n0.50\n"),
    ("x = 7.5\nprint x // -2\nprint x % -2\n", "-4.00\n-0.50\n"),
    ("x = 7.5f\nprint x // 2\nprint x % 2\n", "3.00\n1.50\n"),
    ("x = 7.5\ny = 0.0\nprint x // y\nprint x % y\n", "inf\nnan\n"),
    ("x = -7.5\ny = 0.0\nprint x // y\n", "-inf\n"),
    ("x = 2.5\ny = 0.5\nprint x // y * y + x % y == x\n", "true\n"),
])
def test_float_floor_division_and_remainder(run_scribe, source, output):
    assert run_scribe(source) == output
