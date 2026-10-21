import pytest


def c_source(compiler, source):
    return compiler.compile(source).c_source


def test_block_variables_are_declared_at_the_top_of_the_c_block(compiler):
    source = c_source(compiler, "if 1 > 0 {\n    a = 1\n    b = a + 1\n}\n")
    assert (
        "    if (INT64_C(1) > INT64_C(0)) {\n"
        "        int64_t v_a = 0;\n"
        "        int64_t v_b = 0;\n"
        "        v_a = INT64_C(1);\n"
        "        v_b = scribe_add_i64(v_a, INT64_C(1), 0);\n"
        "    }\n"
    ) in source


def test_program_level_variables_stay_global(compiler):
    source = c_source(compiler, "x = 1\nprint x\n")
    assert "int64_t v_x;\n" in source
    assert "int64_t v_x = 0;" not in source


def test_block_variables_are_not_in_the_global_header(compiler):
    source = c_source(compiler, "if 1 > 0 {\n    t = 1\n}\n")
    assert "int64_t v_t;" not in source
    assert "int64_t v_t = 0;" in source


def test_globals_are_declared_in_sorted_order(compiler):
    source = c_source(compiler, "b = 1\na = 2\nprint a + b\n")
    assert source.index("int64_t v_a;") < source.index("int64_t v_b;")


def test_if_elif_else_becomes_an_else_if_chain(compiler):
    source = c_source(compiler, '''\
x = 1
if x > 0 {
    print "p"
} elif x < 0 {
    print "n"
} elif x == 0 {
    print "z"
} else {
    print "o"
}
''')
    assert "    if (v_x > INT64_C(0)) {\n" in source
    assert "    } else if (v_x < INT64_C(0)) {\n" in source
    assert "    } else if (v_x == INT64_C(0)) {\n" in source
    assert "    } else {\n" in source
    assert source.count("else if") == 2


def test_if_without_else_emits_no_else(compiler):
    assert "else" not in c_source(compiler, "if 1 > 0 {\n    print 1\n}\n")


def test_standalone_block_emits_its_own_braces(compiler):
    source = c_source(compiler, "{\n    a = 1\n}\n")
    assert "    {\n        int64_t v_a = 0;\n        v_a = INT64_C(1);\n    }\n" in source


def test_empty_block_emits_empty_braces(compiler):
    assert "    if (INT64_C(1) > INT64_C(0)) {\n    }\n" in c_source(compiler, "if 1 > 0 {\n}\n")


def test_nested_blocks_indent_one_level_per_block(compiler):
    source = c_source(compiler, "x = 1\nif x > 0 {\n    while x > 0 {\n        x = x - 1\n    }\n}\n")
    assert "    if (v_x > INT64_C(0)) {\n" in source
    assert "        while (v_x > INT64_C(0)) {\n" in source
    assert "            v_x = scribe_sub_i64(v_x, INT64_C(1), 0);\n" in source


def test_labels_are_emitted_as_null_statements(compiler):
    source = c_source(compiler, "label end\n")
    assert "\nl_end:;\n" in source


def test_output_is_deterministic(compiler):
    program = "x = 1\nif x > 0 {\n    a = 1\n    b = 2\n} else {\n    c = 3\n}\n"
    assert c_source(compiler, program) == c_source(compiler, program)


def test_declarations_use_each_variables_type(compiler):
    source = c_source(compiler, "a = 1\nb = 1.0\nc = 1.0f\n{\n    d = 2.0f\n}\n")
    assert "int64_t v_a;\ndouble v_b;\nfloat v_c;\n" in source
    assert "        float v_d = 0;\n" in source


def test_runtime_checks_record_their_source_position(compiler):
    source = compiler.compile("x = 1\ny = x * x\nz = -y\n", filename="p.scribe").c_source
    assert '    "p.scribe:2:7",\n    "p.scribe:3:5",\n' in source
    assert "v_y = scribe_mul_i64(v_x, v_x, 0);" in source
    assert "v_z = scribe_neg_i64(v_y, 1);" in source


@pytest.mark.parametrize("program, expected", [
    ("x = 0.5\n", "v_x = 0.5;"),
    ("x = 0.1\n", "v_x = 0x1.999999999999ap-4 /* 0.1 */;"),
    ("x = 0.1f\n", "v_x = 0x1.99999ap-4f /* 0.1 */;"),
    ("x = 1.0\nx = 3\n", "v_x = 3.0;"),
    ("x = -9223372036854775808\n", "v_x = (-INT64_C(9223372036854775807) - 1);"),
    ("x = -5\n", "v_x = (-INT64_C(5));"),
    # 2**-1074: the shortest decimal (5e-324) is not the exact value.
    ("x = 4.9406564584124654e-324\n", "v_x = 0x0.0000000000001p-1022 /* 5e-324 */;"),
])
def test_literal_spelling(compiler, program, expected):
    assert expected in c_source(compiler, program)


def test_mixed_float_widths_widen_the_f32_operand(compiler):
    assert "((v_f + ((double)v_g)))" in c_source(compiler, "f = 1.0\ng = 1.0f\nprint (f + g)\n").replace(
        "printf(\"%.2f\\n\", ", "(")
