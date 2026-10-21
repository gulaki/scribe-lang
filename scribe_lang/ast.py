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

    condition: Comparison
    body: Block
    location: SourceLocation = field(default_factory=SourceLocation)


@dataclass(frozen=True)
class If(Stmt):
    condition: Comparison
    body: Block
    elifs: tuple[Elif, ...] = ()
    orelse: Block | None = None
    location: SourceLocation = field(default_factory=SourceLocation)


@dataclass(frozen=True)
class While(Stmt):
    condition: Comparison
    body: Block
    location: SourceLocation = field(default_factory=SourceLocation)


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
class Cast(Expr):
    """`f64(x)`: converts `operand` to the type called `type_name`."""

    type_name: str
    operand: Expr
    location: SourceLocation = field(default_factory=SourceLocation)


StmtType = Union[Print, Input, Let, If, While, Block, Label, Goto]
