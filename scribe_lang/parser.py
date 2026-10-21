from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from lark import Lark, Transformer, Token
from lark.exceptions import UnexpectedCharacters, UnexpectedInput, UnexpectedToken

from .ast import (
    Binary, Block, Cast, Comparison, Elif, FloatLit, Goto, Grouped, If, Input,
    IntLit, Label, Let, Print, Program, SourceLocation, Stmt, Unary, Variable,
    While,
)
from . import diagnostics as codes
from .diagnostics import Diagnostics, Span
from .errors import ParseError
from .render import render_text


_GRAMMAR_PATH = Path(__file__).resolve().parent / "grammar" / "scribe_lang.lark"

def _loc(item) -> SourceLocation:
    return SourceLocation(
        line=getattr(item, "line", None),
        column=getattr(item, "column", None),
        start_pos=getattr(item, "start_pos", None),
        end_pos=getattr(item, "end_pos", None),
        end_line=getattr(item, "end_line", None),
        end_column=getattr(item, "end_column", None),
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

    def int_literal(self, items):
        text = str(items[0])
        return IntLit(int(text, 0), text, _loc(items[0]))

    def float_literal(self, items):
        text = str(items[0]).replace("_", "")
        is_f32 = text.endswith("f")
        return FloatLit(text.removesuffix("f"), is_f32, _loc(items[0]))

    def cast_type(self, items):
        return items[0]

    def cast(self, items):
        type_token, operand = items
        return Cast(str(type_token), operand, _loc(type_token))

    def variable(self, items):
        return Variable(str(items[0]), _loc(items[0]))

    def grouped(self, items):
        # The parentheses are anonymous tokens and are filtered out, so take
        # the location of the expression inside them.
        return Grouped(items[0], items[0].location)

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
        op = items[i]
        rhs = items[i + 1]
        node = Binary(node, str(op), rhs, getattr(node, "location", SourceLocation()), _loc(op))
    return node


_ESCAPES = {'"': '"', "\\": "\\", "n": "\n", "r": "\r", "t": "\t"}
_ESCAPE_RE = re.compile(r"\\(.)")


def _decode_string(token_text: str) -> str:
    # The STRING terminal only admits the escapes in _ESCAPES. Decode them by
    # hand: `unicode_escape` would also re-read non-ASCII text as Latin-1.
    return _ESCAPE_RE.sub(lambda m: _ESCAPES[m.group(1)], token_text[1:-1])


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

    def parse(self, source: str, diagnostics: Diagnostics | None = None) -> Program | None:
        """Parse `source`, or report every syntax error and return None.

        After an error the parser skips to the next statement and carries on
        (see `_skip_statement`), so one run reports one error per broken
        statement, up to MAX_SYNTAX_ERRORS. An error at the end of the file
        cannot be skipped and ends the search.

        Without a `diagnostics` collector, a syntax error raises ParseError
        (which carries the diagnostics) instead; handy in tests and scripts.
        """
        sink = diagnostics if diagnostics is not None else Diagnostics()
        text = source
        tree = None
        failed = False
        for _ in range(MAX_SYNTAX_ERRORS):
            try:
                tree = self._parser.parse(text)
                break
            except UnexpectedInput as exc:
                failed = True
                _report_syntax_error(exc, sink, source, text)
                text = _skip_statement(text, exc)
                if text is None:
                    break
        if failed:
            if diagnostics is None:
                raise ParseError(render_text(sink, source), sink)
            return None
        return ASTBuilder().transform(tree)


# -- recovery -----------------------------------------------------------------

MAX_SYNTAX_ERRORS = 50

_STRUCTURE = re.compile(r'"(?:[^"\\\n]|\\.)*"?|#[^\n]*|[{};\n]')


def _marks(text: str) -> list[tuple[int, str]]:
    """Positions of `{`, `}`, `;` and newlines outside strings and comments."""
    return [(m.start(), m.group()) for m in _STRUCTURE.finditer(text) if len(m.group()) == 1]


def _statement_start(marks: list[tuple[int, str]], pos: int) -> int:
    """Index just after the last separator before `pos`."""
    start = 0
    for index, _ in marks:
        if index >= pos:
            break
        start = index + 1
    return start


def _error_position(exc: UnexpectedInput) -> tuple[int, int]:
    """(index, width) of what the parser choked on."""
    if isinstance(exc, UnexpectedToken):
        return exc.token.start_pos, max(len(exc.token), 1)
    return exc.pos_in_stream, 1


def _skip_statement(text: str, exc: UnexpectedInput) -> str | None:
    """`text` with the statement containing the error blanked out.

    The statement runs from just after the previous separator (newline, `;`,
    `{` or `}`) to the next newline or `;`. If it opens blocks, it runs on to
    the `}` that closes them, so `if x > {` takes its whole body with it and
    the braces stay balanced. Blanked characters become spaces and newlines
    are kept, so every position reported later is still right.

    Returns None when there is nothing left to skip (end of file).
    """
    if isinstance(exc, UnexpectedToken) and exc.token.type == "$END":
        return None
    pos, width = _error_position(exc)

    marks = _marks(text)
    start = _statement_start(marks, pos)
    end = len(text)
    depth = 0
    for index, char in marks:
        if index < start:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            if depth == 0:
                end = index
                break
            depth -= 1
        elif depth == 0 and index >= pos:  # newline or ';'
            end = index
            break
    end = max(end, pos + width)  # always skip at least the offending token

    blanked = "".join(c if c in "\r\n" else " " for c in text[start:end])
    new_text = text[:start] + blanked + text[end:]
    return None if new_text == text else new_text


# -- syntax error wording -----------------------------------------------------
# Lark speaks in terminal names (`IDENT`, `_NL`, `$END`); users should not have
# to. Add an entry here when a new terminal is added to the grammar.

_TERMINAL_WORDS = {
    "_NL": "end of line",
    "SEMICOLON": "';'",
    "$END": "end of file",
    "IDENT": "a name",
    "INT_LIT": "a number",
    "FLOAT_LIT": "a number",
    "STRING": "a string",
    "LBRACE": "'{'",
    "RBRACE": "'}'",
    "LPAR": "'('",
    "RPAR": "')'",
    "EQUAL": "'='",
    "COMP_OP": "a comparison operator",
    "ADD_OP": "an operator",
    "MUL_OP": "an operator",
    "SIGN": "'+' or '-'",
}
_KEYWORDS = {"PRINT", "INPUT", "IF", "ELIF", "ELSE", "WHILE", "LABEL", "GOTO", "I64", "F32", "F64"}

# When every terminal of a group is expected, say the group's name instead.
_GROUPS = [
    ("a statement", {"PRINT", "INPUT", "IF", "WHILE", "LABEL", "GOTO", "IDENT", "LBRACE"}),
    ("an expression", {"INT_LIT", "FLOAT_LIT", "IDENT", "LPAR", "SIGN", "I64", "F32", "F64"}),
]


def _terminal_word(name: str) -> str:
    if name in _KEYWORDS:
        return f"'{name.lower()}'"
    return _TERMINAL_WORDS.get(name, name)


def describe_expected(expected: set[str]) -> str:
    """`{'IDENT', 'INT_LIT', 'LPAR', ...}` -> "an expression"."""
    remaining = set(expected)
    words: list[str] = []
    for word, group in _GROUPS:
        if group <= remaining:
            words.append(word)
            remaining -= group
    if "_NL" in remaining:
        # "end of line" covers both separators, and the end of the file.
        remaining -= {"SEMICOLON", "$END"}
    for name in sorted(remaining, key=lambda n: (n.startswith(("_", "$")), n)):
        word = _terminal_word(name)
        if word not in words:
            words.append(word)
    if len(words) <= 1:
        return "".join(words)
    return ", ".join(words[:-1]) + " or " + words[-1]


def describe_token(token: Token) -> str:
    if token.type == "IDENT":
        return f"name '{token}'"
    if token.type in ("INT_LIT", "FLOAT_LIT"):
        return f"number {token}"
    if token.type == "STRING":
        return f"string {token}"
    if token.type in _KEYWORDS:
        return f"'{token}'"
    word = _TERMINAL_WORDS.get(token.type)
    if word is not None and token.type not in ("COMP_OP", "ADD_OP", "MUL_OP", "SIGN"):
        return word
    return f"'{token}'"


def _token_span(token: Token, filename: str | None) -> Span:
    if token.type == "_NL":
        # A newline token ends on the next line; point at where it starts.
        return Span(filename, token.line, token.column, token.line, token.column + 1)
    return Span(filename, token.line, token.column, token.end_line, token.end_column)


def _end_of_file(source: str, filename: str | None) -> Span:
    """Just past the last non-blank character, where the file "ends"."""
    text = source.rstrip()
    line = text.count("\n") + 1
    column = len(text) - (text.rfind("\n") + 1) + 1
    return Span(filename, line, column)


def _expected_terminals(exc: UnexpectedToken) -> set[str]:
    # LALR merges lookaheads between states, so `exc.expected` can list
    # terminals that would fail a moment later. `accepts()` tries each one.
    if exc.interactive_parser is not None:
        return set(exc.interactive_parser.accepts())
    return set(exc.expected)


# -- hints: specific messages for common mistakes -------------------------------
# Each hint looks at a syntax error and either reports a specific diagnostic
# and returns True, or returns False to let the next one try. The generic
# "unexpected X; expected Y" message is the fallback. Add a hint here when a
# new feature brings a mistake worth explaining.

@dataclass(frozen=True)
class _SyntaxError:
    exc: UnexpectedInput
    text: str             # the text being parsed (earlier errors blanked out)
    source: str           # the original source, for end-of-file positions
    diagnostics: Diagnostics

    @property
    def filename(self) -> str | None:
        return self.diagnostics.filename

    def span_at(self, index: int, width: int = 1) -> Span:
        line = self.text.count("\n", 0, index) + 1
        column = index - (self.text.rfind("\n", 0, index) + 1) + 1
        return Span(self.filename, line, column, line, column + width)

    def statement_words(self) -> list[tuple[int, str]]:
        """Words (with their index) from the start of the failing statement
        up to the error."""
        pos, _ = _error_position(self.exc)
        start = _statement_start(_marks(self.text), pos)
        return [(start + m.start(), m.group()) for m in re.finditer(r"[A-Za-z_]\w*", self.text[start:pos])]

    def unexpected(self, type_: str) -> bool:
        return isinstance(self.exc, UnexpectedToken) and self.exc.token.type == type_


def _hint_misplaced_else(err: _SyntaxError) -> bool:
    # `else` / `elif` at the start of a statement lexes as a name, so a
    # `} else {` split over two lines fails just after it.
    if not isinstance(err.exc, UnexpectedToken):
        return False
    words = err.statement_words()
    if len(words) != 1 or words[0][1] not in ("else", "elif"):
        return False
    index, word = words[0]
    err.diagnostics.error(
        codes.MISPLACED_ELSE, err.span_at(index, len(word)), word=word,
        help=f"join the lines: '}} {word} ...'",
    )
    return True


def _hint_reserved_word_assignment(err: _SyntaxError) -> bool:
    # `print = 1`: the keyword is lexed as a keyword, so the '=' is the error.
    if not err.unexpected("EQUAL"):
        return False
    words = err.statement_words()
    if len(words) != 1 or words[0][1].upper() not in _KEYWORDS:
        return False
    index, word = words[0]
    err.diagnostics.error(codes.RESERVED_NAME, err.span_at(index, len(word)), name=word, what="variable")
    return True


def _hint_unclosed_block(err: _SyntaxError) -> bool:
    if not err.unexpected("$END") or "RBRACE" not in _expected_terminals(err.exc):
        return False
    open_braces = []
    for index, char in _marks(err.text):
        if char == "{":
            open_braces.append(index)
        elif char == "}" and open_braces:
            open_braces.pop()
    if not open_braces:
        return False
    err.diagnostics.error(
        codes.UNCLOSED_BLOCK, err.span_at(open_braces[-1]),
        notes=(("the file ends here", _end_of_file(err.source, err.filename)),),
    )
    return True


def _hint_unmatched_closing_brace(err: _SyntaxError) -> bool:
    if not err.unexpected("RBRACE"):
        return False
    pos, _ = _error_position(err.exc)
    depth = 0
    for index, char in _marks(err.text):
        if index >= pos:
            break
        depth += {"{": 1, "}": -1}.get(char, 0)
    if depth > 0:
        return False
    err.diagnostics.error(
        codes.UNMATCHED_CLOSING_BRACE, err.span_at(pos),
        help="remove it, or add the '{' it was meant to close",
    )
    return True


def _hint_bad_string(err: _SyntaxError) -> bool:
    if not isinstance(err.exc, UnexpectedCharacters) or err.exc.char != '"':
        return False
    pos = err.exc.pos_in_stream
    line_end = err.text.find("\n", pos)
    rest = err.text[pos + 1: line_end if line_end != -1 else len(err.text)]
    # Walk the string as the lexer would: a bad escape or the end of the line.
    i = 0
    while i < len(rest):
        if rest[i] == '"':
            break
        if rest[i] == "\\":
            escape = rest[i: i + 2]
            if escape[1:] not in _ESCAPES:
                err.diagnostics.error(
                    codes.INVALID_ESCAPE, err.span_at(pos + 1 + i, len(escape)), escape=escape,
                    help="the escapes are \\\" \\\\ \\n \\r \\t",
                )
                return True
            i += 2
            continue
        i += 1
    else:
        err.diagnostics.error(
            codes.UNTERMINATED_STRING, err.span_at(pos, len(rest) + 1),
            help="close it with '\"' on the same line",
        )
        return True
    return False


_HINTS = [
    _hint_misplaced_else,
    _hint_reserved_word_assignment,
    _hint_unclosed_block,
    _hint_unmatched_closing_brace,
    _hint_bad_string,
]


def _report_syntax_error(exc: UnexpectedInput, diagnostics: Diagnostics, source: str, text: str | None = None) -> None:
    err = _SyntaxError(exc, source if text is None else text, source, diagnostics)
    for hint in _HINTS:
        if hint(err):
            return
    filename = diagnostics.filename
    if isinstance(exc, UnexpectedToken):
        expected = describe_expected(_expected_terminals(exc))
        if exc.token.type == "$END":
            diagnostics.error(codes.UNEXPECTED_END_OF_FILE, _end_of_file(source, filename), expected=expected)
        else:
            diagnostics.error(
                codes.UNEXPECTED_TOKEN, _token_span(exc.token, filename),
                found=describe_token(exc.token), expected=expected,
            )
    elif isinstance(exc, UnexpectedCharacters):
        diagnostics.error(
            codes.UNEXPECTED_CHARACTER,
            Span(filename, exc.line, exc.column, exc.line, exc.column + 1),
            char=repr(exc.char),
        )
    else:  # pragma: no cover - Lark's LALR parser raises only the two above
        diagnostics.error(codes.INTERNAL_ERROR, Span(filename, exc.line, exc.column), detail=str(exc))
