from __future__ import annotations

from dataclasses import dataclass, field

from .ast import (
    Binary, Block, Comparison, Expr, Goto, Grouped, If, Input, Label, Let,
    Print, Program, SourceLocation, Stmt, Unary, Variable, While,
)
from .errors import SemanticError


# Words the grammar treats as keywords. The contextual lexer only produces a
# keyword token where the parser can accept one, so e.g. `else` at the start of
# a statement lexes as an IDENT. Reject those names here instead of letting
# them reach the C compiler. tests/test_semantics.py checks this set against
# the keyword terminals in the grammar file so the two cannot drift apart.
RESERVED_WORDS = frozenset(
    {"print", "input", "if", "elif", "else", "while", "label", "goto"}
)


@dataclass
class Symbol:
    name: str
    kind: str = "variable"
    location: SourceLocation = field(default_factory=SourceLocation)


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

    def declare(self, name: str, location: SourceLocation) -> Symbol:
        symbol = Symbol(name, "variable", location)
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
    gotos: list[Goto] = field(default_factory=list)

    @property
    def symbols(self) -> dict[str, Symbol]:
        """Program-level (outermost scope) variables only."""
        return self.root.symbols


def _where(location: SourceLocation) -> str:
    if location.line is None:
        return ""
    return f" at {location.line}:{location.column}"


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
    """

    def analyze(self, program: Program) -> SemanticModel:
        model = SemanticModel()
        self._model = model
        self._goto_sites: list[tuple[Goto, Scope]] = []
        # Variables whose scope has already ended, for friendlier errors.
        self._closed: dict[str, SourceLocation] = {}

        self._visit_statements(program.statements, model.root)

        for goto, scope in self._goto_sites:
            label_scope = model.labels.get(goto.name)
            if label_scope is None:
                raise SemanticError(
                    f"GOTO to undeclared label '{goto.name}'{_where(goto.location)}"
                )
            if not label_scope.encloses(scope):
                raise SemanticError(
                    f"GOTO '{goto.name}'{_where(goto.location)} jumps into a "
                    f"nested block; a goto may only jump within its own block "
                    f"or out to an enclosing block"
                )
        return model

    # -- statements --------------------------------------------------------

    def _visit_statements(self, statements: tuple[Stmt, ...], scope: Scope) -> None:
        for stmt in statements:
            if isinstance(stmt, Let):
                self._expr(stmt.value, scope)  # before declaring the target
                self._assign(stmt.name, scope, stmt.location)
            elif isinstance(stmt, Input):
                self._assign(stmt.name, scope, stmt.location)
            elif isinstance(stmt, Print):
                if not stmt.is_string:
                    self._expr(stmt.value, scope)
            elif isinstance(stmt, If):
                self._expr(stmt.condition, scope)
                self._visit_block(stmt.body, scope)
                for arm in stmt.elifs:
                    self._expr(arm.condition, scope)
                    self._visit_block(arm.body, scope)
                if stmt.orelse is not None:
                    self._visit_block(stmt.orelse, scope)
            elif isinstance(stmt, While):
                self._expr(stmt.condition, scope)
                self._visit_block(stmt.body, scope)
            elif isinstance(stmt, Block):
                self._visit_block(stmt, scope)
            elif isinstance(stmt, Label):
                self._check_name(stmt.name, "label", stmt.location)
                if stmt.name in self._model.labels:
                    raise SemanticError(
                        f"duplicate label '{stmt.name}'{_where(stmt.location)}"
                    )
                self._model.labels[stmt.name] = scope
            elif isinstance(stmt, Goto):
                self._model.gotos.append(stmt)
                self._goto_sites.append((stmt, scope))

    def _visit_block(self, block: Block, parent: Scope) -> None:
        scope = Scope(parent)
        self._model.scopes[block] = scope
        self._visit_statements(block.statements, scope)
        for name, symbol in scope.symbols.items():
            self._closed[name] = symbol.location

    def _assign(self, name: str, scope: Scope, location: SourceLocation) -> None:
        self._check_name(name, "variable", location)
        if scope.lookup(name) is None:
            scope.declare(name, location)

    @staticmethod
    def _check_name(name: str, what: str, location: SourceLocation) -> None:
        if name in RESERVED_WORDS:
            raise SemanticError(
                f"'{name}' is a reserved word and cannot be used as a "
                f"{what} name{_where(location)}"
            )

    # -- expressions -------------------------------------------------------

    def _expr(self, expr: Expr, scope: Scope) -> None:
        if isinstance(expr, Variable):
            if scope.lookup(expr.name) is None:
                message = f"use of undeclared variable '{expr.name}'{_where(expr.location)}"
                gone = self._closed.get(expr.name)
                if gone is not None:
                    message += (
                        f" ('{expr.name}' was declared in a block that ended; "
                        f"first assigned at {gone.line}:{gone.column})"
                    )
                raise SemanticError(message)
        elif isinstance(expr, Grouped):
            self._expr(expr.value, scope)
        elif isinstance(expr, Unary):
            self._expr(expr.operand, scope)
        elif isinstance(expr, Binary):
            self._expr(expr.left, scope)
            self._expr(expr.right, scope)
        elif isinstance(expr, Comparison):
            self._expr(expr.left, scope)
            self._expr(expr.right, scope)
