"""The power operator `**` (docs/language.md, "Powers"), and the headers and
libraries a program needs only when it uses them."""
import pytest

from scribe_lang.build import BUILD_SYSTEMS, BuildConfig


# -- includes and libraries on demand -------------------------------------------------

def test_a_program_without_input_or_output_has_no_stdio(compiler):
    result = compiler.compile("a = 1.5\nb = a * 2\n")
    assert "stdio.h" not in result.c_source
    assert result.link_libraries == ()


@pytest.mark.parametrize("source", ['print "hi"\n', "print 1\n", "i64: n\ninput n\n", "a = 9223372036854775807\nb = a + 1\n"])
def test_input_output_and_runtime_checks_include_stdio(compiler, source):
    assert compiler.compile(source).c_source.startswith("#include <stdio.h>\n")


def test_programs_without_library_functions_need_no_libraries(compiler):
    result = compiler.compile("x = 2.5\nprint x * x\nn = 7\nprint n // 2\n")
    assert result.link_libraries == ()
    assert "Link with" not in result.c_source


@pytest.mark.parametrize("system, line", [("make", "LDLIBS ?= -lm"), ("ninja", "libs = -lm")])
def test_build_files_link_the_libraries(tmp_path, system, line):
    text = BUILD_SYSTEMS[system].generate(
        tmp_path / "prog.c", tmp_path / "prog", tmp_path / "rules", BuildConfig(libraries=("m",))
    )
    assert line in text
    assert "$(LDLIBS)" in text if system == "make" else "$in $libs" in text


@pytest.mark.parametrize("system, line", [("make", "LDLIBS ?=\n"), ("ninja", "libs =\n")])
def test_build_files_without_libraries(tmp_path, system, line):
    text = BUILD_SYSTEMS[system].generate(tmp_path / "prog.c", tmp_path / "prog", tmp_path / "rules", BuildConfig())
    assert line in text
