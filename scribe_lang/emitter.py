from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from .ast import (
    Binary, Block, BoolLit, Break, Cast, ChainedLet, Comparison, ComparisonChain,
    Continue, Declaration, Expr, FloatLit, Goto, Grouped, If, Input, IntLit,
    Label, Let, Logical, MultiLet, Not, Print, Program, SourceLocation, Unary,
    Variable, While,
)
from . import types
from .semantics import Scope, SemanticModel
from .types import ScalarType


# Scribe names are prefixed in the generated C so that no Scribe name can
# collide with a C keyword, a name from <stdio.h> (`printf`, `EOF`, ...),
# `main`, or an identifier the C standard reserves (`__x`, `_X`). Variables and
# labels get different prefixes so the C stays easy to read.
def c_variable(name: str) -> str:
    return f"v_{name}"


def c_label(name: str) -> str:
    return f"l_{name}"


def c_float_literal(value: Fraction, t: ScalarType) -> str:
    """`value`, which must be exactly a value of float type `t`, as a C literal.

    Decimal when the shortest decimal spelling is exact. Otherwise a C99 hex
    float, because only a hex float is guaranteed to be read exactly: C11
    6.4.4.2 lets a compiler round an inexact decimal either way. The hex form
    is followed by the shortest decimal that rounds to it, for the reader.
    """
    as_double = float(value)  # exact: every f32 and f64 value is a double
    suffix = "f" if t == types.F32 else ""
    text = repr(as_double)
    if Fraction(text) == value:
        text += suffix
    else:
        mantissa, exponent = as_double.hex().split("p")
        if "." in mantissa:
            mantissa = mantissa.rstrip("0").rstrip(".")
        text = f"{mantissa}p{exponent}{suffix} /* {_shortest_decimal(value, t)} */"
    return f"({text})" if text.startswith("-") else text


def _shortest_decimal(value: Fraction, t: ScalarType) -> str:
    for digits in range(1, 18):
        text = f"{float(value):.{digits}g}"
        if types.round_float(Fraction(text), t) == value:
            return text
    return repr(float(value))


def c_int_literal(value: int, t: ScalarType) -> str:
    """An integer constant of type `t` (i64 for now).

    INT64_C gives the literal the right type even where nothing converts it,
    such as a printf argument. C has no literal for INT64_MIN: `-9223372036854775808`
    is the negation of a number that does not fit.
    """
    assert t == types.I64, t
    if value == t.min:
        return f"(-INT64_C({t.max}) - 1)"
    if value < 0:
        return f"(-INT64_C({-value}))"
    return f"INT64_C({value})"


_SIMPLE_ESCAPES = {
    "\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t",
    # Escaping `?` stops sequences like `??/` being read as trigraphs, which
    # C compilers still honour under -std=c11.
    "?": "\\?",
}


def c_string_literal(text: str) -> str:
    """`text` as a C string literal made only of printable ASCII.

    Anything else is written as three-digit octal escapes of its UTF-8 bytes,
    so the output does not depend on the C compiler's source character set.
    """
    out = []
    for ch in text:
        if ch in _SIMPLE_ESCAPES:
            out.append(_SIMPLE_ESCAPES[ch])
        elif " " <= ch <= "~":
            out.append(ch)
        else:
            out.extend(f"\\{byte:03o}" for byte in ch.encode("utf-8"))
    return '"' + "".join(out) + '"'


@dataclass(frozen=True)
class _Helper:
    """A runtime support function, emitted only when the program uses it
    (an unused static function makes the C compiler warn)."""

    lines: tuple[str, ...]
    includes: tuple[str, ...] = ()
    needs: tuple[str, ...] = ()  # other helpers it calls
    libraries: tuple[str, ...] = ()  # to link with: "m" for -lm


def _helper(code: str, includes=(), needs=(), libraries=()) -> _Helper:
    return _Helper(tuple(code.strip("\n").split("\n")) + ("",), tuple(includes), tuple(needs), tuple(libraries))


# Every check stops the program through scribe_trap, which says where in the
# Scribe source the check failed; `scribe_sites` (generated) maps the site
# number each call passes to a "file:line:column" position.
#
# The integer checks are plain ISO C comparisons done *before* the operation
# (CERT INT32-C), so the operation itself can never overflow. Compilers turn
# them into the same overflow-flag test __builtin_add_overflow would give.
#
# Helpers are listed in the order they are emitted; each one only calls
# helpers above it.
_HELPERS: dict[str, _Helper] = {
    "scribe_trap": _helper("""
/* Stops the program at a failed runtime check. */
static _Noreturn void scribe_trap(int site, const char *what) {
#ifdef SCRIBE_COLOR_ERRORS
    /* Defined by the web shell's build: its stderr is always a terminal. */
    fprintf(stderr, "\\033[31m%s: runtime error: %s\\033[0m\\n", scribe_sites[site], what);
#else
    fprintf(stderr, "%s: runtime error: %s\\n", scribe_sites[site], what);
#endif
    abort();
}
""", includes=["stdio.h", "stdlib.h"]),
    "scribe_add_i64": _helper("""
static int64_t scribe_add_i64(int64_t a, int64_t b, int site) {
    if ((b > 0 && a > INT64_MAX - b) || (b < 0 && a < INT64_MIN - b)) {
        scribe_trap(site, "integer overflow");
    }
    return a + b;
}
""", includes=["stdint.h"], needs=["scribe_trap"]),
    "scribe_sub_i64": _helper("""
static int64_t scribe_sub_i64(int64_t a, int64_t b, int site) {
    if ((b < 0 && a > INT64_MAX + b) || (b > 0 && a < INT64_MIN + b)) {
        scribe_trap(site, "integer overflow");
    }
    return a - b;
}
""", includes=["stdint.h"], needs=["scribe_trap"]),
    "scribe_mul_i64": _helper("""
static int64_t scribe_mul_i64(int64_t a, int64_t b, int site) {
    int overflow;
    if (a > 0) {
        overflow = b > 0 ? a > INT64_MAX / b : b < INT64_MIN / a;
    } else {
        overflow = b > 0 ? a < INT64_MIN / b : a != 0 && b < INT64_MAX / a;
    }
    if (overflow) {
        scribe_trap(site, "integer overflow");
    }
    return a * b;
}
""", includes=["stdint.h"], needs=["scribe_trap"]),
    # Exponentiation by squaring, every step checked. A double holds integers
    # exactly only up to 2**53, so `pow` would be wrong here. `base` is squared
    # only when a later bit needs it, and then the result is at least as large,
    # so a square that overflows means the result does too.
    "scribe_pow_i64": _helper("""
static int64_t scribe_pow_i64(int64_t base, int64_t exp, int site) {
    if (exp < 0) {
        scribe_trap(site, "negative exponent");
    }
    int64_t result = 1;
    while (exp > 0) {
        if (exp % 2 == 1) {
            result = scribe_mul_i64(result, base, site);
        }
        exp = exp / 2;
        if (exp > 0) {
            base = scribe_mul_i64(base, base, site);
        }
    }
    return result;
}
""", includes=["stdint.h"], needs=["scribe_mul_i64", "scribe_trap"]),
    # `//` and `%` round toward negative infinity, as in Python: C's `/` and
    # `%` truncate, so a nonzero remainder whose sign differs from the
    # divisor's moves one step. INT64_MIN % -1 is undefined in C (the quotient
    # overflows) although the remainder, 0, fits.
    "scribe_floordiv_i64": _helper("""
static int64_t scribe_floordiv_i64(int64_t a, int64_t b, int site) {
    if (b == 0) {
        scribe_trap(site, "division by zero");
    }
    if (a == INT64_MIN && b == -1) {
        scribe_trap(site, "integer overflow");
    }
    int64_t q = a / b;
    if (a % b != 0 && (a < 0) != (b < 0)) {
        q = q - 1;
    }
    return q;
}
""", includes=["stdint.h"], needs=["scribe_trap"]),
    "scribe_mod_i64": _helper("""
static int64_t scribe_mod_i64(int64_t a, int64_t b, int site) {
    if (b == 0) {
        scribe_trap(site, "division by zero");
    }
    if (b == -1) {
        return 0;
    }
    int64_t r = a % b;
    if (r != 0 && (r < 0) != (b < 0)) {
        r = r + b;
    }
    return r;
}
""", includes=["stdint.h"], needs=["scribe_trap"]),
    "scribe_neg_i64": _helper("""
static int64_t scribe_neg_i64(int64_t a, int site) {
    if (a == INT64_MIN) {
        scribe_trap(site, "integer overflow");
    }
    return -a;
}
""", includes=["stdint.h"], needs=["scribe_trap"]),
    # Dividing a float by zero is undefined in ISO C unless the compiler
    # implements Annex F (C11 6.5.5p5), so it never happens: a zero divisor
    # gives the IEEE 754 result directly. signbit, isnan, INFINITY and NAN
    # are macros, so this needs no -lm.
    "scribe_div_f64": _helper("""
static double scribe_div_f64(double a, double b) {
    if (b == 0.0) {
        if (a == 0.0 || isnan(a)) {
            return NAN;
        }
        return (signbit(a) != 0) != (signbit(b) != 0) ? -INFINITY : INFINITY;
    }
    return a / b;
}
""", includes=["math.h"]),
    "scribe_div_f32": _helper("""
static float scribe_div_f32(float a, float b) {
    if (b == 0.0f) {
        if (a == 0.0f || isnan(a)) {
            return NAN;
        }
        return (signbit(a) != 0) != (signbit(b) != 0) ? -INFINITY : INFINITY;
    }
    return a / b;
}
""", includes=["math.h"]),
    # `//` and `%` on floats are exact on the values the floats hold, rounded
    # once, as IEEE 754 rounds + - * /. C has no float floor division, and
    # floor(a / b) rounds the quotient first: 1 // 0.1 is 9 (0.1 is a little
    # more than one tenth), but floor(1 / 0.1) is floor(10.0).
    #
    # Quotient: d = a / b is rounded, but rounding never reverses order, so
    # with c = floor(d) the exact floor is c or c - 1. fma gives a - c*b
    # rounded once, which has the exact sign: it is c - 1 when that sign
    # differs from b's. Past 2^53 (2^24 for f32) every float is an integer
    # and d is the result, within one ulp of the exact floor.
    #
    # Remainder: fmod is always exact (C11 7.12.10.1) and has the sign of a;
    # when that differs from b's sign, adding b is the one rounding. It may
    # round to b itself: -1e-100 % 1e100 is 1e100, the nearest float.
    #
    # A nan, an infinite a or a zero b gives the IEEE 754 result directly, so
    # fmod never sees the cases C leaves implementation-defined.
    "scribe_floordiv_f64": _helper("""
static double scribe_floordiv_f64(double a, double b) {
    if (isnan(a) || isnan(b) || isinf(a) || b == 0.0) {
        return scribe_div_f64(a, b);
    }
    if (isinf(b)) {
        return a != 0.0 && (signbit(a) != 0) != (signbit(b) != 0) ? -1.0 : a / b;
    }
    double d = a / b;
    if (d > 0x1p53 || d < -0x1p53) {
        return d;
    }
    double c = floor(d);
    double t = fma(-c, b, a);
    if (t != 0.0 && (t < 0.0) != (b < 0.0)) {
        c = c - 1.0;
    }
    return c;
}
""", includes=["math.h"], needs=["scribe_div_f64"], libraries=["m"]),
    "scribe_mod_f64": _helper("""
static double scribe_mod_f64(double a, double b) {
    if (isnan(a) || isnan(b) || isinf(a) || b == 0.0) {
        return NAN;
    }
    double r = isinf(b) ? a : fmod(a, b);
    if (r == 0.0) {
        return signbit(b) != 0 ? -0.0 : 0.0;
    }
    if ((r < 0.0) != (b < 0.0)) {
        r = r + b;
    }
    return r;
}
""", includes=["math.h"], libraries=["m"]),
    "scribe_floordiv_f32": _helper("""
static float scribe_floordiv_f32(float a, float b) {
    if (isnan(a) || isnan(b) || isinf(a) || b == 0.0f) {
        return scribe_div_f32(a, b);
    }
    if (isinf(b)) {
        return a != 0.0f && (signbit(a) != 0) != (signbit(b) != 0) ? -1.0f : a / b;
    }
    float d = a / b;
    if (d > 0x1p24f || d < -0x1p24f) {
        return d;
    }
    float c = floorf(d);
    float t = fmaf(-c, b, a);
    if (t != 0.0f && (t < 0.0f) != (b < 0.0f)) {
        c = c - 1.0f;
    }
    return c;
}
""", includes=["math.h"], needs=["scribe_div_f32"], libraries=["m"]),
    "scribe_mod_f32": _helper("""
static float scribe_mod_f32(float a, float b) {
    if (isnan(a) || isnan(b) || isinf(a) || b == 0.0f) {
        return NAN;
    }
    float r = isinf(b) ? a : fmodf(a, b);
    if (r == 0.0f) {
        return signbit(b) != 0 ? -0.0f : 0.0f;
    }
    if ((r < 0.0f) != (b < 0.0f)) {
        r = r + b;
    }
    return r;
}
""", includes=["math.h"], libraries=["m"]),
    # A float -> integer conversion of a value out of range (or NaN) is
    # undefined (C11 6.3.1.4). NaN fails both comparisons; both bounds are
    # powers of two, so they are exact doubles.
    "scribe_f64_to_i64": _helper("""
static int64_t scribe_f64_to_i64(double x, int site) {
    if (!(x >= -9223372036854775808.0 && x < 9223372036854775808.0)) {
        scribe_trap(site, "value out of range for i64");
    }
    return (int64_t)x;
}
""", includes=["stdint.h"], needs=["scribe_trap"]),
    # A double -> float conversion of a value out of range is undefined (C11
    # 6.3.1.5), so handle those values here, rounding as IEEE 754 does:
    # infinity from FLT_MAX plus half an ulp (0x1.ffffffp+127) upward,
    # FLT_MAX below that.
    "scribe_f64_to_f32": _helper("""
static float scribe_f64_to_f32(double x) {
    if (x >= 0x1.ffffffp+127) {
        return INFINITY;
    }
    if (x <= -0x1.ffffffp+127) {
        return -INFINITY;
    }
    if (x > FLT_MAX) {
        return FLT_MAX;
    }
    if (x < -FLT_MAX) {
        return -FLT_MAX;
    }
    return (float)x;
}
""", includes=["float.h", "math.h"]),
    # `scanf("%f")` is undefined when the number is out of range (C11
    # 7.21.6.2), so `input` reads a whitespace-delimited token and converts
    # it with strtoll/strtod/strtof. Anything that is not a number of the
    # variable's type (text, `inf`, `nan`, `1e999`, an over-long token, end of
    # input) reads as 0, and the whole token is always consumed.
    "scribe_read_token": _helper("""
/* Reads one token into buf; returns 0 at end of input or if it does not fit. */
static int scribe_read_token(char *buf, size_t size) {
    size_t len = 0;
    int too_long = 0;
    int c = getchar();
    while (c != EOF && isspace(c)) {
        c = getchar();
    }
    while (c != EOF && !isspace(c)) {
        if (len < size - 1) {
            buf[len++] = (char)c;
        } else {
            too_long = 1;
        }
        c = getchar();
    }
    if (len == 0 || too_long) {
        return 0;
    }
    buf[len] = '\\0';
    return 1;
}
""", includes=["ctype.h", "stdio.h"]),
    "scribe_read_i64": _helper("""
/* Reads one token; returns 0 unless it is a whole number that fits in i64. */
static int64_t scribe_read_i64(void) {
    char buf[64];
    if (!scribe_read_token(buf, sizeof buf)) {
        return 0;
    }
    char *end = buf;
    errno = 0;
    long long value = strtoll(buf, &end, 10);
    if (end == buf || *end != '\\0' || errno == ERANGE) {
        return 0;
    }
#if LLONG_MAX > INT64_MAX
    if (value < INT64_MIN || value > INT64_MAX) {
        return 0;
    }
#endif
    return (int64_t)value;
}
""", includes=["errno.h", "limits.h", "stdint.h", "stdlib.h"], needs=["scribe_read_token"]),
    "scribe_read_f64": _helper("""
/* Reads one token; returns 0 unless it is a finite f64. */
static double scribe_read_f64(void) {
    char buf[64];
    if (!scribe_read_token(buf, sizeof buf)) {
        return 0;
    }
    char *end = buf;
    errno = 0;
    double value = strtod(buf, &end);
    if (end == buf || *end != '\\0' || errno == ERANGE || !isfinite(value)) {
        return 0;
    }
    return value;
}
""", includes=["errno.h", "math.h", "stdlib.h"], needs=["scribe_read_token"]),
    "scribe_read_f32": _helper("""
/* Reads one token; returns 0 unless it is a finite f32. */
static float scribe_read_f32(void) {
    char buf[64];
    if (!scribe_read_token(buf, sizeof buf)) {
        return 0;
    }
    char *end = buf;
    errno = 0;
    float value = strtof(buf, &end);
    if (end == buf || *end != '\\0' || errno == ERANGE || !isfinite(value)) {
        return 0;
    }
    return value;
}
""", includes=["errno.h", "math.h", "stdlib.h"], needs=["scribe_read_token"]),
}

def _variables(expr: Expr):
    """Names of the variables `expr` reads."""
    if isinstance(expr, Variable):
        yield expr.name
    elif isinstance(expr, Grouped):
        yield from _variables(expr.value)
    elif isinstance(expr, (Unary, Cast, Not)):
        yield from _variables(expr.operand)
    elif isinstance(expr, (Binary, Comparison, Logical)):
        yield from _variables(expr.left)
        yield from _variables(expr.right)
    elif isinstance(expr, ComparisonChain):
        for operand in expr.operands:
            yield from _variables(operand)


def _without_outer_parentheses(text: str) -> str:
    """`(a && b)` -> `a && b`, but `(a) && (b)` stays as it is. For conditions,
    whose parentheses `if (...)` already supplies."""
    if not (text.startswith("(") and text.endswith(")")):
        return text
    depth = 0
    for i, char in enumerate(text):
        depth += {"(": 1, ")": -1}.get(char, 0)
        if depth == 0 and i < len(text) - 1:
            return text
    return text[1:-1]


@dataclass
class _Loop:
    """A `while` being emitted. A `break`/`continue` aimed at it from a nested
    loop becomes a `goto` to one of its labels, `break_<name>_<n>` or
    `continue_<name>_<n>`; `n` keeps sibling loops with one name apart, since
    C labels belong to the whole function."""

    name: str | None
    number: int
    broken: bool = False
    continued: bool = False

    def label(self, keyword: str) -> str:
        return f"{keyword}_{self.name}_{self.number}"


_CHECKED_I64 = {
    "+": "scribe_add_i64", "-": "scribe_sub_i64", "*": "scribe_mul_i64",
    "//": "scribe_floordiv_i64", "%": "scribe_mod_i64", "**": "scribe_pow_i64",
}
# C library functions the emitter calls: name -> (header, library to link).
_LIBRARY = {"pow": ("math.h", "m"), "powf": ("math.h", "m")}
_READ = {types.I64: "scribe_read_i64", types.F64: "scribe_read_f64", types.F32: "scribe_read_f32"}


@dataclass
class CEmitter:
    """AST -> C backend. No parsing or semantic analysis occurs here; every
    expression's type comes from the semantic model.

    Variable declarations come from the semantic model's scopes:

    * Program-level variables become zero-initialised file-scope globals in the
      header, exactly as before blocks existed.
    * Variables first assigned inside a block are declared at the *top of the
      matching C block*, zero-initialised. Hoisting (rather than declaring at
      the first assignment) means a `goto` inside a block can never jump over
      a declaration, and a block-local variable starts at 0 just like a global.

    Integer arithmetic goes through checked helpers that stop the program
    instead of overflowing; float arithmetic is plain C (IEEE 754, defined).
    """

    indent_width: int = 4
    # Shown in runtime error messages.
    filename: str | None = None
    _body: list[str] = field(default_factory=list, init=False)
    _indent: int = field(default=1, init=False)
    _model: SemanticModel | None = field(default=None, init=False)
    _scopes: list[Scope] = field(default_factory=list, init=False)
    _includes: set[str] = field(default_factory=set, init=False)
    # Libraries the C must be linked with (`m` for `-lm`), set by emit_program.
    link_libraries: tuple[str, ...] = field(default=(), init=False)
    _libraries: set[str] = field(default_factory=set, init=False)
    _helpers: set[str] = field(default_factory=set, init=False)
    _sites: list[str] = field(default_factory=list, init=False)
    _temporaries: int = field(default=0, init=False)
    # Declarations of the expression temporaries each open C block needs.
    _block_temporaries: list[list[str]] = field(default_factory=list, init=False)
    # The loops around the statement being emitted, innermost last.
    _loops: list[_Loop] = field(default_factory=list, init=False)
    # How many loops of each name have been emitted, to number their labels.
    _loop_names: dict[str | None, int] = field(default_factory=dict, init=False)

    def emit_program(self, program: Program, model: SemanticModel) -> str:
        self._body = []
        self._indent = 1
        self._model = model
        self._scopes = [model.root]
        self._includes = set()
        self._libraries = set()
        self._helpers = set()
        self._sites = []
        self._temporaries = 0
        self._loops = []
        self._loop_names = {}

        globals_ = [f"{self._c_type(symbol.type)} {c_variable(name)};" for name, symbol in sorted(model.root.symbols.items())]

        self._body.append("int main(void) {")
        self._block_temporaries = [[]]
        start = len(self._body)
        for stmt in program.statements:
            self._stmt(stmt)
        self._body[start:start] = [" " * self.indent_width + d for d in self._block_temporaries.pop()]
        self._body.append("    return 0;")
        self._body.append("}")

        # Only the headers and libraries the program uses: a program with no
        # input, output or runtime check does not even include <stdio.h>.
        self.link_libraries = tuple(sorted(self._libraries))
        header = []
        if self.link_libraries:
            header.append(f"/* Link with: {' '.join('-l' + lib for lib in self.link_libraries)} */")
        header += ["#include <stdio.h>"] if "stdio.h" in self._includes else []
        header += [f"#include <{name}>" for name in sorted(self._includes - {"stdio.h"})]
        header.append("")
        header.append("/* Program-level variables generated by semantic analysis. */")
        header += globals_
        header.append("")
        header += self._runtime()
        return "\n".join(header + self._body) + "\n"

    def _runtime(self) -> list[str]:
        lines: list[str] = []
        if self._sites:
            lines.append("/* Source position of each runtime check, by site number. */")
            lines.append("static const char *const scribe_sites[] = {")
            lines += [f"    {c_string_literal(site)}," for site in self._sites]
            lines.append("};")
            lines.append("")
        for name, helper in _HELPERS.items():
            if name in self._helpers:
                lines += helper.lines
        return lines

    def _use(self, name: str) -> str:
        if name not in self._helpers:
            self._helpers.add(name)
            helper = _HELPERS[name]
            self._includes.update(helper.includes)
            self._libraries.update(helper.libraries)
            for dependency in helper.needs:
                self._use(dependency)
        return name

    def _library(self, name: str) -> str:
        """Call the C library function `name`: include its header, link its library."""
        header, library = _LIBRARY[name]
        self._includes.add(header)
        self._libraries.add(library)
        return name

    def _site(self, location: SourceLocation) -> int:
        """Register a runtime check at `location`; returns its site number."""
        self._sites.append(f"{self.filename or '<input>'}:{location.line}:{location.column}")
        return len(self._sites) - 1

    def _c_type(self, t: ScalarType) -> str:
        if t.is_integer or t == types.BOOL:
            self._includes.add("stdint.h")
        return t.c_name

    def _temporary(self, t: ScalarType) -> str:
        """A new temporary for use inside an expression. It is declared, zeroed,
        at the top of the enclosing C block, so a goto never skips it."""
        self._temporaries += 1
        name = f"t_{self._temporaries}"
        self._block_temporaries[-1].append(f"{self._c_type(t)} {name} = 0;")
        return name

    def _line(self, text: str) -> None:
        self._body.append(" " * (self._indent * self.indent_width) + text)

    def _block_body(self, block: Block) -> None:
        """Emit the inside of a C block: hoisted declarations, then statements.

        The caller writes the opening and closing braces.
        """
        assert self._model is not None, "emit_program() must set the model first"
        scope = self._model.scopes[block]
        self._scopes.append(scope)
        self._indent += 1
        for name, symbol in scope.symbols.items():
            self._line(f"{self._c_type(symbol.type)} {c_variable(name)} = 0;")
        self._block_temporaries.append([])
        start = len(self._body)
        for child in block.statements:
            self._stmt(child)
        indent = " " * (self._indent * self.indent_width)
        self._body[start:start] = [indent + d for d in self._block_temporaries.pop()]
        self._indent -= 1
        self._scopes.pop()

    def _stmt(self, stmt) -> None:
        if isinstance(stmt, Print):
            self._includes.add("stdio.h")
            if stmt.is_string:
                # puts, not printf: the text must never be read as a format
                # string (`print "100%"`). puts also appends the newline.
                self._line(f"puts({c_string_literal(stmt.value)});")
            elif self._model.type_of(stmt.value) == types.BOOL:
                self._line(f'puts({self._expr(stmt.value)} ? "true" : "false");')
            elif self._model.type_of(stmt.value).is_integer:
                self._includes.add("inttypes.h")
                self._line(f'printf("%" PRId64 "\\n", {self._expr(stmt.value)});')
            else:
                # An f32 argument is promoted to double, which %f expects.
                self._line(f'printf("%.2f\\n", {self._expr(stmt.value)});')
        elif isinstance(stmt, Input):
            symbol = self._scopes[-1].lookup(stmt.name)
            self._line(f"{c_variable(stmt.name)} = {self._use(_READ[symbol.type])}();")
        elif isinstance(stmt, Let):
            symbol = self._scopes[-1].lookup(stmt.name)
            self._line(f"{c_variable(stmt.name)} = {self._operand(stmt.value, symbol.type)};")
        elif isinstance(stmt, ChainedLet):
            for let in stmt.lets:
                self._stmt(let)
        elif isinstance(stmt, MultiLet):
            self._multi_let(stmt)
        elif isinstance(stmt, Declaration):
            # The variable itself is declared (and zeroed) at the top of its C
            # block. Assigning here as well means the declaration gives the
            # variable its value every time it runs, even after a backward goto.
            for declarator in stmt.declarators:
                symbol = self._scopes[-1].lookup(declarator.name)
                if declarator.value is None:
                    value = self._zero(symbol.type)
                else:
                    value = self._operand(declarator.value, symbol.type)
                self._line(f"{c_variable(declarator.name)} = {value};")
        elif isinstance(stmt, If):
            self._line(f"if ({self._condition(stmt.condition)}) {{")
            self._block_body(stmt.body)
            for arm in stmt.elifs:
                self._line(f"}} else if ({self._condition(arm.condition)}) {{")
                self._block_body(arm.body)
            if stmt.orelse is not None:
                self._line("} else {")
                self._block_body(stmt.orelse)
            self._line("}")
        elif isinstance(stmt, While):
            self._loop_names[stmt.name] = self._loop_names.get(stmt.name, 0) + 1
            loop = _Loop(stmt.name, self._loop_names[stmt.name])
            self._loops.append(loop)
            self._line(f"while ({self._condition(stmt.condition)}) {{")
            self._block_body(stmt.body)
            self._loops.pop()
            # The labels of a named loop, only if a nested loop jumps to them
            # (an unused label is a -Wall warning). `continue` lands at the end
            # of the body, so the condition is tested again.
            if loop.continued:
                self._body.append(f"{loop.label('continue')}:;")
            self._line("}")
            if loop.broken:
                self._body.append(f"{loop.label('break')}:;")
        elif isinstance(stmt, (Break, Continue)):
            keyword = "break" if isinstance(stmt, Break) else "continue"
            target = self._loops[-1]
            if stmt.name is not None:
                target = next(loop for loop in reversed(self._loops) if loop.name == stmt.name)
            if target is self._loops[-1]:
                self._line(f"{keyword};")
            else:
                # C's break and continue only reach the innermost loop.
                if keyword == "break":
                    target.broken = True
                else:
                    target.continued = True
                self._line(f"goto {target.label(keyword)};")
        elif isinstance(stmt, Block):
            self._line("{")
            self._block_body(stmt)
            self._line("}")
        elif isinstance(stmt, Label):
            # Labels need special indentation in C. The trailing `;` is a null
            # statement: C11 requires a statement after a label, so without it
            # a label that ends a block is rejected by strict compilers.
            self._body.append(f"{c_label(stmt.name)}:;")
        elif isinstance(stmt, Goto):
            self._line(f"goto {c_label(stmt.name)};")
        else:
            raise TypeError(f"Unsupported statement node: {type(stmt).__name__}")

    def _multi_let(self, stmt: MultiLet) -> None:
        """`a, b = x, y`. Plain assignments in order are enough unless a value
        reads a target assigned before it; then every value is computed into
        a temporary first (still left to right), in a C block of their own."""
        names = [name for name, _ in stmt.targets]
        types_ = [self._scopes[-1].lookup(name).type for name in names]
        if not any(set(_variables(value)) & set(names[:i]) for i, value in enumerate(stmt.values)):
            for name, type_, value in zip(names, types_, stmt.values):
                self._line(f"{c_variable(name)} = {self._operand(value, type_)};")
            return
        self._line("{")
        self._indent += 1
        temporaries = []
        for value in stmt.values:
            self._temporaries += 1
            temporary = f"t_{self._temporaries}"
            value_type = self._model.type_of(value)
            self._line(f"{self._c_type(value_type)} {temporary} = {self._expr(value)};")
            temporaries.append((temporary, value_type))
        for name, type_, (temporary, value_type) in zip(names, types_, temporaries):
            # Only lossless widening reaches here, so a plain cast is exact.
            value = temporary if value_type == type_ else f"(({self._c_type(type_)}){temporary})"
            self._line(f"{c_variable(name)} = {value};")
        self._indent -= 1
        self._line("}")

    def _condition(self, cond: Expr) -> str:
        """The C condition of an `if`/`elif`/`while`: a bool as it is, an
        integer compared with 0. No outer parentheses, because `if (...)`
        supplies them (`if ((a == b))` makes clang warn)."""
        if isinstance(cond, Comparison):
            return self._comparison(cond)
        text = self._expr(cond)
        if self._model.type_of(cond).is_integer:
            return f"{text} != 0"
        return _without_outer_parentheses(text)

    def _comparison(self, cmp: Comparison) -> str:
        operand_type = self._model.operand_type(cmp)
        left = self._operand(cmp.left, operand_type)
        right = self._operand(cmp.right, operand_type)
        return f"{left} {cmp.operator} {right}"

    def _chain(self, chain: ComparisonChain) -> str:
        """`a < b <= c` -> `((a < b) && (b <= c))`. A middle operand that is
        not a plain name or constant is evaluated once, into a temporary, at
        its first use: `((a < (t_1 = b + 1)) && (t_1 <= c))`. So, as in
        Python, later operands only run while the comparisons hold."""
        operand_type = self._model.operand_type(chain)
        last = len(chain.operands) - 1
        first_use, later_use = [], []
        for i, operand in enumerate(chain.operands):
            text = self._operand(operand, operand_type)
            if 0 < i < last and not self._is_plain(operand):
                temporary = self._temporary(operand_type)
                first_use.append(f"({temporary} = {text})")
                later_use.append(temporary)
            else:
                first_use.append(text)
                later_use.append(text)
        pieces = [
            f"({first_use[0] if i == 0 else later_use[i]} {op} {first_use[i + 1]})"
            for i, op in enumerate(chain.operators)
        ]
        return "(" + " && ".join(pieces) + ")"

    def _is_plain(self, expr: Expr) -> bool:
        """True if evaluating `expr` twice costs nothing and cannot fail."""
        if isinstance(expr, Grouped):
            return self._is_plain(expr.value)
        return isinstance(expr, (Variable, IntLit, FloatLit, BoolLit)) or self._model.constant(expr) is not None

    def _zero(self, t: ScalarType) -> str:
        if t == types.BOOL:
            return "0"
        if t.is_float:
            return c_float_literal(Fraction(0), t)
        self._c_type(t)
        return c_int_literal(0, t)

    def _operand(self, expr: Expr, t: ScalarType) -> str:
        """`expr` converted to `t`. Semantic analysis only allows lossless
        (widening) conversions here, so a plain C cast is exact."""
        text = self._expr(expr)
        if self._model.type_of(expr) != t:
            return f"(({self._c_type(t)}){text})"
        return text

    def _expr(self, expr: Expr) -> str:
        t = self._model.type_of(expr)
        value = self._model.constant(expr)
        if value is not None:
            if t.is_float:
                return c_float_literal(types.round_float(Fraction(value), t), t)
            self._c_type(t)
            return c_int_literal(value, t)
        if isinstance(expr, FloatLit):
            return c_float_literal(types.round_float(Fraction(expr.text), t), t)
        if isinstance(expr, Variable):
            return c_variable(expr.name)
        if isinstance(expr, Grouped):
            return self._expr(expr.value)
        if isinstance(expr, Unary):
            operand = self._expr(expr.operand)
            if expr.operator == "+":
                return operand
            if t.is_integer:
                return f"{self._use('scribe_neg_i64')}({operand}, {self._site(expr.location)})"
            return f"(-{operand})"
        if isinstance(expr, Binary):
            left = self._operand(expr.left, t)
            right = self._operand(expr.right, t)
            if t.is_integer:
                helper = self._use(_CHECKED_I64[expr.operator])
                return f"{helper}({left}, {right}, {self._site(expr.operator_location)})"
            if expr.operator == "**":
                # IEEE 754 results (C11 Annex F): inf on overflow, nan for a
                # negative base and a fractional exponent; never undefined.
                function = self._library("powf" if t == types.F32 else "pow")
                return f"{function}({_without_outer_parentheses(left)}, {_without_outer_parentheses(right)})"
            if expr.operator == "/" and not self._nonzero_constant(expr.right):
                helper = self._use("scribe_div_f32" if t == types.F32 else "scribe_div_f64")
                return f"{helper}({_without_outer_parentheses(left)}, {_without_outer_parentheses(right)})"
            return f"({left} {expr.operator} {right})"
        if isinstance(expr, Cast):
            return self._cast(expr, t)
        if isinstance(expr, BoolLit):
            # Plain constants, so `while true` stays a C constant expression.
            return "1" if expr.value else "0"
        if isinstance(expr, Not):
            return f"(!{self._expr(expr.operand)})"
        if isinstance(expr, Logical):
            # C's && and || evaluate the right side only when needed, and give
            # 0 or 1, so a bool stored from them is always 0 or 1.
            op = "&&" if expr.operator == "and" else "||"
            return f"({self._expr(expr.left)} {op} {self._expr(expr.right)})"
        if isinstance(expr, Comparison):
            return f"({self._comparison(expr)})"
        if isinstance(expr, ComparisonChain):
            return self._chain(expr)
        raise TypeError(f"Unsupported expression node: {type(expr).__name__}")

    def _nonzero_constant(self, expr: Expr) -> bool:
        """True if `expr` is a number constant other than zero, so dividing by
        it is plain C division."""
        if isinstance(expr, (Grouped, Unary)):
            return self._nonzero_constant(expr.value if isinstance(expr, Grouped) else expr.operand)
        if isinstance(expr, FloatLit):
            # The value C sees: a literal such as 1e-400 rounds to 0.0.
            return types.round_float(Fraction(expr.text), self._model.type_of(expr)) != 0
        value = self._model.constant(expr)
        return value is not None and value != 0

    def _cast(self, expr: Cast, target: ScalarType) -> str:
        source = self._model.type_of(expr.operand)
        operand = self._expr(expr.operand)
        if source == target:
            return operand
        if target == types.BOOL:
            return f"({operand} != 0)"
        if source == types.BOOL:
            return f"(({self._c_type(target)}){operand})"  # 0 or 1, exact in every type
        if target.is_float and (source.is_integer or types.holds_all(source, target)):
            # Integer -> float rounds (defined: every i64 is in range of f32);
            # f32 -> f64 is exact.
            return f"(({self._c_type(target)}){operand})"
        if target == types.F32:
            return f"{self._use('scribe_f64_to_f32')}({operand})"
        if target.is_integer and source.is_float:
            return f"{self._use('scribe_f64_to_i64')}({operand}, {self._site(expr.location)})"
        raise TypeError(f"Unsupported cast from {source} to {target}")
