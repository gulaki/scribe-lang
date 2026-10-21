from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from .ast import (
    Binary, Block, Cast, Comparison, Expr, FloatLit, Goto, Grouped, If, Input,
    IntLit, Label, Let, Print, Program, SourceLocation, Stmt, Unary, Variable,
    While,
)
from . import diagnostics as codes
from . import types
from .diagnostics import Diagnostics
from .types import ScalarType


# Words the grammar treats as keywords. The contextual lexer only produces a
# keyword token where the parser can accept one, so e.g. `else` at the start of
# a statement lexes as an IDENT. Reject those names here instead of letting
# them reach the C compiler. tests/test_semantics.py checks this set against
# the keyword terminals in the grammar file so the two cannot drift apart.
RESERVED_WORDS = frozenset(
    {"print", "input", "if", "elif", "else", "while", "label", "goto"}
) | types.TYPE_NAMES


@dataclass
class Symbol:
    name: str
    kind: str = "variable"
    location: SourceLocation = field(default_factory=SourceLocation)
    # Fixed by the first assignment. None only after an error made it unknown.
    type: ScalarType | None = None


# eq=False: scopes are compared by identity.
@dataclass(eq=False)
class Scope:
    """One lexical scope. Maps names to the symbols *declared* in it.

    `symbols` keeps insertion order, i.e. the order of first assignment, which
    is the order the C backend declares them in.
    """

    parent: Scope | None = None
    symbols: dict[str, Symbol] = field(default_factory=dict)

    def lookup(self, name: str) -> Symbol | None:
        """Find `name` here or in any enclosing scope."""
        scope: Scope | None = self
        while scope is not None:
            symbol = scope.symbols.get(name)
            if symbol is not None:
                return symbol
            scope = scope.parent
        return None

    def declare(self, name: str, location: SourceLocation, type: ScalarType | None) -> Symbol:
        symbol = Symbol(name, "variable", location, type)
        self.symbols[name] = symbol
        return symbol

    def encloses(self, inner: Scope) -> bool:
        """True if `inner` is this scope or is nested somewhere inside it."""
        scope: Scope | None = inner
        while scope is not None:
            if scope is self:
                return True
            scope = scope.parent
        return False


@dataclass
class SemanticModel:
    root: Scope = field(default_factory=Scope)
    # Scope introduced by each Block node (keyed by identity).
    scopes: dict[Block, Scope] = field(default_factory=dict)
    # label name -> scope the label was written in. C labels are function
    # scoped, so one namespace for the whole program.
    labels: dict[str, Scope] = field(default_factory=dict)
    label_locations: dict[str, SourceLocation] = field(default_factory=dict)
    gotos: list[Goto] = field(default_factory=list)
    # The type of every expression, and the exact value of every integer
    # constant expression, keyed by node identity: expression nodes compare by
    # value, but two equal literals can end up with different types. For a
    # Comparison the type is the one both operands are compared in.
    expr_types: dict[int, ScalarType] = field(default_factory=dict)
    constants: dict[int, int] = field(default_factory=dict)

    @property
    def symbols(self) -> dict[str, Symbol]:
        """Program-level (outermost scope) variables only."""
        return self.root.symbols

    def type_of(self, expr: Expr) -> ScalarType:
        return self.expr_types[id(expr)]

    def constant(self, expr: Expr) -> int | None:
        """The folded value if `expr` is an integer constant expression."""
        return self.constants.get(id(expr))


@dataclass(frozen=True)
class _Const:
    """An integer constant expression, folded exactly. Like a literal, it has
    no type until its context gives it one."""

    value: int


class _UntypedFloat:
    """A float constant expression (made of literals); typed by its context."""


_UNTYPED_FLOAT = _UntypedFloat()

# What inferring an expression gives: a type, an untyped constant, or None
# when an error was already reported (so it is not reported again).
_Info = ScalarType | _Const | _UntypedFloat | None


def _fold(op: str, a: int, b: int) -> int | None:
    """`a op b` on exact integers, as the generated C computes it; None for
    division by zero. Division truncates toward zero, like C."""
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if b == 0:
        return None
    quotient = abs(a) // abs(b)
    return quotient if (a < 0) == (b < 0) else -quotient


def _literal_text(expr: Expr) -> str | None:
    """The spelling of a (possibly signed or parenthesised) literal."""
    if isinstance(expr, IntLit):
        return expr.text
    if isinstance(expr, FloatLit):
        return expr.text
    if isinstance(expr, Grouped):
        return _literal_text(expr.value)
    if isinstance(expr, Unary):
        inner = _literal_text(expr.operand)
        return None if inner is None else expr.operator + inner
    return None


class SemanticAnalyzer:
    """Language-independent semantic checks live here, not in the emitter.

    Scoping rules
    -------------
    * `{ ... }` opens a scope. The program itself is the outermost scope.
    * `x = e` and `input x` assign to `x` if a variable called `x` is visible
      (declared earlier in this scope or an enclosing one). Otherwise they
      declare a new variable in the *innermost* scope.
    * The right-hand side is checked before the target is declared, so
      `x = x + 1` is an error when `x` does not exist yet.
    * `if` / `elif` / `while` conditions belong to the enclosing scope; each
      body (and `else`) is its own scope.
    * Variables are not visible after the block that declared them ends.
    * Labels live in one program-wide namespace, but `goto` may only jump to a
      label in its own block or an enclosing block, never into a nested one.

    Typing rules (docs/design/type-system.md)
    ------------------------------------------
    * A variable gets the type of its first assignment and keeps it. Later
      assignments must widen losslessly (`types.holds_all`). `input x` into a
      new variable makes it f64.
    * Literals have no type of their own. An integer literal takes the type
      its context needs if its value fits exactly; a float literal takes any
      float type it does not overflow. With no context they are i64 and f64.
      `2.5f` is always f32.
    * Integer constant expressions are folded exactly, so only the final
      value has to fit (`-9223372036854775808` is fine).
    * A binary operator works in `types.common_type` of its operands, and it
      is an error if there is none: i64 and f64 need an explicit cast.

    Every problem is reported to `diagnostics` and analysis carries on, so all
    errors are found in one run. To avoid a flood of follow-on errors, each
    undeclared variable is reported only at its first use, and an expression
    whose type is unknown because of an earlier error is not checked further.
    """

    def analyze(self, program: Program, diagnostics: Diagnostics) -> SemanticModel:
        model = SemanticModel()
        self._model = model
        self._diagnostics = diagnostics
        self._goto_sites: list[tuple[Goto, Scope]] = []
        # Variables whose scope has already ended, for friendlier errors.
        self._closed: dict[str, SourceLocation] = {}
        self._reported_undeclared: set[str] = set()
        # Exact values of integer constant expressions, before they are typed.
        self._consts: dict[int, int] = {}

        self._visit_statements(program.statements, model.root)

        for goto, scope in self._goto_sites:
            label_scope = model.labels.get(goto.name)
            if label_scope is None:
                diagnostics.error(codes.UNDECLARED_LABEL, goto.location, name=goto.name)
            elif not label_scope.encloses(scope):
                diagnostics.error(
                    codes.GOTO_INTO_BLOCK, goto.location, name=goto.name,
                    notes=((f"label '{goto.name}' is defined here, inside a nested block",
                            model.label_locations[goto.name]),),
                )
        return model

    # -- statements --------------------------------------------------------

    def _visit_statements(self, statements: tuple[Stmt, ...], scope: Scope) -> None:
        for stmt in statements:
            if isinstance(stmt, Let):
                info = self._infer(stmt.value, scope)  # before declaring the target
                self._assign(stmt.name, scope, stmt.location, stmt.value, info)
            elif isinstance(stmt, Input):
                self._assign(stmt.name, scope, stmt.location, None, types.F64)
            elif isinstance(stmt, Print):
                if not stmt.is_string:
                    self._settle_default(stmt.value, self._infer(stmt.value, scope))
            elif isinstance(stmt, If):
                self._condition(stmt.condition, scope)
                self._visit_block(stmt.body, scope)
                for arm in stmt.elifs:
                    self._condition(arm.condition, scope)
                    self._visit_block(arm.body, scope)
                if stmt.orelse is not None:
                    self._visit_block(stmt.orelse, scope)
            elif isinstance(stmt, While):
                self._condition(stmt.condition, scope)
                self._visit_block(stmt.body, scope)
            elif isinstance(stmt, Block):
                self._visit_block(stmt, scope)
            elif isinstance(stmt, Label):
                self._check_name(stmt.name, "label", stmt.location)
                if stmt.name in self._model.labels:
                    # Keep the first definition; gotos are checked against it.
                    self._diagnostics.error(
                        codes.DUPLICATE_LABEL, stmt.location, name=stmt.name,
                        notes=(("first defined here", self._model.label_locations[stmt.name]),),
                    )
                else:
                    self._model.labels[stmt.name] = scope
                    self._model.label_locations[stmt.name] = stmt.location
            elif isinstance(stmt, Goto):
                self._model.gotos.append(stmt)
                self._goto_sites.append((stmt, scope))

    def _visit_block(self, block: Block, parent: Scope) -> None:
        scope = Scope(parent)
        self._model.scopes[block] = scope
        self._visit_statements(block.statements, scope)
        for name, symbol in scope.symbols.items():
            self._closed[name] = symbol.location

    def _assign(self, name: str, scope: Scope, location: SourceLocation, value: Expr | None, info: _Info) -> None:
        """`name = value` (or `input name` when `value` is None)."""
        # A reserved name is still declared, so its later uses do not also
        # report "undeclared variable".
        self._check_name(name, "variable", location)
        symbol = scope.lookup(name)
        if symbol is None:
            type_ = info if value is None else self._settle_default(value, info)
            scope.declare(name, location, type_)
        elif value is not None and symbol.type is not None and info is not None:
            self._check_assignment(symbol, value, info)

    def _check_assignment(self, symbol: Symbol, value: Expr, info: _Info) -> None:
        target = symbol.type
        if isinstance(info, _Const) or (info is _UNTYPED_FLOAT and target.is_float):
            self._settle(value, target)
            return
        found = types.DEFAULT_FLOAT if info is _UNTYPED_FLOAT else info
        if not types.holds_all(found, target):
            help = None
            if target.is_float or found.is_float:
                help = f"convert it explicitly: {target}(...)"
            self._diagnostics.error(
                codes.TYPE_MISMATCH, value.location, found=found, name=symbol.name, expected=target,
                notes=((f"'{symbol.name}' was declared here as {target}", symbol.location),),
                help=help,
            )

    def _check_name(self, name: str, what: str, location: SourceLocation) -> None:
        if name in RESERVED_WORDS:
            self._diagnostics.error(codes.RESERVED_NAME, location, name=name, what=what)

    # -- expressions -------------------------------------------------------
    # `_infer` works bottom-up and returns the type of an expression, or that
    # it is still an untyped constant. `_settle` then gives an untyped constant
    # expression the type its context needs, checking that its value fits.

    def _infer(self, expr: Expr, scope: Scope) -> _Info:
        info = self._infer_uncached(expr, scope)
        if isinstance(info, ScalarType):
            self._model.expr_types[id(expr)] = info
        elif isinstance(info, _Const):
            self._consts[id(expr)] = info.value
        return info

    def _infer_uncached(self, expr: Expr, scope: Scope) -> _Info:
        if isinstance(expr, IntLit):
            return _Const(expr.value)
        if isinstance(expr, FloatLit):
            if expr.is_f32:
                self._settle(expr, types.F32)
                return types.F32
            return _UNTYPED_FLOAT
        if isinstance(expr, Variable):
            symbol = scope.lookup(expr.name)
            if symbol is not None:
                return symbol.type
            if expr.name not in self._reported_undeclared:
                self._reported_undeclared.add(expr.name)
                gone = self._closed.get(expr.name)
                notes = ()
                if gone is not None:
                    notes = ((f"'{expr.name}' was declared here, in a block that ended", gone),)
                self._diagnostics.error(
                    codes.UNDECLARED_VARIABLE, expr.location, name=expr.name, notes=notes,
                )
            return None
        if isinstance(expr, Grouped):
            return self._infer(expr.value, scope)
        if isinstance(expr, Unary):
            info = self._infer(expr.operand, scope)
            if isinstance(info, _Const) and expr.operator == "-":
                return _Const(-info.value)
            return info
        if isinstance(expr, Binary):
            return self._binary(expr, scope)
        if isinstance(expr, Cast):
            return self._cast(expr, scope)
        raise TypeError(f"Unsupported expression node: {type(expr).__name__}")

    def _binary(self, expr: Binary, scope: Scope) -> _Info:
        left = self._infer(expr.left, scope)
        right = self._infer(expr.right, scope)
        if left is None or right is None:
            return None
        if isinstance(left, _Const) and isinstance(right, _Const):
            value = _fold(expr.operator, left.value, right.value)
            if value is None:
                self._diagnostics.error(codes.CONSTANT_DIVISION_BY_ZERO, expr.operator_location)
                return None
            return _Const(value)
        if not isinstance(left, ScalarType) and not isinstance(right, ScalarType):
            return _UNTYPED_FLOAT  # literals only, at least one of them a float
        return self._operand_type(expr, expr.operator_location, left, right)

    def _condition(self, cond: Comparison, scope: Scope) -> None:
        left = self._infer(cond.left, scope)
        right = self._infer(cond.right, scope)
        if left is None or right is None:
            return
        if not isinstance(left, ScalarType) and not isinstance(right, ScalarType):
            # Two constants, e.g. `if 1 > 0`: compare them as default types.
            both_int = isinstance(left, _Const) and isinstance(right, _Const)
            type_ = types.DEFAULT_INT if both_int else types.DEFAULT_FLOAT
            self._settle(cond.left, type_)
            self._settle(cond.right, type_)
            self._model.expr_types[id(cond)] = type_
            return
        type_ = self._operand_type(cond, cond.location, left, right)
        if type_ is not None:
            self._model.expr_types[id(cond)] = type_

    def _operand_type(self, expr: Binary | Comparison, where: SourceLocation, left: _Info, right: _Info) -> ScalarType | None:
        """The type a binary operator or comparison works in, when at least
        one operand has a type; untyped operands are settled to it."""
        if isinstance(left, ScalarType) and isinstance(right, ScalarType):
            type_ = types.common_type(left, right)
            if type_ is None:
                self._no_common_type(expr.operator, where, left, right)
            return type_
        typed, other_info, other = (left, right, expr.right) if isinstance(left, ScalarType) else (right, left, expr.left)
        if isinstance(other_info, _Const) or typed.is_float:
            self._settle(other, typed)
            return typed
        self._no_common_type(expr.operator, where, left if left is typed else "a float constant",
                             right if right is typed else "a float constant")
        return None

    def _no_common_type(self, op: str, where: SourceLocation, left, right) -> None:
        """`left` and `right` are types, or the text "a float constant"."""
        sides = [types.DEFAULT_FLOAT if isinstance(t, str) else t for t in (left, right)]
        floats = [t for t in sides if t.is_float]
        ints = [t for t in sides if not t.is_float]
        help = "convert one side explicitly"
        if floats and ints:
            help += f": {floats[0]}(...) to work in {floats[0]}, or {ints[0]}(...) to work in {ints[0]}"
        self._diagnostics.error(codes.NO_COMMON_TYPE, where, op=op, left=left, right=right, help=help)

    def _cast(self, expr: Cast, scope: Scope) -> _Info:
        target = types.by_name(expr.type_name)
        info = self._infer(expr.operand, scope)
        if isinstance(info, _Const):
            # An explicit cast may round an integer constant to a float.
            self._settle(expr.operand, target, exact=False)
        elif info is _UNTYPED_FLOAT:
            self._settle(expr.operand, target if target.is_float else types.DEFAULT_FLOAT)
        # Even if the operand had an error, the result is known to be `target`.
        return target

    def _settle_default(self, expr: Expr, info: _Info) -> ScalarType | None:
        """Type an expression that has no context: i64 or f64 for constants."""
        if isinstance(info, _Const):
            self._settle(expr, types.DEFAULT_INT)
            return types.DEFAULT_INT
        if info is _UNTYPED_FLOAT:
            self._settle(expr, types.DEFAULT_FLOAT)
            return types.DEFAULT_FLOAT
        return info

    def _settle(self, expr: Expr, target: ScalarType, exact: bool = True) -> None:
        """Give the untyped constant expression `expr` the type `target`,
        reporting a value that does not fit. With `exact=False` (explicit
        casts) an integer constant may round to a float value."""
        self._model.expr_types[id(expr)] = target
        value = self._consts.get(id(expr))
        if value is not None:
            if exact or not target.is_float:
                fits = types.integer_fits(value, target)
            else:
                fits = types.round_float(Fraction(value), target) is not None
            if fits:
                self._model.constants[id(expr)] = value
            else:
                self._does_not_fit(expr, value, target)
        elif isinstance(expr, FloatLit):
            if types.round_float(Fraction(expr.text), target) is None:
                self._does_not_fit(expr, expr.text, target)
        elif isinstance(expr, (Grouped, Unary)):
            self._settle(expr.value if isinstance(expr, Grouped) else expr.operand, target, exact)
        elif isinstance(expr, Binary):
            self._settle(expr.left, target, exact)
            self._settle(expr.right, target, exact)

    def _does_not_fit(self, expr: Expr, value, target: ScalarType) -> None:
        text = _literal_text(expr)
        if text is not None:
            self._diagnostics.error(codes.NUMBER_TOO_LARGE, expr.location, value=text, type=target)
        else:
            self._diagnostics.error(codes.CONSTANT_OVERFLOW, expr.location, value=value, type=target)
