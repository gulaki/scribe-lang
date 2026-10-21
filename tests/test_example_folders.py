"""Keeps the example sub-folders honest.

examples/errors/  every file must be rejected with exactly the diagnostics its
                  header lists, one `# expect: <code> at <line>:<column>` line
                  each, in order. Nothing missing and nothing extra, so a
                  cascade of follow-on errors fails the test too.
examples/future/  proposals for later versions. They must NOT compile today:
                  if one starts compiling, move it out of future/ and record
                  its run in test_end_to_end.py.
"""
import re

import pytest

from scribe_lang import diagnostics

from conftest import EXAMPLES

ERROR_EXAMPLES = sorted((EXAMPLES / "errors").glob("*.scribe"))
FUTURE_EXAMPLES = sorted((EXAMPLES / "future").rglob("*.scribe"))

EXPECT = re.compile(r"# expect: (?P<code>[EW]\d{4}) at (?P<line>\d+):(?P<column>\d+)$")

# Codes that no source file can trigger: they come from the driver.
NOT_FROM_SOURCE = {diagnostics.INTERNAL_ERROR.code, diagnostics.CANNOT_READ_SOURCE.code}


def expected_diagnostics(source):
    found = []
    for line in source.splitlines():
        if line.startswith("# expect:"):
            match = EXPECT.match(line)
            assert match, f"malformed expectation: {line!r}"
            found.append((match["code"], int(match["line"]), int(match["column"])))
    return found


@pytest.mark.parametrize("path", ERROR_EXAMPLES, ids=lambda p: p.stem)
def test_error_example_reports_exactly_the_expected_diagnostics(compiler, path):
    source = path.read_text(encoding="utf-8")
    expected = expected_diagnostics(source)
    assert expected, "list the expected errors as '# expect: <code> at <line>:<column>'"
    result = compiler.compile(source, filename=str(path))
    assert not result.ok
    actual = [(d.code.code, d.span.line, d.span.column) for d in result.diagnostics]
    assert actual == expected, result.render()


def test_every_error_code_has_an_example():
    covered = {code for path in ERROR_EXAMPLES for code, _, _ in expected_diagnostics(path.read_text(encoding="utf-8"))}
    missing = set(diagnostics.CODES) - NOT_FROM_SOURCE - covered
    assert not missing, f"add an examples/errors/ file for {sorted(missing)}"


@pytest.mark.parametrize("path", FUTURE_EXAMPLES, ids=lambda p: str(p.relative_to(EXAMPLES / "future")))
def test_future_example_is_not_supported_yet(compiler, path):
    assert not compiler.compile(path.read_text(encoding="utf-8"), filename=str(path)).ok
