def c_source(compiler, source):
    return compiler.compile(source).c_source


def test_block_variables_are_declared_at_the_top_of_the_c_block(compiler):
    source = c_source(compiler, "if 1 > 0 {\n    a = 1\n    b = a + 1\n}\n")
    assert (
        "    if (1.0f > 0.0f) {\n"
        "        float v_a = 0;\n"
        "        float v_b = 0;\n"
        "        v_a = 1.0f;\n"
        "        v_b = (v_a + 1.0f);\n"
        "    }\n"
    ) in source


def test_program_level_variables_stay_global(compiler):
    source = c_source(compiler, "x = 1\nprint x\n")
    assert "float v_x;\n" in source
    assert "float v_x = 0;" not in source


def test_block_variables_are_not_in_the_global_header(compiler):
    source = c_source(compiler, "if 1 > 0 {\n    t = 1\n}\n")
    assert "float v_t;" not in source
    assert "float v_t = 0;" in source


def test_globals_are_declared_in_sorted_order(compiler):
    source = c_source(compiler, "b = 1\na = 2\nprint a + b\n")
    assert source.index("float v_a;") < source.index("float v_b;")


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
    assert "    if (v_x > 0.0f) {\n" in source
    assert "    } else if (v_x < 0.0f) {\n" in source
    assert "    } else if (v_x == 0.0f) {\n" in source
    assert "    } else {\n" in source
    assert source.count("else if") == 2


def test_if_without_else_emits_no_else(compiler):
    assert "else" not in c_source(compiler, "if 1 > 0 {\n    print 1\n}\n")


def test_standalone_block_emits_its_own_braces(compiler):
    source = c_source(compiler, "{\n    a = 1\n}\n")
    assert "    {\n        float v_a = 0;\n        v_a = 1.0f;\n    }\n" in source


def test_empty_block_emits_empty_braces(compiler):
    assert "    if (1.0f > 0.0f) {\n    }\n" in c_source(compiler, "if 1 > 0 {\n}\n")


def test_nested_blocks_indent_one_level_per_block(compiler):
    source = c_source(compiler, "x = 1\nif x > 0 {\n    while x > 0 {\n        x = x - 1\n    }\n}\n")
    assert "    if (v_x > 0.0f) {\n" in source
    assert "        while (v_x > 0.0f) {\n" in source
    assert "            v_x = (v_x - 1.0f);\n" in source


def test_labels_are_emitted_as_null_statements(compiler):
    source = c_source(compiler, "label end\n")
    assert "\nl_end:;\n" in source


def test_output_is_deterministic(compiler):
    program = "x = 1\nif x > 0 {\n    a = 1\n    b = 2\n} else {\n    c = 3\n}\n"
    assert c_source(compiler, program) == c_source(compiler, program)
