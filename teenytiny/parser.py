from __future__ import annotations

from pathlib import Path

from lark import Lark, Transformer, Token
from lark.exceptions import UnexpectedCharacters, UnexpectedInput, UnexpectedToken

from .ast import (
    Binary, Block, Comparison, Elif, Goto, Grouped, If, Input, Label, Let,
    Number, Print, Program, SourceLocation, Stmt, Unary, Variable, While,
)
from .errors import ParseError


_GRAMMAR_PATH = Path(__file__).resolve().parent / "grammar" / "teenytiny.lark"


def _loc(item) -> SourceLocation:
    return SourceLocation(
        line=getattr(item, "line", None),
        column=getattr(item, "column", None),
        start_pos=getattr(item, "start_pos", None),
        end_pos=getattr(item, "end_pos", None),
    )


class ASTBuilder(Transformer):
    """Convert Lark's concrete parse tree into a small, stable AST."""

    def start(self, items):
        return items[0]

    def program(self, items):
        return Program(tuple(item for item in items if isinstance(item, Stmt)))

    def statement(self, items):
        return items[0]

    def block(self, items):
        # LBRACE, statement..., RBRACE. The separators are inlined away.
        statements = tuple(item for item in items if isinstance(item, Stmt))
        return Block(statements, _loc(items[0]))

    def print_stmt(self, items):
        token = items[0]
        value = items[1]
        if isinstance(value, Token) and value.type == "STRING":
            return Print(_decode_string(str(value)), True, _loc(token))
        return Print(value, False, _loc(token))

    def input_stmt(self, items):
        return Input(str(items[1]), _loc(items[0]))

    def let_stmt(self, items):
        return Let(str(items[0]), items[1], _loc(items[0]))

    def if_stmt(self, items):
        # IF, comparison, Block, (ELIF, comparison, Block)*, (ELSE, Block)?
        if_token, condition, body, *rest = items
        elifs = []
        orelse = None
        i = 0
        while i < len(rest):
            token = rest[i]
            if token.type == "ELIF":
                elifs.append(Elif(rest[i + 1], rest[i + 2], _loc(token)))
                i += 3
            else:  # ELSE
                orelse = rest[i + 1]
                i += 2
        return If(condition, body, tuple(elifs), orelse, _loc(if_token))

    def while_stmt(self, items):
        # WHILE, comparison, Block
        return While(items[1], items[2], _loc(items[0]))

    def label_stmt(self, items):
        return Label(str(items[1]), _loc(items[0]))

    def goto_stmt(self, items):
        return Goto(str(items[1]), _loc(items[0]))

    def comparison(self, items):
        return Comparison(items[0], str(items[1]), items[2], _loc(items[1]))

    def expression(self, items):
        return _fold_binary(items)

    def term(self, items):
        return _fold_binary(items)

    def unary(self, items):
        if len(items) == 1:
            return items[0]
        return Unary(str(items[0]), items[1], _loc(items[0]))

    def number(self, items):
        return Number(str(items[0]), _loc(items[0]))

    def variable(self, items):
        return Variable(str(items[0]), _loc(items[0]))

    def grouped(self, items):
        return Grouped(items[0], _loc(items[0]))

    def ADD_OP(self, token):
        return token

    def MUL_OP(self, token):
        return token

    def SIGN(self, token):
        return token


def _fold_binary(items):
    if len(items) == 1:
        return items[0]
    node = items[0]
    for i in range(1, len(items), 2):
        op = str(items[i])
        rhs = items[i + 1]
        node = Binary(node, op, rhs, getattr(node, "location", SourceLocation()))
    return node


def _decode_string(token_text: str) -> str:
    raw = token_text[1:-1]
    # Language deliberately keeps escaping small and C-friendly.
    return bytes(raw, "utf-8").decode("unicode_escape")


class Parser:
    def __init__(self, grammar_path: str | Path | None = None):
        path = Path(grammar_path) if grammar_path else _GRAMMAR_PATH
        self.grammar_path = path
        self._parser = Lark.open(
            str(path),
            parser="lalr",
            lexer="contextual",
            start="start",
            propagate_positions=True,
            maybe_placeholders=False,
            cache=True,
        )

    def parse(self, source: str, filename: str | None = None) -> Program:
        try:
            tree = self._parser.parse(source)
            return ASTBuilder().transform(tree)
        except UnexpectedInput as exc:
            line = getattr(exc, "line", None)
            column = getattr(exc, "column", None)
            message = self._format_lark_error(exc)
            suffix = f" at {filename}" if filename else ""
            raise ParseError(f"{message}{suffix}:{line}:{column}") from exc

    @staticmethod
    def _format_lark_error(exc: UnexpectedInput) -> str:
        if isinstance(exc, UnexpectedToken):
            expected = ", ".join(sorted(exc.expected))
            return f"unexpected token {exc.token!r}; expected one of: {expected}"
        if isinstance(exc, UnexpectedCharacters):
            return f"unexpected character {exc.char!r}"
        return str(exc)
