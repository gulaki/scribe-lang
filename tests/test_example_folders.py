"""Keeps the example sub-folders honest.

examples/errors/  every file must be rejected, with the message its first line
                  promises (`# expect: <text>`).
examples/future/  proposals for later versions. They must NOT compile today:
                  if one starts compiling, move it out of future/ and record
                  its run in test_end_to_end.py.
"""
import pytest

from conftest import EXAMPLES

ERROR_EXAMPLES = sorted((EXAMPLES / "errors").glob("*.scribe"))
FUTURE_EXAMPLES = sorted((EXAMPLES / "future").rglob("*.scribe"))


@pytest.mark.parametrize("path", ERROR_EXAMPLES, ids=lambda p: p.stem)
def test_error_example_is_rejected_with_the_promised_message(compiler, path):
    source = path.read_text(encoding="utf-8")
    first = source.splitlines()[0]
    assert first.startswith("# expect: "), "first line must be '# expect: <message text>'"
    result = compiler.compile(source, filename=str(path))
    assert not result.ok
    assert first.removeprefix("# expect: ") in result.render()


@pytest.mark.parametrize("path", FUTURE_EXAMPLES, ids=lambda p: str(p.relative_to(EXAMPLES / "future")))
def test_future_example_is_not_supported_yet(compiler, path):
    assert not compiler.compile(path.read_text(encoding="utf-8"), filename=str(path)).ok
