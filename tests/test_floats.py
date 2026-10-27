"""Float arithmetic that ISO C only defines on IEEE 754 (Annex F) targets.

Dividing a float by zero is undefined in C11 (6.5.5p5) unless the compiler
implements Annex F, and Apple clang, for one, does not claim it. So `/` on
floats never divides by zero: a helper returns the IEEE 754 result (±inf or
nan) itself. The rest of float arithmetic relies on IEEE 754, which the
generated C checks when it is compiled."""
import subprocess

import pytest

from conftest import C_COMPILER, STRICT_FLAGS, require_ubsan


def float_division_check() -> list[str]:
    # UBSan's float-divide-by-zero check is not part of -fsanitize=undefined.
    return [*require_ubsan(), "-fsanitize=float-divide-by-zero"]


@pytest.mark.parametrize("source, output", [
    ("x = 1.0\ny = 0.0\nprint x / y\n", "inf\n"),
    ("x = -1.0\ny = 0.0\nprint x / y\n", "-inf\n"),
    ("x = 1.0\ny = -0.0\nprint x / y\n", "-inf\n"),
    ("x = -1.0\ny = -0.0\nprint x / y\n", "inf\n"),
    ("y = 0.0\nprint y / y\n", "nan\n"),
    ("x = 1.0\ny = 0.0\nz = x / y\nprint z / y\n", "inf\n"),
    ("x = 1.0f\ny = 0.0f\nprint x / y\n", "inf\n"),
    ("print 1 / 0\n", "inf\n"),
    ("print 1.0 / 0\n", "inf\n"),
    ("x = 7.0\ny = 2.0\nprint x / y\n", "3.50\n"),
])
def test_float_division_by_zero_is_defined(build_scribe, source, output):
    proc = build_scribe(source, float_division_check())("")
    assert (proc.returncode, proc.stdout) == (0, output), proc.stderr


@pytest.mark.parametrize("source, fragment", [
    ("x = 1.0\ny = 2.0\nprint x / y\n", "scribe_div_f64(v_x, v_y)"),
    ("x = 1.0f\ny = 2.0f\nprint x / y\n", "scribe_div_f32(v_x, v_y)"),
    ("print 1 / 0\n", "scribe_div_f64(1.0, 0.0)"),
    ("x = 1.0\nprint x / 2\n", "(v_x / 2.0)"),
    ("x = 1.0\nprint x / -0.5\n", "(v_x / (-0.5))"),
    ("x = 1.0\nprint x / 1e-400\n", "scribe_div_f64(v_x, 0.0"),  # the literal rounds to 0.0
])
def test_only_a_divisor_that_may_be_zero_goes_through_the_helper(compiler, source, fragment):
    assert fragment in compiler.compile(source).c_source


def test_float_division_needs_no_library(compiler):
    assert compiler.compile("x = 1.0\ny = 0.0\nprint x / y\n").link_libraries == ()
