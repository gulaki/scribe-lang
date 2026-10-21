"""Explicit declarations: `i64: a, b = 5` (docs/design/type-system.md)."""
from scribe_lang.types import F32, F64, I64


def codes(compiler, source):
    return [d.code.code for d in compiler.compile(source).diagnostics]


def test_declared_variables_start_at_zero_unless_initialised(run_scribe):
    assert run_scribe("i64: a, b = 5\nprint a\nprint b\n") == "0\n5\n"
    assert run_scribe("f64: x, y = 2.5\nf32: z\nprint x\nprint y\nprint z\n") == "0.00\n2.50\n0.00\n"


def test_declared_types(compiler):
    model = compiler.compile("i64: a\nf64: b = 1\nf32: c = 2.5\n").semantic_model
    assert [model.root.symbols[n].type for n in "abc"] == [I64, F64, F32]


def test_initialiser_follows_the_assignment_rules(compiler):
    assert codes(compiler, "i64: n = 2.5\n") == ["E0501"]
    assert codes(compiler, "n = 1\nf64: d = n\n") == ["E0501"]
    assert codes(compiler, "n = 1\nf64: d = f64(n)\n") == []
    assert codes(compiler, "f32: f = 16777217\n") == ["E0401"]


def test_later_declarators_see_earlier_ones(run_scribe):
    assert run_scribe("i64: a = 1, b = a + 1\nprint b\n") == "2\n"


def test_initialiser_cannot_read_the_variable_it_declares(compiler):
    assert codes(compiler, "i64: a = a\n") == ["E0201"]


def test_a_declared_variable_keeps_its_type(compiler):
    assert codes(compiler, "f32: f\nf = 0.5\nf = 1\n") == []
    assert codes(compiler, "i64: n\nn = 0.5\n") == ["E0501"]


def test_input_reads_the_declared_type(run_scribe):
    assert run_scribe("i64: n\ninput n\nprint n\n", "42\n") == "42\n"
    assert run_scribe("f32: f\ninput f\nprint f\n", "1.5\n") == "1.50\n"


def test_redeclaring_a_visible_variable_is_an_error(compiler):
    result = compiler.compile("x = 1\ni64: x\n")
    assert [d.code.code for d in result.diagnostics] == ["E0203"]
    assert result.diagnostics[0].notes[0].span.line == 1
    assert codes(compiler, "i64: x, x\n") == ["E0203"]
    # No shadowing: a nested block cannot declare a name that is visible.
    assert codes(compiler, "x = 1\n{\n    f64: x\n}\n") == ["E0203"]


def test_sibling_blocks_can_declare_the_same_name(run_scribe):
    assert run_scribe("{\n    i64: t = 1\n    print t\n}\n{\n    f64: t = 2\n    print t\n}\n") == "1\n2.00\n"


def test_declaring_a_reserved_word_is_an_error(compiler):
    assert codes(compiler, "i64: print\n") == ["E0202"]
    assert codes(compiler, "i64: u8\n") == ["E0202"]


def test_a_declaration_resets_the_variable_every_time_it_runs(run_scribe):
    # In a loop body the block is entered afresh; after a backward goto the
    # same declaration runs again. Either way the variable starts at 0.
    loop = "i = 0\nwhile i < 3 {\n    i64: count\n    count = count + 1\n    print count\n    i = i + 1\n}\n"
    assert run_scribe(loop) == "1\n1\n1\n"
    backward = "n = 0\nlabel again\ni64: x\nx = x + 1\nn = n + 1\nif n < 3 {\n    goto again\n}\nprint x\n"
    assert run_scribe(backward) == "1\n"


def test_declaration_emits_an_assignment(compiler):
    source = compiler.compile("i64: a, b = 5\nf32: c\n").c_source
    assert "int64_t v_a;" in source and "float v_c;" in source
    assert "    v_a = INT64_C(0);\n    v_b = INT64_C(5);\n    v_c = 0.0f;\n" in source


def test_declaration_in_a_block_is_hoisted(compiler):
    source = compiler.compile("{\n    print 1\n    f64: d = 2\n}\n").c_source
    assert "    {\n        double v_d = 0;\n" in source
    assert "        v_d = 2.0;\n" in source
