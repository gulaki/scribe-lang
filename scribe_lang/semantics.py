from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from .ast import (
    Binary, Block, BoolLit, Break, Cast, ChainedLet, Comparison, ComparisonChain,
    Continue, Declaration, Expr, FloatLit, Goto, Grouped, If, Input, IntLit,
    Label, Let, Logical, MultiLet, Not, Print, Program, SourceLocation, Stmt,
    Unary, Variable, While,
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
    {"print", "input", "if", "elif", "else", "while", "label", "goto",
     "break", "continue", "as", "true", "false", "and", "or", "not"}
) | types.TYPE_NAMES

_GOTO_HELP = "leave a loop with 'break', or an outer loop with 'break name' / 'continue name' (while ... as name)"


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
    # value, but two equal literals can end up with different types.
    expr_types: dict[int, ScalarType] = field(default_factory=dict)
    constants: dict[int, int] = field(default_factory=dict)
    # For a Comparison or ComparisonChain (whose own type is bool): the type
    # its operands are compared in.
    operand_types: dict[int, ScalarType] = field(default_factory=dict)

    @property
    def symbols(self) -> dict[str, Symbol]:
        """Program-level (outermost scope) variables only."""
        return self.root.symbols

    def type_of(self, expr: Expr) -> ScalarType:
        return self.expr_types[id(expr)]

    def constant(self, expr: Expr) -> int | None:
        """The folded value if `expr` is an integer constant expression."""
        return self.constants.get(id(expr))

    def operand_type(self, comparison: Expr) -> ScalarType:
        return self.operand_types[id(comparison)]


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

# Which way each comparison operator points, for chains.
_DIRECTION = {"<": "up", "<=": "up", ">": "down", ">=": "down", "==": "equal", "!=": "not-equal"}


def _fold(op: str, a: int, b: int) -> int | None:
    """`a op b` on exact integers, as the generated C computes it; None for
    division by zero. `//` and `%` round toward negative infinity, as
    Python's do."""
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "**":
        return a ** b  # b >= 0 and small enough, checked by the caller
    if b == 0:
        return None
    if op == "//":
        return a // b
    return a % b


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


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
    * `i64: x = e` always declares `x` in the innermost scope; it is an error
      if a variable called `x` is already visible (there is no shadowing).
      Declarators are handled left to right, each value before its name.
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
    * `**` works in the common type of its operands, like `+`. An integer
      power needs an exponent of 0 or more.
    * `/` divides floats; constants become floats (`7 / 2` is 3.5) and an
      integer operand is an error. `//` and `%` work on integers only,
      rounding toward negative infinity.
    * A truth test (a condition, an operand of `not`/`and`/`or`, `bool(x)`)
      takes a bool or an integer. A float is an error: NaN would count as
      true and -0.0 as false, so the program must compare explicitly.
    * Comparisons, `not`, `and` and `or` give a bool. A bool is not a number:
      no arithmetic or ordering on it, and no implicit conversion to or from
      it (`bool(n)` and `i64(flag)` convert explicitly).
    * `a < b <= c` compares every operand in one common type. A chain points
      one way (`<`/`<=`, or `>`/`>=`) or is all `==`; `!=` cannot be chained.

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
        # The loops around the statement being checked, innermost last.
        self._loops: list[While] = []

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
                self._let(stmt, scope)
            elif isinstance(stmt, ChainedLet):
                # In source order the targets are the reverse of `lets`.
                self._check_unique([(let.name, let.location) for let in reversed(stmt.lets)])
                for let in stmt.lets:
                    self._let(let, scope)
            elif isinstance(stmt, MultiLet):
                self._multi_let(stmt, scope)
            elif isinstance(stmt, Declaration):
                self._declaration(stmt, scope)
            elif isinstance(stmt, Input):
                symbol = scope.lookup(stmt.name)
                if symbol is not None and symbol.type == types.BOOL:
                    self._diagnostics.error(
                        codes.CANNOT_INPUT_TYPE, stmt.location, type=symbol.type,
                        help="read an i64 and convert it: bool(n)",
                    )
                self._assign(stmt.name, scope, stmt.location, None, types.F64)
            elif isinstance(stmt, Print):
                if not stmt.is_string:
                    self._settle_default(stmt.value, self._infer(stmt.value, scope))
            elif isinstance(stmt, If):
                self._truth(stmt.condition, scope, "a condition")
                self._visit_block(stmt.body, scope)
                for arm in stmt.elifs:
                    self._truth(arm.condition, scope, "a condition")
                    self._visit_block(arm.body, scope)
                if stmt.orelse is not None:
                    self._visit_block(stmt.orelse, scope)
            elif isinstance(stmt, While):
                self._truth(stmt.condition, scope, "a condition")
                if stmt.name is not None:
                    self._check_loop_name(stmt)
                self._loops.append(stmt)
                self._visit_block(stmt.body, scope)
                self._loops.pop()
            elif isinstance(stmt, (Break, Continue)):
                self._loop_jump(stmt)
            elif isinstance(stmt, Block):
                self._visit_block(stmt, scope)
            elif isinstance(stmt, Label):
                self._diagnostics.warning(codes.DEPRECATED_GOTO, stmt.location, keyword="label", help=_GOTO_HELP)
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
                self._diagnostics.warning(codes.DEPRECATED_GOTO, stmt.location, keyword="goto", help=_GOTO_HELP)
                self._model.gotos.append(stmt)
                self._goto_sites.append((stmt, scope))

    def _check_loop_name(self, loop: While) -> None:
        self._check_name(loop.name, "loop", loop.name_location)
        enclosing = next((outer for outer in self._loops if outer.name == loop.name), None)
        if enclosing is not None:
            self._diagnostics.error(
                codes.LOOP_NAME_IN_USE, loop.name_location, name=loop.name,
                notes=((f"the enclosing loop '{loop.name}' is here", enclosing.name_location),),
                help="give the inner loop another name",
            )

    def _loop_jump(self, stmt: Break | Continue) -> None:
        """`break` / `continue` must be inside a loop, and a name must be the
        name of a loop around it."""
        keyword = "break" if isinstance(stmt, Break) else "continue"
        if not self._loops:
            self._diagnostics.error(codes.OUTSIDE_LOOP, stmt.location, keyword=keyword)
            return
        if stmt.name is not None and all(loop.name != stmt.name for loop in self._loops):
            names = [loop.name for loop in reversed(self._loops) if loop.name is not None]
            help = (f"the loops around it are named {', '.join(repr(n) for n in names)}" if names
                    else f"name the loop to leave: while ... as {stmt.name} {{")
            self._diagnostics.error(codes.UNKNOWN_LOOP, stmt.name_location, name=stmt.name, help=help)

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

    def _let(self, stmt: Let, scope: Scope) -> None:
        info = self._infer(stmt.value, scope)  # before declaring the target
        self._assign(stmt.name, scope, stmt.location, stmt.value, info)

    def _multi_let(self, stmt: MultiLet, scope: Scope) -> None:
        # Every value first, so none of them can see a target's new value
        # (or a target that this statement declares).
        infos = [self._infer(value, scope) for value in stmt.values]
        if len(stmt.targets) != len(stmt.values):
            self._diagnostics.error(
                codes.ASSIGNMENT_COUNT_MISMATCH, stmt.location,
                targets=_count(len(stmt.targets), "name"), values=_count(len(stmt.values), "value"),
            )
            return
        self._check_unique(list(stmt.targets))
        for (name, location), value, info in zip(stmt.targets, stmt.values, infos):
            self._assign(name, scope, location, value, info)

    def _check_unique(self, targets: list[tuple[str, SourceLocation]]) -> None:
        """Report each target named again later in the same statement."""
        first: dict[str, SourceLocation] = {}
        for name, location in targets:
            if name in first:
                self._diagnostics.error(
                    codes.DUPLICATE_TARGET, location, name=name,
                    notes=((f"'{name}' is first assigned here", first[name]),),
                )
            else:
                first[name] = location

    def _declaration(self, stmt: Declaration, scope: Scope) -> None:
        type_ = types.by_name(stmt.type_name)
        for declarator in stmt.declarators:
            info = None if declarator.value is None else self._infer(declarator.value, scope)
            self._check_name(declarator.name, "variable", declarator.location)
            existing = scope.lookup(declarator.name)
            if existing is not None:
                self._diagnostics.error(
                    codes.ALREADY_DECLARED, declarator.location, name=declarator.name,
                    notes=((f"'{declarator.name}' was declared here", existing.location),),
                    help=f"Scribe has no shadowing: pick another name, or assign with '{declarator.name} = ...'",
                )
                continue
            symbol = scope.declare(declarator.name, declarator.location, type_)
            if declarator.value is not None and info is not None:
                self._check_assignment(symbol, declarator.value, info)

    def _check_assignment(self, symbol: Symbol, value: Expr, info: _Info) -> None:
        target = symbol.type
        numeric = target != types.BOOL
        if numeric and (isinstance(info, _Const) or (info is _UNTYPED_FLOAT and target.is_float)):
            self._settle(value, target)
            return
        if isinstance(info, _Const):
            found = types.DEFAULT_INT
        elif info is _UNTYPED_FLOAT:
            found = types.DEFAULT_FLOAT
        else:
            found = info
        if not types.holds_all(found, target):
            help = None
            if target == types.BOOL and found.is_float:
                help = "compare it explicitly, such as x != 0.0"
            elif target.is_float or found.is_float or types.BOOL in (target, found):
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
        if isinstance(expr, BoolLit):
            return types.BOOL
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
            if info == types.BOOL:
                self._diagnostics.error(codes.BOOL_OPERATOR, expr.location, op=expr.operator)
                return None
            if isinstance(info, _Const) and expr.operator == "-":
                return _Const(-info.value)
            return info
        if isinstance(expr, Binary):
            return self._binary(expr, scope)
        if isinstance(expr, Cast):
            return self._cast(expr, scope)
        if isinstance(expr, Not):
            self._truth(expr.operand, scope, "the operand of 'not'")
            return types.BOOL
        if isinstance(expr, Logical):
            self._truth(expr.left, scope, f"the operand of '{expr.operator}'")
            self._truth(expr.right, scope, f"the operand of '{expr.operator}'")
            return types.BOOL
        if isinstance(expr, Comparison):
            self._compare(expr, [expr.left, expr.right], [expr.operator], [expr.location], scope)
            return types.BOOL
        if isinstance(expr, ComparisonChain):
            self._compare(expr, list(expr.operands), list(expr.operators), list(expr.operator_locations), scope)
            return types.BOOL
        raise TypeError(f"Unsupported expression node: {type(expr).__name__}")

    def _binary(self, expr: Binary, scope: Scope) -> _Info:
        left = self._infer(expr.left, scope)
        right = self._infer(expr.right, scope)
        if left is None or right is None:
            return None
        if types.BOOL in (left, right):
            self._diagnostics.error(codes.BOOL_OPERATOR, expr.operator_location, op=expr.operator)
            return None
        if expr.operator in ("//", "%"):
            floats = [info for info in (left, right) if info is _UNTYPED_FLOAT or (isinstance(info, ScalarType) and info.is_float)]
            if floats:
                type_ = types.DEFAULT_FLOAT if floats[0] is _UNTYPED_FLOAT else floats[0]
                help = ("use '/' for float division, or convert to an integer first: i64(x) // n"
                        if expr.operator == "//" else
                        "convert to an integer first: i64(x) % n; a float remainder is not available yet")
                self._diagnostics.error(codes.INTEGER_OPERATOR, expr.operator_location,
                                        op=expr.operator, type=type_, help=help)
                return None
        if expr.operator == "/" and isinstance(left, _Const) and isinstance(right, _Const):
            return _UNTYPED_FLOAT  # `7 / 2` is 3.5: the literals become floats
        if expr.operator == "**" and isinstance(left, _Const) and isinstance(right, _Const):
            base, exponent = left.value, right.value
            if exponent < 0:
                self._diagnostics.error(
                    codes.NEGATIVE_EXPONENT, expr.right.location, exponent=exponent,
                    help=f"for a fraction, raise a float: {base}.0 ** {exponent}",
                )
                return None
            # |base ** exponent| >= 2 ** ((bits - 1) * exponent): past 2 ** 16384
            # nothing can hold it (not even a future f128), so do not compute it.
            if abs(base) >= 2 and (abs(base).bit_length() - 1) * exponent > 16384:
                self._diagnostics.error(codes.CONSTANT_OVERFLOW, expr.location,
                                        value=f"{base} ** {exponent}", type="any type")
                return None
        if isinstance(left, _Const) and isinstance(right, _Const):
            value = _fold(expr.operator, left.value, right.value)
            if value is None:
                self._diagnostics.error(codes.CONSTANT_DIVISION_BY_ZERO, expr.operator_location)
                return None
            return _Const(value)
        if not isinstance(left, ScalarType) and not isinstance(right, ScalarType):
            return _UNTYPED_FLOAT  # literals only, at least one of them a float
        type_ = self._operand_type(expr, expr.operator_location, left, right)
        if expr.operator == "/" and type_ is not None and type_.is_integer:
            self._diagnostics.error(
                codes.FLOAT_DIVISION, expr.operator_location, type=type_,
                help="use '//' for integer division (it rounds down), or divide as floats: f64(a) / f64(b)",
            )
            return None
        return type_

    def _truth(self, expr: Expr, scope: Scope, what: str) -> None:
        self._truth_test(expr, self._infer(expr, scope), what)

    def _truth_test(self, expr: Expr, info: _Info, what: str) -> None:
        """Check that `expr` (already inferred as `info`) can be tested for
        truth: a bool or an integer, never a float."""
        if isinstance(info, _Const):
            self._settle(expr, types.DEFAULT_INT)
        elif info is _UNTYPED_FLOAT or (isinstance(info, ScalarType) and info.is_float):
            type_ = types.DEFAULT_FLOAT if info is _UNTYPED_FLOAT else info
            self._diagnostics.error(
                codes.NOT_A_TRUTH_VALUE, expr.location, what=what, type=type_,
                help="compare it explicitly, such as x != 0.0",
            )

    def _compare(self, node: Expr, operands: list[Expr], operators: list[str],
                 locations: list[SourceLocation], scope: Scope) -> None:
        """A comparison or a chain: check the operators, then find the one type
        every operand is compared in (recorded in `operand_types`)."""
        infos = [self._infer(operand, scope) for operand in operands]
        directions = [_DIRECTION[op] for op in operators]
        if "not-equal" in directions and len(operators) > 1:
            index = directions.index("not-equal")
            self._diagnostics.error(
                codes.CHAINED_NOT_EQUAL, locations[index],
                help="'a != b != c' does not mean all three differ; write the pairs you mean with 'and'",
            )
            return
        for op, direction, location in zip(operators, directions, locations):
            if direction != directions[0]:
                self._diagnostics.error(
                    codes.MIXED_COMPARISON_CHAIN, location, first=operators[0], op=op,
                    help="write the comparisons separately, joined with 'and'",
                )
                return
        if any(info is None for info in infos):
            return
        typed = [info for info in infos if isinstance(info, ScalarType)]
        if types.BOOL in typed:
            if any(info != types.BOOL for info in infos):
                other = next(info for info in infos if info != types.BOOL)
                self._no_common_type(operators[0], locations[0], types.BOOL, self._describe(other),
                                     help="a bool only compares with another bool, such as 'flag == true'")
                return
            for op, location in zip(operators, locations):
                if op not in ("==", "!="):
                    self._diagnostics.error(codes.BOOL_OPERATOR, location, op=op)
                    return
            self._model.operand_types[id(node)] = types.BOOL
            return
        if not typed:
            # Only constants, e.g. `if 1 > 0`: compare them as default types.
            all_int = all(isinstance(info, _Const) for info in infos)
            type_ = types.DEFAULT_INT if all_int else types.DEFAULT_FLOAT
        else:
            type_ = typed[0]
            for other in typed[1:]:
                joined = types.common_type(type_, other)
                if joined is None:
                    self._no_common_type(operators[0], locations[0], type_, other)
                    return
                type_ = joined
        for operand, info in zip(operands, infos):
            if info is _UNTYPED_FLOAT and not type_.is_float:
                self._no_common_type(operators[0], locations[0], type_, "a float constant")
                return
            if not isinstance(info, ScalarType):
                self._settle(operand, type_)
        self._model.operand_types[id(node)] = type_

    @staticmethod
    def _describe(info: _Info) -> ScalarType | str:
        if isinstance(info, _Const):
            return "an integer constant"
        if info is _UNTYPED_FLOAT:
            return "a float constant"
        return info

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

    def _no_common_type(self, op: str, where: SourceLocation, left, right, help: str | None = None) -> None:
        """`left` and `right` are types, or text such as "a float constant"."""
        if help is None:
            constants = {"a float constant": types.DEFAULT_FLOAT, "an integer constant": types.DEFAULT_INT}
            sides = [constants.get(t, t) if isinstance(t, str) else t for t in (left, right)]
            floats = [t for t in sides if t.is_float]
            ints = [t for t in sides if not t.is_float]
            help = "convert one side explicitly"
            if floats and ints:
                help += f": {floats[0]}(...) to work in {floats[0]}, or {ints[0]}(...) to work in {ints[0]}"
        self._diagnostics.error(codes.NO_COMMON_TYPE, where, op=op, left=left, right=right, help=help)

    def _cast(self, expr: Cast, scope: Scope) -> _Info:
        target = types.by_name(expr.type_name)
        info = self._infer(expr.operand, scope)
        if target == types.BOOL:
            # bool(n) is the truth test, written out: n != 0.
            self._truth_test(expr.operand, info, "the operand of bool(...)")
        elif isinstance(info, _Const):
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
