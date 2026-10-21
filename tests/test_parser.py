import pytest

from scribe_lang.ast import Block, Elif, If, Let, Print, While
from scribe_lang.diagnostics import Diagnostics
from scribe_lang.errors import ParseError
from scribe_lang.parser import Parser

PARSER = Parser()


def parse(source):
    return PARSER.parse(source)


def test_if_elif_else_ast_shape():
    program = parse('''\
x = 1
if x > 0 {
    print "pos"
} elif x < 0 {
    print "neg"
} elif x == 0 {
    print "zero"
} else {
    print "other"
}
''')
    assert len(program.statements) == 2
    stmt = program.statements[1]
    assert isinstance(stmt, If)
    assert stmt.condition.operator == ">"
    assert isinstance(stmt.body, Block)
    assert isinstance(stmt.body.statements[0], Print)
    assert len(stmt.elifs) == 2
    assert all(isinstance(arm, Elif) for arm in stmt.elifs)
    assert [arm.condition.operator for arm in stmt.elifs] == ["<", "=="]
    assert isinstance(stmt.orelse, Block)
    assert len(stmt.orelse.statements) == 1


def test_if_without_elif_or_else():
    stmt = parse("if 1 > 0 {\n    print 1\n}\n").statements[0]
    assert isinstance(stmt, If)
    assert stmt.elifs == ()
    assert stmt.orelse is None


def test_if_else_without_elif():
    stmt = parse("if 1 > 0 {\n} else {\n    print 2\n}\n").statements[0]
    assert stmt.elifs == ()
    assert len(stmt.orelse.statements) == 1


def test_while_body_is_a_block():
    stmt = parse("while 1 > 0 {\n    x = 1\n    print x\n}\n").statements[0]
    assert isinstance(stmt, While)
    assert isinstance(stmt.body, Block)
    assert len(stmt.body.statements) == 2


def test_standalone_block_statement():
    program = parse("{\n    x = 1\n}\n")
    assert len(program.statements) == 1
    assert isinstance(program.statements[0], Block)
    assert isinstance(program.statements[0].statements[0], Let)


def test_nested_blocks():
    outer = parse("{\n    {\n        {\n            x = 1\n        }\n    }\n}\n").statements[0]
    middle = outer.statements[0]
    inner = middle.statements[0]
    assert isinstance(inner, Block) and len(inner.statements) == 1


def test_empty_blocks():
    program = parse("if 1 > 0 { }\nwhile 0 > 1 {}\n{}\n{\n}\n")
    assert len(program.statements) == 4
    assert program.statements[0].body.statements == ()
    assert program.statements[1].body.statements == ()
    assert program.statements[2].statements == ()


def test_single_line_blocks_and_semicolons():
    stmt = parse("if 1 > 0 { print 1; print 2 }\n").statements[0]
    assert len(stmt.body.statements) == 2
    assert len(parse("x = 1; y = 2\n").statements) == 2
    assert len(parse("x = 1;\ny = 2;\n").statements) == 2


def test_blank_lines_and_comments_inside_blocks():
    program = parse('''\
while 1 > 0 {

    # a comment on its own line

    x = 1   # trailing comment

}
''')
    assert len(program.statements[0].body.statements) == 1


def test_final_newline_is_optional():
    assert len(parse("x = 1").statements) == 1
    assert len(parse("if 1 > 0 { print 1 }").statements) == 1


@pytest.mark.parametrize("source", ["", "\n\n", "# only a comment\n", "  \n# c\n\n"])
def test_empty_programs(source):
    assert parse(source).statements == ()


def test_block_and_if_locations_point_at_their_keywords():
    program = parse("x = 1\nif x > 0 {\n    print x\n}\n")
    stmt = program.statements[1]
    assert (stmt.location.line, stmt.location.column) == (2, 1)
    assert (stmt.body.location.line, stmt.body.location.column) == (2, 10)


def test_blocks_compare_by_identity_not_by_value():
    # Same contents and the same (default) location: only identity can tell
    # them apart, and the semantic model relies on that to key scopes.
    first, second = Block(()), Block(())
    assert first != second
    assert len({first, second}) == 2
    assert first == first


REJECTED = {
    "old then/endif syntax": "if 1 > 0 then\n    print 1\nendif\n",
    "old repeat/endwhile syntax": "while 1 > 0 repeat\n    print 1\nendwhile\n",
    "bare endwhile": "endwhile\n",
    "if without a block": "if 1 > 0\n    print 1\n",
    "while without a block": "while 1 > 0\n    print 1\n",
    "opening brace on its own line": "if 1 > 0\n{\n    print 1\n}\n",
    "else on its own line": "if 1 > 0 {\n}\nelse {\n}\n",
    "elif on its own line": "if 1 > 0 {\n}\nelif 1 > 0 {\n}\n",
    "elif after else": "if 1 > 0 {\n} else {\n} elif 1 > 0 {\n}\n",
    "two else blocks": "if 1 > 0 {\n} else {\n} else {\n}\n",
    "else without if": "else {\n}\n",
    "elif without if": "elif 1 > 0 {\n}\n",
    "else with a condition": "if 1 > 0 {\n} else 2 > 1 {\n}\n",
    "else if (the keyword is elif)": "if 1 > 0 {\n} else if 2 > 1 {\n}\n",
    "unclosed block": "while 1 > 0 {\n    print 1\n",
    "unopened close brace": "}\n",
    "close brace after a statement": "x = 1 }\n",
    "condition is not a comparison": "if x {\n}\n",
    "two statements on one line": "x = 1 y = 2\n",
    "statement after a closing brace": "if 1 > 0 { print 1 } print 2\n",
}


@pytest.mark.parametrize("source", REJECTED.values(), ids=REJECTED.keys())
def test_invalid_syntax_is_rejected(source):
    with pytest.raises(ParseError):
        parse(source)


def test_parse_error_reports_filename_line_and_column():
    diags = Diagnostics("prog.scribe")
    assert PARSER.parse("if 1 > 0 then\n", diags) is None
    (diag,) = diags
    assert (diag.span.filename, diag.span.line, diag.span.column) == ("prog.scribe", 1, 10)


def test_removed_keywords_are_ordinary_identifiers():
    program = parse("then = 1\nendif = 2\nrepeat = 3\nendwhile = 4\n")
    assert [stmt.name for stmt in program.statements] == ["then", "endif", "repeat", "endwhile"]


def test_locations_record_where_a_token_ends():
    stmt = parse("x = 1\nprint total\n").statements[1]
    loc = stmt.value.location
    assert (loc.line, loc.column, loc.end_line, loc.end_column) == (2, 7, 2, 12)


# -- syntax error wording -----------------------------------------------------

def syntax_errors(source):
    diags = Diagnostics("t.scribe")
    assert PARSER.parse(source, diags) is None
    return [(x.code.code, x.span.line, x.span.column, x.message) for x in diags]


@pytest.mark.parametrize("source, expected", [
    ("x = \n", ("E0101", 1, 5, "unexpected end of line; expected an expression")),
    ("print 1 2\n", ("E0101", 1, 9, "unexpected number 2; expected an operator or end of line")),
    ("if 1 > 0 then\n", ("E0101", 1, 10, "unexpected name 'then'; expected an operator or '{'")),
    ("if x {\n}\n", ("E0101", 1, 6, "unexpected '{'; expected a comparison operator")),
    ("goto 3\n", ("E0101", 1, 6, "unexpected number 3; expected a name")),
    ("x = (1 + 2\n", ("E0101", 1, 11, "unexpected end of line; expected ')'")),
    ("x = 1\n}\n", ("E0107", 2, 1, "unmatched '}'")),
    ("print 1 print 2\n", ("E0101", 1, 9, "unexpected 'print'; expected an operator or end of line")),
    ("x = 1 @ 2\n", ("E0102", 1, 7, "unexpected character '@'")),
    ("print\n", ("E0101", 1, 6, "unexpected end of line; expected an expression or a string")),
    ("if 1 > 0 {\n    print 1\n\n", ("E0104", 1, 10, "this block is never closed; missing '}'")),
    ("x = (", ("E0103", 1, 6, "unexpected end of file; expected an expression")),
])
def test_syntax_error_messages(source, expected):
    assert syntax_errors(source) == [expected]


def test_syntax_errors_never_mention_grammar_internals():
    for source in ["x = \n", "}\n", "if 1 > 0 {", "print 1 2", "label\n", "x = = 1\n"]:
        ((_, _, _, message),) = syntax_errors(source)
        for internal in ("_NL", "$END", "IDENT", "LPAR", "LBRACE", "Token("):
            assert internal not in message, (source, message)


def test_newline_token_is_underlined_on_its_own_line():
    diags = Diagnostics("t.scribe")
    PARSER.parse("x = \nprint 1\n", diags)
    (diag,) = diags
    assert (diag.span.line, diag.span.end_line, diag.span.end_column) == (1, 1, 6)


def test_parse_without_a_collector_raises_with_the_diagnostics():
    with pytest.raises(ParseError) as info:
        PARSER.parse("x = \n")
    assert [d.code.code for d in info.value.diagnostics] == ["E0101"]


@pytest.mark.parametrize("expected, words", [
    ({"IDENT", "NUMBER", "LPAR", "SIGN"}, "an expression"),
    ({"PRINT", "INPUT", "IF", "WHILE", "LABEL", "GOTO", "IDENT", "LBRACE", "RBRACE", "_NL"},
     "a statement, '}' or end of line"),
    ({"_NL", "SEMICOLON", "$END"}, "end of line"),
    ({"$END"}, "end of file"),
    ({"ELSE"}, "'else'"),
    ({"ADD_OP", "MUL_OP"}, "an operator"),
    ({"SOME_NEW_TERMINAL"}, "SOME_NEW_TERMINAL"),
])
def test_describe_expected(expected, words):
    from scribe_lang.parser import describe_expected

    assert describe_expected(expected) == words


def test_every_grammar_terminal_has_a_readable_name():
    # Adding a terminal to the grammar without a word for it in parser.py
    # would leak its internal name into error messages.
    from scribe_lang.parser import _KEYWORDS, _TERMINAL_WORDS

    terminals = {t.name for t in PARSER._parser.terminals}
    ignored = {"COMMENT"} | {t for t in terminals if t.startswith("__")}
    assert terminals - ignored <= set(_TERMINAL_WORDS) | _KEYWORDS


# -- recovery: one error per broken statement ---------------------------------

def error_positions(source):
    return [(code, line, column) for code, line, column, _ in syntax_errors(source)]


def test_every_broken_statement_is_reported():
    source = "x = \nprint 1 2\ny = 3 @ 4; z = (\nprint \"ok\"\n"
    assert error_positions(source) == [("E0101", 1, 5), ("E0101", 2, 9), ("E0102", 3, 7), ("E0101", 3, 17)]


def test_statements_after_an_error_are_still_checked():
    assert error_positions("x = \nprint 1\nprint 2 2\n") == [("E0101", 1, 5), ("E0101", 3, 9)]


def test_errors_inside_a_block_keep_the_block():
    # Only the broken lines are skipped; the block and its braces survive, so
    # there is no follow-on error about the closing '}'.
    source = "while 1 > 0 {\n    a = \n    b = 1 1\n}\nc = \n"
    assert error_positions(source) == [("E0101", 2, 9), ("E0101", 3, 11), ("E0101", 5, 5)]


def test_an_error_in_a_block_header_skips_the_whole_block():
    # Errors inside the skipped body are not reported: the body is gone.
    source = "while x > {\n    y = \n}\nz = \n"
    assert error_positions(source) == [("E0101", 1, 11), ("E0101", 4, 5)]


def test_misplaced_else_skips_its_block_too():
    source = "if 1 > 0 {\n    print 1\n}\nelse {\n    print 2\n}\nx = \n"
    assert [line for _, line, _ in error_positions(source)] == [4, 7]


def test_braces_and_separators_in_strings_and_comments_do_not_confuse_recovery():
    source = 'print "a;{" 1\nx = 1 # { ;\ny = \n'
    assert error_positions(source) == [("E0101", 1, 13), ("E0101", 3, 5)]


def test_unterminated_string_skips_only_its_line():
    assert error_positions('print "abc\nx = \n') == [("E0106", 1, 7), ("E0101", 2, 5)]


def test_semicolon_separated_statements_recover_independently():
    assert error_positions("a = ; b = 1; c = 1 1\n") == [("E0101", 1, 5), ("E0101", 1, 20)]


def test_an_error_at_the_end_of_the_file_ends_recovery():
    codes = [code for code, _, _ in error_positions("x = \nif 1 > 0 {\n    print 1\n")]
    assert codes == ["E0101", "E0104"]


def test_recovery_stops_at_the_error_limit(monkeypatch):
    import scribe_lang.parser as parser_module

    monkeypatch.setattr(parser_module, "MAX_SYNTAX_ERRORS", 3)
    assert len(syntax_errors("a = \n" * 10)) == 3


def test_a_valid_program_after_recovery_still_returns_none():
    # Recovery only finds more errors; the program is still rejected.
    diags = Diagnostics()
    assert PARSER.parse("x = \nprint 1\n", diags) is None
    assert len(diags) == 1


# -- hints for common mistakes ------------------------------------------------

def first_error(source):
    diags = Diagnostics("t.scribe")
    assert PARSER.parse(source, diags) is None
    return diags.errors[0]


@pytest.mark.parametrize("word", ["else", "elif"])
def test_else_or_elif_on_a_new_line(word):
    source = f"if 1 > 0 {{\n    print 1\n}}\n{word}{' 2 > 1' if word == 'elif' else ''} {{\n    print 2\n}}\n"
    diag = first_error(source)
    assert diag.code.code == "E0105"
    assert (diag.span.line, diag.span.column, diag.span.end_column) == (4, 1, 5)
    assert diag.message == f"'{word}' must be on the same line as the '}}' that closes the if block"
    assert diag.help == f"join the lines: '}} {word} ...'"


@pytest.mark.parametrize("word", ["print", "while", "goto", "input", "label", "if"])
def test_assigning_to_a_keyword_is_explained(word):
    diag = first_error(f"{word} = 2\n")
    assert diag.code.code == "E0202"
    assert diag.message == f"'{word}' is a reserved word and cannot be used as a variable name"
    assert (diag.span.column, diag.span.end_column) == (1, 1 + len(word))


def test_keyword_hint_needs_the_keyword_to_start_the_statement():
    assert first_error("x print = 2\n").code.code == "E0101"


def test_unclosed_block_points_at_its_brace_and_the_end_of_file():
    diag = first_error("while 1 > 0 {\n    if 2 > 1 {\n        print 1\n    }\n")
    assert diag.code.code == "E0104"
    assert (diag.span.line, diag.span.column) == (1, 13)
    ((message, span),) = [(n.message, n.span) for n in diag.notes]
    assert message == "the file ends here"
    assert (span.line, span.column) == (4, 6)


def test_unclosed_block_names_the_innermost_open_brace():
    diag = first_error("{\n    {\n        print 1\n")
    assert (diag.code.code, diag.span.line, diag.span.column) == ("E0104", 2, 5)


def test_unclosed_block_ignores_braces_in_strings_and_comments():
    diag = first_error('{\n    print "}"\n    # }\n')
    assert (diag.code.code, diag.span.line) == ("E0104", 1)


def test_unmatched_closing_brace():
    diag = first_error("x = 1\n}\nprint x\n")
    assert (diag.code.code, diag.span.line, diag.span.column) == ("E0107", 2, 1)
    assert diag.message == "unmatched '}'"


def syntax_errors_full(source):
    diags = Diagnostics("t.scribe")
    PARSER.parse(source, diags)
    return list(diags)


def test_unmatched_brace_after_a_complete_block():
    assert [d.code.code for d in syntax_errors_full("{\n    print 1\n}\n}\n")] == ["E0107"]


def test_unterminated_string():
    diag = first_error('print "abc\n')
    assert diag.code.code == "E0106"
    assert (diag.span.column, diag.span.end_column) == (7, 11)


def test_invalid_escape_points_at_the_escape():
    diag = first_error('print "a\\qb"\n')
    assert diag.code.code == "E0108"
    assert diag.message == "invalid escape sequence '\\q' in string"
    assert (diag.span.column, diag.span.end_column) == (9, 11)


def test_valid_escapes_before_an_invalid_one_are_skipped():
    diag = first_error('print "\\n\\t\\"\\x"\n')
    assert (diag.code.code, diag.span.column) == ("E0108", 14)


def test_unterminated_string_after_valid_escapes():
    assert first_error('print "a\\"b\n').code.code == "E0106"


def test_every_hint_message_still_recovers():
    source = "else {\n}\nprint = 1\nx = \"abc\ny = }\nz = 1 1\n"
    codes = [d.code.code for d in syntax_errors_full(source)]
    assert codes == ["E0105", "E0202", "E0106", "E0107", "E0101"]
