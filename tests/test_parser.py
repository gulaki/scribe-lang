import pytest

from scribe_lang.ast import Block, Elif, If, Let, Print, While
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
    with pytest.raises(ParseError) as info:
        PARSER.parse("if 1 > 0 then\n", "prog.scribe")
    assert str(info.value).endswith("prog.scribe:1:10")


def test_removed_keywords_are_ordinary_identifiers():
    program = parse("then = 1\nendif = 2\nrepeat = 3\nendwhile = 4\n")
    assert [stmt.name for stmt in program.statements] == ["then", "endif", "repeat", "endwhile"]
