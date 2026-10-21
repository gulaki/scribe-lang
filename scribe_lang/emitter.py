from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from .ast import (
    Binary, Block, Cast, Comparison, Expr, FloatLit, Goto, Grouped, If, Input,
    Label, Let, Print, Program, SourceLocation, Unary, Variable, While,
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


def _helper(code: str, includes=(), needs=()) -> _Helper:
    return _Helper(tuple(code.strip("\n").split("\n")) + ("",), tuple(includes), tuple(needs))


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
    fprintf(stderr, "%s: runtime error: %s\\n", scribe_sites[site], what);
    abort();
}
""", includes=["stdlib.h"]),
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
    "scribe_div_i64": _helper("""
static int64_t scribe_div_i64(int64_t a, int64_t b, int site) {
    if (b == 0) {
        scribe_trap(site, "division by zero");
    }
    if (a == INT64_MIN && b == -1) {
        scribe_trap(site, "integer overflow");
    }
    return a / b;
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
""", includes=["ctype.h"]),
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

_CHECKED_I64 = {"+": "scribe_add_i64", "-": "scribe_sub_i64", "*": "scribe_mul_i64", "/": "scribe_div_i64"}
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
    _helpers: set[str] = field(default_factory=set, init=False)
    _sites: list[str] = field(default_factory=list, init=False)

    def emit_program(self, program: Program, model: SemanticModel) -> str:
        self._body = []
        self._indent = 1
        self._model = model
        self._scopes = [model.root]
        self._includes = set()
        self._helpers = set()
        self._sites = []

        globals_ = [f"{self._c_type(symbol.type)} {c_variable(name)};" for name, symbol in sorted(model.root.symbols.items())]

        self._body.append("int main(void) {")
        for stmt in program.statements:
            self._stmt(stmt)
        self._body.append("    return 0;")
        self._body.append("}")

        header = ["#include <stdio.h>"]
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
            for dependency in helper.needs:
                self._use(dependency)
        return name

    def _site(self, location: SourceLocation) -> int:
        """Register a runtime check at `location`; returns its site number."""
        self._sites.append(f"{self.filename or '<input>'}:{location.line}:{location.column}")
        return len(self._sites) - 1

    def _c_type(self, t: ScalarType) -> str:
        if t.is_integer:
            self._includes.add("stdint.h")
        return t.c_name

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
        for child in block.statements:
            self._stmt(child)
        self._indent -= 1
        self._scopes.pop()

    def _stmt(self, stmt) -> None:
        if isinstance(stmt, Print):
            if stmt.is_string:
                # puts, not printf: the text must never be read as a format
                # string (`print "100%"`). puts also appends the newline.
                self._line(f"puts({c_string_literal(stmt.value)});")
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
            self._line(f"while ({self._condition(stmt.condition)}) {{")
            self._block_body(stmt.body)
            self._line("}")
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

    def _condition(self, cond: Comparison) -> str:
        # No outer parentheses: comparisons only appear as the condition of
        # `if`/`while`, which already supply them (`if ((a == b))` makes
        # clang warn with -Wparentheses-equality).
        operand_type = self._model.type_of(cond)
        left = self._operand(cond.left, operand_type)
        right = self._operand(cond.right, operand_type)
        return f"{left} {cond.operator} {right}"

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
            return f"({left} {expr.operator} {right})"
        if isinstance(expr, Cast):
            return self._cast(expr, t)
        raise TypeError(f"Unsupported expression node: {type(expr).__name__}")

    def _cast(self, expr: Cast, target: ScalarType) -> str:
        source = self._model.type_of(expr.operand)
        operand = self._expr(expr.operand)
        if source == target:
            return operand
        if target.is_float and (source.is_integer or types.holds_all(source, target)):
            # Integer -> float rounds (defined: every i64 is in range of f32);
            # f32 -> f64 is exact.
            return f"(({self._c_type(target)}){operand})"
        if target == types.F32:
            return f"{self._use('scribe_f64_to_f32')}({operand})"
        if target.is_integer and source.is_float:
            return f"{self._use('scribe_f64_to_i64')}({operand}, {self._site(expr.location)})"
        raise TypeError(f"Unsupported cast from {source} to {target}")
