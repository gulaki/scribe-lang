import re
from pathlib import Path

import pytest

import scribe_lang
from scribe_lang.ast import Block, Let, Number, Program
from scribe_lang.errors import SemanticError
from scribe_lang.semantics import RESERVED_WORDS, SemanticAnalyzer


def names(scope):
    return list(scope.symbols)


def error_text(compiler, source):
    with pytest.raises(SemanticError) as info:
        compiler.compile(source)
    return str(info.value)


# -- scoping ----------------------------------------------------------------

def test_first_assignment_in_a_block_declares_it_in_that_block(compiler):
    result = compiler.compile("if 1 > 0 {\n    a = 1\n}\n")
    block = result.ast.statements[0].body
    assert names(result.semantic_model.scopes[block]) == ["a"]
    assert names(result.semantic_model.root) == []


def test_assignment_to_a_visible_variable_does_not_redeclare(compiler):
    result = compiler.compile("x = 1\n{\n    x = 2\n}\nprint x\n")
    block = result.ast.statements[1]
    assert names(result.semantic_model.root) == ["x"]
    assert names(result.semantic_model.scopes[block]) == []


def test_block_variable_is_not_visible_after_the_block(compiler):
    text = error_text(compiler, "if 1 > 0 {\n    y = 1\n}\nprint y\n")
    assert "undeclared variable 'y'" in text
    assert "block that ended" in text
    assert "at 4:7" in text


def test_use_before_first_assignment_in_a_block_is_rejected(compiler):
    assert "undeclared variable 'z'" in error_text(compiler, "{\n    print z\n    z = 1\n}\n")


def test_sibling_blocks_declare_independent_variables(compiler):
    result = compiler.compile("if 1 > 0 {\n    t = 1\n} else {\n    t = 2\n}\n")
    stmt = result.ast.statements[0]
    model = result.semantic_model
    assert names(model.scopes[stmt.body]) == ["t"]
    assert names(model.scopes[stmt.orelse]) == ["t"]
    assert model.scopes[stmt.body].symbols["t"] is not model.scopes[stmt.orelse].symbols["t"]
    assert names(model.root) == []


def test_variable_from_if_body_is_not_visible_in_else(compiler):
    text = error_text(compiler, "if 1 > 0 {\n    v = 1\n} else {\n    print v\n}\n")
    assert "undeclared variable 'v'" in text


def test_variable_from_if_body_is_not_visible_in_elif_condition(compiler):
    text = error_text(compiler, "if 1 > 0 {\n    v = 1\n} elif v > 0 {\n}\n")
    assert "undeclared variable 'v'" in text


def test_nested_blocks_see_enclosing_variables(compiler):
    result = compiler.compile(
        "x = 3\nif x > 0 {\n    while x > 0 {\n        x = x - 1\n    }\n}\n"
    )
    assert names(result.semantic_model.root) == ["x"]
    assert all(names(scope) == [] for scope in result.semantic_model.scopes.values())


def test_same_name_declared_in_block_then_later_at_program_level(compiler):
    result = compiler.compile("if 1 > 0 {\n    x = 1\n}\nx = 2\nprint x\n")
    block = result.ast.statements[0].body
    assert names(result.semantic_model.scopes[block]) == ["x"]
    assert names(result.semantic_model.root) == ["x"]


def test_declaration_order_is_first_assignment_order(compiler):
    result = compiler.compile("{\n    b = 1\n    a = 2\n    b = 3\n}\n")
    assert names(result.semantic_model.scopes[result.ast.statements[0]]) == ["b", "a"]


def test_input_declares_like_an_assignment(compiler):
    result = compiler.compile("input n\n{\n    input m\n    print m\n    input n\n}\n")
    model = result.semantic_model
    assert names(model.root) == ["n"]
    assert names(model.scopes[result.ast.statements[1]]) == ["m"]


def test_loop_body_variable_is_not_visible_in_the_loop_condition(compiler):
    text = error_text(compiler, "while k < 3 {\n    k = 1\n}\n")
    assert "undeclared variable 'k'" in text


def test_every_block_gets_its_own_scope(compiler):
    result = compiler.compile(
        "if 1 > 0 {\n} elif 1 > 0 {\n} else {\n}\nwhile 0 > 1 {\n}\n{\n}\n"
    )
    assert len(result.semantic_model.scopes) == 5


def test_identical_blocks_still_get_separate_scopes():
    # Hand-built AST with two indistinguishable blocks (same contents, default
    # locations). If Block compared by value they would share one scope entry.
    def make():
        return Block((Let("a", Number("1")),))

    first, second = make(), make()
    model = SemanticAnalyzer().analyze(Program((first, second)))
    assert len(model.scopes) == 2
    assert model.scopes[first] is not model.scopes[second]
    assert names(model.scopes[first]) == names(model.scopes[second]) == ["a"]


# -- right-hand side is checked before the target is declared ---------------

def test_self_reference_on_first_assignment_is_rejected(compiler):
    assert "undeclared variable 'x'" in error_text(compiler, "x = x + 1\n")
    assert "undeclared variable 'q'" in error_text(compiler, "{\n    q = q + 1\n}\n")


def test_self_reference_is_fine_once_the_variable_exists(compiler):
    compiler.compile("x = 1\nx = x + 1\n{\n    x = x * 2\n}\n")


# -- goto and labels ---------------------------------------------------------

def test_goto_out_of_a_block_is_allowed(compiler):
    compiler.compile("i = 0\nlabel again\ni = i + 1\nif i < 3 {\n    goto again\n}\n")


def test_goto_within_the_same_block_is_allowed(compiler):
    compiler.compile("{\n    label a\n    goto a\n}\n")


def test_forward_goto_to_a_label_in_the_enclosing_block_is_allowed(compiler):
    compiler.compile("if 1 > 0 {\n    goto done\n}\nlabel done\n")


def test_goto_into_a_nested_block_is_rejected(compiler):
    text = error_text(compiler, "goto inside\n{\n    label inside\n    print 1\n}\n")
    assert "jumps into a nested block" in text
    assert "'inside'" in text


def test_goto_into_an_if_body_is_rejected(compiler):
    text = error_text(compiler, "goto inside\nif 1 > 0 {\n    label inside\n}\n")
    assert "jumps into a nested block" in text


def test_goto_into_a_sibling_block_is_rejected(compiler):
    text = error_text(compiler, "{\n    goto there\n}\n{\n    label there\n}\n")
    assert "jumps into a nested block" in text


def test_duplicate_label_across_blocks_is_rejected(compiler):
    assert "duplicate label" in error_text(compiler, "label a\n{\n    label a\n}\n")


def test_undeclared_goto_inside_a_block_is_rejected(compiler):
    assert "undeclared label" in error_text(compiler, "{\n    goto nowhere\n}\n")


# -- reserved words ----------------------------------------------------------

@pytest.mark.parametrize("word", ["else", "elif"])
def test_assigning_to_a_keyword_is_rejected(compiler, word):
    # `else` / `elif` are not valid at the start of a statement, so the lexer
    # hands them to the parser as plain identifiers.
    assert "reserved word" in error_text(compiler, f"{word} = 3\n")


@pytest.mark.parametrize("word", sorted(RESERVED_WORDS))
def test_input_into_a_keyword_is_rejected(compiler, word):
    assert "reserved word" in error_text(compiler, f"input {word}\n")


@pytest.mark.parametrize("word", sorted(RESERVED_WORDS))
def test_keyword_as_a_label_name_is_rejected(compiler, word):
    assert "reserved word" in error_text(compiler, f"label {word}\n")


def test_reserved_words_match_the_keywords_in_the_grammar():
    grammar = Path(scribe_lang.__file__).parent / "grammar" / "scribe_lang.lark"
    keywords = set(re.findall(r'^[A-Z_]+:\s*"([a-z]+)"\s*$', grammar.read_text(), re.MULTILINE))
    assert keywords == set(RESERVED_WORDS)
