"""Regression tests for bugs found in review. Each section names the bug.

End-to-end tests build the generated C with strict flags (see conftest.py) and
check what the program actually prints, because most of these bugs only show
up once a real C compiler gets involved.
"""
import pytest

from scribe_lang.build import BUILD_SYSTEMS, BuildConfig
from scribe_lang.cli import main
from scribe_lang.errors import ParseError, SemanticError
from scribe_lang.parser import Parser


def c_source(compiler, source):
    return compiler.compile(source).c_source


# -- Bug 1: number literals were emitted as C `int` literals ----------------
# Every Scribe value is a float, but `7` was emitted as the C int `7`, so
# arithmetic on literals used C integer rules.

def test_division_of_literals_is_float_division(run_scribe):
    assert run_scribe("print 7 / 2\n") == "3.50\n"


def test_literal_division_by_zero_is_not_integer_division(run_scribe):
    # Integer division by zero is undefined behaviour in C; float division
    # gives infinity.
    assert run_scribe("print 1 / 0\n") == "inf\n"


def test_literal_multiplication_does_not_overflow_int(run_scribe):
    assert run_scribe("print 65536 * 65536\n") == "4294967296.00\n"


def test_literal_wider_than_any_c_integer_compiles(run_scribe):
    assert run_scribe("print 99999999999999999999\n") == "100000002004087734272.00\n"


def test_comparison_of_literals_uses_float_values(run_scribe):
    assert run_scribe('if 7 / 2 == 3 {\n    print "int"\n} else {\n    print "float"\n}\n') == "float\n"


@pytest.mark.parametrize("literal, expected", [("7", "7.0f"), ("0", "0.0f"), ("2.5", "2.5f")])
def test_number_literals_are_emitted_as_c_float_literals(compiler, literal, expected):
    assert f"v_x = {expected};" in c_source(compiler, f"x = {literal}\n")


def test_literal_too_large_for_a_float_is_rejected(compiler):
    with pytest.raises(SemanticError, match="too large"):
        compiler.compile("x = " + "9" * 50 + "\n")


def test_largest_float_literal_is_accepted(compiler):
    compiler.compile("x = 340282346638528859811704183484516925440\n")


# -- Bug 2: string `print` used the text as a printf format string ----------

def test_percent_signs_in_strings_are_printed_literally(run_scribe):
    assert run_scribe('print "100% done %s %n %d"\n') == "100% done %s %n %d\n"


def test_string_print_does_not_go_through_printf(compiler):
    source = c_source(compiler, 'print "50%"\n')
    assert 'puts("50%");' in source
    assert 'printf("50%' not in source


# -- Bug 3: non-ASCII string text was double-encoded ------------------------
# `unicode_escape` decodes the UTF-8 bytes as Latin-1, so "é" became "Ã©".

def test_non_ascii_strings_round_trip(run_scribe):
    assert run_scribe('print "héllo ✓ 日本"\n') == "héllo ✓ 日本\n"


def test_non_ascii_string_is_decoded_once():
    stmt = Parser().parse('print "é"\n').statements[0]
    assert stmt.value == "é"


def test_non_ascii_text_is_emitted_as_escapes(compiler):
    # Plain ASCII C source cannot be misread under a different source charset.
    source = c_source(compiler, 'print "é"\n')
    assert 'puts("\\303\\251");' in source
    assert source.isascii()


# -- Bug 4: `\r` escapes and `??` sequences broke the C string literal ------

def test_carriage_return_and_tab_escapes(compiler, run_scribe):
    # A raw carriage return inside a C string literal ended the line, so the
    # C did not compile. (run_scribe reads stdout in text mode, which turns
    # the `\r` into `\n`, hence the C-level check too.)
    program = 'print "a\\rb\\tc"\n'
    assert 'puts("a\\rb\\tc");' in c_source(compiler, program)
    assert run_scribe(program) == "a\nb\tc\n"


def test_trigraph_like_text_is_printed_unchanged(run_scribe):
    # Under -std=c11 a C compiler replaces `??/` with `\`.
    assert run_scribe('print "what??/ ??= ??!"\n') == "what??/ ??= ??!\n"


@pytest.mark.parametrize("escape, expected", [
    ('\\"', '"'), ("\\\\", "\\"), ("\\n", "\n"), ("\\r", "\r"), ("\\t", "\t"),
])
def test_every_string_escape_decodes(escape, expected):
    assert Parser().parse(f'print "{escape}"\n').statements[0].value == expected


def test_escaped_backslash_followed_by_n_is_not_a_newline(run_scribe):
    assert run_scribe('print "a\\\\nb"\n') == "a\\nb\n"


# -- Bug 5: Scribe names collided with C keywords and <stdio.h> names -------
# Names were emitted verbatim, so `int = 1` declared `float int;`.

@pytest.mark.parametrize("name", [
    "int", "float", "return", "main", "printf", "puts", "scanf", "stdin",
    "EOF", "NULL", "FILE", "__x", "_X",
])
def test_variables_named_like_c_identifiers_work(run_scribe, name):
    assert run_scribe(f"{name} = 3\nprint {name} + 1\n") == "4.00\n"


@pytest.mark.parametrize("name", ["EOF", "int", "main", "BUFSIZ", "L_tmpnam"])
def test_labels_named_like_c_identifiers_work(run_scribe, name):
    program = f'goto {name}\nprint "skipped"\nlabel {name}\nprint "after"\n'
    assert run_scribe(program) == "after\n"


def test_block_variable_named_like_a_c_identifier_works(run_scribe):
    assert run_scribe("{\n    char = 2\n    input double\n    print char * double\n}\n", "5\n") == "10.00\n"


def test_variable_and_label_with_the_same_name(run_scribe):
    program = "x = 0\nlabel x\nx = x + 1\nif x < 3 {\n    goto x\n}\nprint x\n"
    assert run_scribe(program) == "3.00\n"


# -- Bug 6: build files pointed at the wrong paths --------------------------

def test_cli_writes_the_build_file_next_to_the_c_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "prog.scribe"
    src.write_text("print 1\n", encoding="utf-8")
    (tmp_path / "out").mkdir()
    assert main([str(src), "-o", "out/prog.c", "--build", "make"]) == 0
    assert (tmp_path / "out" / "Makefile").exists()
    assert not (tmp_path / "Makefile").exists()


@pytest.mark.parametrize("system", ["make", "ninja"])
def test_build_file_paths_are_relative_to_the_build_file(tmp_path, system):
    build_file = tmp_path / "build" / "rules"
    text = BUILD_SYSTEMS[system].generate(
        tmp_path / "gen" / "prog.c", tmp_path / "bin" / "prog", build_file, BuildConfig()
    )
    assert "../gen/prog.c" in text
    assert "../bin/prog" in text


def test_generated_makefile_builds_the_program(tmp_path, run_scribe):
    # run_scribe is only requested so the test skips without a C compiler.
    import shutil
    import subprocess

    if shutil.which("make") is None:
        pytest.skip("make not installed")
    src = tmp_path / "prog.scribe"
    src.write_text('print "built"\n', encoding="utf-8")
    out = tmp_path / "gen" / "prog.c"
    out.parent.mkdir()
    build_file = tmp_path / "build" / "Makefile"
    build_file.parent.mkdir()
    assert main([str(src), "-o", str(out), "--build", "make", "--build-output", str(build_file)]) == 0
    subprocess.run(["make", "-C", str(build_file.parent)], check=True, capture_output=True)
    run = subprocess.run([str(tmp_path / "gen" / "prog")], capture_output=True, text=True)
    assert run.stdout == "built\n"


# -- Bug 7: AST locations were lost for parenthesised expressions -----------

def test_grouped_expression_has_a_location():
    stmt = Parser().parse("x = (1) + 2\n").statements[0]
    assert stmt.value.location.line == 1
    assert stmt.value.left.location.line == 1


# -- Bug 8: parse error messages --------------------------------------------

def test_parse_error_without_filename_reads_cleanly():
    with pytest.raises(ParseError) as info:
        Parser().parse("x = \n")
    assert str(info.value).endswith(" at 1:5")


def test_parse_error_with_filename():
    with pytest.raises(ParseError) as info:
        Parser().parse("x = \n", "f.scribe")
    assert str(info.value).endswith(" at f.scribe:1:5")


def test_parse_error_at_end_of_input_names_it():
    with pytest.raises(ParseError) as info:
        Parser().parse("if 1 > 0 {")
    assert "unexpected end of input" in str(info.value)
    assert "$END" not in str(info.value)


# -- Bug 9: `input` used scanf("%f"), which is undefined for out-of-range text --

READ_AND_PRINT = "input a\ninput b\nprint a\nprint b\n"


@pytest.mark.parametrize("stdin, expected", [
    ("1.5\n2\n", "1.50\n2.00\n"),
    ("  7   \n\n 8\n", "7.00\n8.00\n"),               # any whitespace separates tokens
    ("1e999\n3\n", "0.00\n3.00\n"),                     # out of range: was undefined
    ("-1e999\n3\n", "0.00\n3.00\n"),
    ("nan\n3\n", "0.00\n3.00\n"),                       # non-finite is not a Scribe number
    ("inf\n3\n", "0.00\n3.00\n"),
    ("abc\n4\n", "0.00\n4.00\n"),                       # bad token consumed, next one read
    ("12abc\n4\n", "0.00\n4.00\n"),                     # trailing junk rejects the whole token
    ("9" * 200 + "\n5\n", "0.00\n5.00\n"),              # over-long token consumed entirely
    ("", "0.00\n0.00\n"),                               # end of input
    ("6", "6.00\n0.00\n"),                              # no trailing newline
])
def test_input_never_misreads_or_overflows(run_scribe, stdin, expected):
    assert run_scribe(READ_AND_PRINT, stdin) == expected


def test_input_helper_only_emitted_when_used(compiler):
    assert "scribe_read_float" not in c_source(compiler, "print 1\n")
    assert "scanf" not in c_source(compiler, "input x\n")


# -- Bug 10: comparisons were wrapped in a second pair of parentheses --------
# `if ((a == b))` makes clang warn (-Wparentheses-equality).

def test_conditions_have_a_single_pair_of_parentheses(compiler):
    source = c_source(compiler, "x = 1\nif x == 1 {\n    print x\n}\nwhile x < 3 {\n    x = x + 1\n}\n")
    assert "if (v_x == 1.0f) {" in source
    assert "while (v_x < 3.0f) {" in source
    assert "((" not in source.replace("(float)((", "")


def test_generated_c_builds_without_any_warning(compiler, tmp_path):
    import subprocess

    from conftest import C_COMPILER, EXAMPLES

    if C_COMPILER is None:
        pytest.skip("no C compiler")
    for example in sorted(EXAMPLES.glob("*.scribe")):
        c_file = tmp_path / f"{example.stem}.c"
        c_file.write_text(compiler.compile(example.read_text(encoding="utf-8")).c_source, encoding="utf-8")
        build = subprocess.run(
            [C_COMPILER, "-std=c11", "-pedantic-errors", "-Wall", "-Wextra", "-Werror",
             "-o", str(tmp_path / example.stem), str(c_file)],
            capture_output=True, text=True,
        )
        assert build.returncode == 0, f"{example.name}: {build.stderr}"
