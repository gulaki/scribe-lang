from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union


@dataclass(frozen=True)
class SourceLocation:
    """Where a node came from. Lines and columns are 1-based; `end_column` and
    `end_pos` point just past the last character."""

    line: int | None = None
    column: int | None = None
    start_pos: int | None = None
    end_pos: int | None = None
    end_line: int | None = None
    end_column: int | None = None


class Node:
    location: SourceLocation


@dataclass(frozen=True)
class Program(Node):
    statements: tuple[Stmt, ...]
    location: SourceLocation = field(default_factory=SourceLocation)


class Stmt(Node):
    pass


@dataclass(frozen=True)
class Print(Stmt):
    value: Expr | str
    is_string: bool = False
    location: SourceLocation = field(default_factory=SourceLocation)


@dataclass(frozen=True)
class Input(Stmt):
    name: str
    location: SourceLocation = field(default_factory=SourceLocation)


@dataclass(frozen=True)
class Let(Stmt):
    name: str
    value: Expr
    location: SourceLocation = field(default_factory=SourceLocation)


@dataclass(frozen=True)
class ChainedLet(Stmt):
    """`a = b = c = e`, kept as the assignments it means, in order:
    `c = e`, `b = c`, `a = b`. The value is computed once."""

    lets: tuple[Let, ...]
    location: SourceLocation = field(default_factory=SourceLocation)


@dataclass(frozen=True)
class MultiLet(Stmt):
    """`a, b = x, y`: every value is evaluated, left to right, before any
    target is assigned. `targets` holds (name, location) pairs."""

    targets: tuple[tuple[str, SourceLocation], ...]
    values: tuple[Expr, ...]
    location: SourceLocation = field(default_factory=SourceLocation)


@dataclass(frozen=True)
class Declarator(Node):
    """One `name` or `name = value` of a Declaration. Not a statement itself."""

    name: str
    value: Expr | None = None
    location: SourceLocation = field(default_factory=SourceLocation)


@dataclass(frozen=True)
class Declaration(Stmt):
    """`i64: a, b = 5`: declares each name with the type `type_name`."""

    type_name: str
    declarators: tuple[Declarator, ...]
    location: SourceLocation = field(default_factory=SourceLocation)


# eq=False: a Block is compared and hashed by identity, never by value. Two
# textually identical blocks are still two different scopes, and the semantic
# model uses Block objects as dictionary keys.
@dataclass(frozen=True, eq=False)
class Block(Stmt):
    """A `{ ... }` list of statements. Every Block is its own variable scope."""

    statements: tuple[Stmt, ...]
    location: SourceLocation = field(default_factory=SourceLocation)


@dataclass(frozen=True)
class Elif(Node):
    """One `elif <condition> { ... }` arm of an If. Not a statement itself."""

    condition: Expr
    body: Block
    location: SourceLocation = field(default_factory=SourceLocation)


@dataclass(frozen=True)
class If(Stmt):
    condition: Expr
    body: Block
    elifs: tuple[Elif, ...] = ()
    orelse: Block | None = None
    location: SourceLocation = field(default_factory=SourceLocation)


@dataclass(frozen=True)
class While(Stmt):
    """`while cond { ... }`, or `while cond as name { ... }` for a loop that
    `break name` and `continue name` can refer to."""

    condition: Expr
    body: Block
    location: SourceLocation = field(default_factory=SourceLocation)
    name: str | None = None
    name_location: SourceLocation = field(default_factory=SourceLocation, compare=False)


@dataclass(frozen=True)
class Break(Stmt):
    """`break` leaves the innermost loop; `break name` the loop called `name`."""

    name: str | None = None
    location: SourceLocation = field(default_factory=SourceLocation)
    name_location: SourceLocation = field(default_factory=SourceLocation, compare=False)


@dataclass(frozen=True)
class Continue(Stmt):
    """`continue` goes on to the next pass of the innermost loop, or of the
    loop called `name`."""

    name: str | None = None
    location: SourceLocation = field(default_factory=SourceLocation)
    name_location: SourceLocation = field(default_factory=SourceLocation, compare=False)


@dataclass(frozen=True)
class Label(Stmt):
    name: str
    location: SourceLocation = field(default_factory=SourceLocation)


@dataclass(frozen=True)
class Goto(Stmt):
    name: str
    location: SourceLocation = field(default_factory=SourceLocation)


class Expr(Node):
    pass


@dataclass(frozen=True)
class IntLit(Expr):
    """An integer literal. `text` is the spelling, for messages."""

    value: int
    text: str = ""
    location: SourceLocation = field(default_factory=SourceLocation)


@dataclass(frozen=True)
class FloatLit(Expr):
    """A float literal. `text` is the spelling without `_` or the `f` suffix;
    `is_f32` is True when it had the suffix (`2.5f`)."""

    text: str
    is_f32: bool = False
    location: SourceLocation = field(default_factory=SourceLocation)


@dataclass(frozen=True)
class BoolLit(Expr):
    value: bool
    location: SourceLocation = field(default_factory=SourceLocation)


@dataclass(frozen=True)
class Variable(Expr):
    name: str
    location: SourceLocation = field(default_factory=SourceLocation)


@dataclass(frozen=True)
class Grouped(Expr):
    value: Expr
    location: SourceLocation = field(default_factory=SourceLocation)


@dataclass(frozen=True)
class Unary(Expr):
    operator: str
    operand: Expr
    location: SourceLocation = field(default_factory=SourceLocation)


@dataclass(frozen=True)
class Binary(Expr):
    left: Expr
    operator: str
    right: Expr
    location: SourceLocation = field(default_factory=SourceLocation)
    # Where the operator is, for type errors and runtime error messages.
    operator_location: SourceLocation = field(default_factory=SourceLocation, compare=False)


@dataclass(frozen=True)
class Comparison(Expr):
    left: Expr
    operator: str
    right: Expr
    location: SourceLocation = field(default_factory=SourceLocation)


@dataclass(frozen=True)
class ComparisonChain(Expr):
    """`a < b <= c`: means `a < b and b <= c`, with `b` evaluated once.
    There is one more operand than operators."""

    operands: tuple[Expr, ...]
    operators: tuple[str, ...]
    operator_locations: tuple[SourceLocation, ...] = ()
    location: SourceLocation = field(default_factory=SourceLocation)


@dataclass(frozen=True)
class Not(Expr):
    operand: Expr
    location: SourceLocation = field(default_factory=SourceLocation)


@dataclass(frozen=True)
class Logical(Expr):
    """`a and b`, `a or b`: short-circuiting, with a bool result."""

    left: Expr
    operator: str
    right: Expr
    location: SourceLocation = field(default_factory=SourceLocation)


@dataclass(frozen=True)
class Cast(Expr):
    """`f64(x)`: converts `operand` to the type called `type_name`."""

    type_name: str
    operand: Expr
    location: SourceLocation = field(default_factory=SourceLocation)


StmtType = Union[Print, Input, Let, ChainedLet, MultiLet, Declaration, If, While, Break, Continue, Block, Label, Goto]
