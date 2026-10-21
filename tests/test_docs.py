"""Keeps the documentation honest.

Code blocks in README.md, docs/ and examples/README.md are checked by their
fence tag:

```scribe        must compile with no diagnostics. If an ```output block
                 follows it directly, the program is built and run, and its
                 stdout must match. A first line `# stdin: 5\\n3` gives it input.
```scribe-error  must be rejected with exactly the diagnostics its
                 `# expect: <code> at <line>:<column>` lines list.

Proposed syntax that does not compile yet goes in untagged or ```text blocks.
Every relative link in those files must point to a file that exists.
"""
import re
from pathlib import Path

import pytest

from conftest import expected_diagnostics

ROOT = Path(__file__).resolve().parent.parent
DOCS = [ROOT / "README.md", ROOT / "examples" / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]

FENCE = re.compile(r"^```([\w-]*)\n(.*?)^```$", re.MULTILINE | re.DOTALL)
LINK = re.compile(r"\]\(([^)\s]+)\)")


def blocks(path: Path):
    """(tag, body, line, next block) for each fenced block in `path`.
    `next block` is the (tag, body) directly after it, if only blank lines
    separate them."""
    text = path.read_text(encoding="utf-8")
    found = [(m.group(1), m.group(2), text.count("\n", 0, m.start()) + 1, m.start(), m.end())
             for m in FENCE.finditer(text)]
    for i, (tag, body, line, _, end) in enumerate(found):
        following = None
        if i + 1 < len(found) and not text[end:found[i + 1][3]].strip():
            following = found[i + 1][:2]
        yield tag, body, line, following


def snippets(tag: str):
    for path in DOCS:
        for block_tag, body, line, following in blocks(path):
            if block_tag == tag:
                yield pytest.param(body, following, id=f"{path.relative_to(ROOT)}:{line}")


@pytest.mark.parametrize("source, following", list(snippets("scribe")))
def test_scribe_snippet_compiles(compiler, source, following):
    result = compiler.compile(source)
    assert result.diagnostics == (), result.render()


@pytest.mark.parametrize("source, following", [
    p for p in snippets("scribe") if p.values[1] is not None and p.values[1][0] == "output"
])
def test_scribe_snippet_prints_its_output(run_scribe, source, following):
    stdin = ""
    first = source.split("\n", 1)[0]
    if first.startswith("# stdin:"):
        stdin = first.removeprefix("# stdin:").strip().replace("\\n", "\n") + "\n"
    assert run_scribe(source, stdin) == following[1]


@pytest.mark.parametrize("source, following", list(snippets("scribe-error")))
def test_scribe_error_snippet_reports_the_expected_errors(compiler, source, following):
    expected = expected_diagnostics(source)
    assert expected, "list the expected errors as '# expect: <code> at <line>:<column>'"
    result = compiler.compile(source)
    assert [(d.code.code, d.span.line, d.span.column) for d in result.diagnostics] == expected, result.render()


@pytest.mark.parametrize("path", DOCS, ids=lambda p: str(p.relative_to(ROOT)))
def test_relative_links_point_to_existing_files(path):
    text = FENCE.sub("", path.read_text(encoding="utf-8"))
    broken = []
    for target in LINK.findall(text):
        if re.match(r"[a-z]+:", target) or target.startswith("#"):
            continue  # a URL or an anchor in the same file
        if not (path.parent / target.split("#")[0]).exists():
            broken.append(target)
    assert not broken, f"broken links: {broken}"


def test_language_reference_lists_every_reserved_word():
    from scribe_lang.semantics import RESERVED_WORDS

    text = (ROOT / "docs" / "language.md").read_text(encoding="utf-8")
    section = text.split("## Reserved words", 1)[1].split("\n## ", 1)[0]
    missing = sorted(word for word in RESERVED_WORDS if f"`{word}`" not in section)
    assert not missing, f"add to the reserved words in docs/language.md: {missing}"
